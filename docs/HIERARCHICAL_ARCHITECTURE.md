# 계층형 오케스트레이터 아키텍처 설계

## 1. 개요

### 배경
기존 A2A 시스템은 **단일 Orchestrator → 다수 Agent** 의 플랫(flat) 토폴로지였습니다. 이 구조는 단순하지만, 팀 간 독립적인 토론 결과를 상위 레벨에서 다시 합성해야 하는 요구사항을 처리할 수 없었습니다.

### 목표
- Orchestrator를 Agent처럼 상위 Orchestrator에 등록 가능하게 확장
- 계층 깊이에 제한 없는 재귀적 구조 지원
- 기존 단일 계층 구조와 100% 하위 호환

### 핵심 원리
> **A2A 프로토콜의 동일 인터페이스 특성**: Orchestrator이든 Agent이든 동일한 `message/send` 엔드포인트로 통신하므로, 상위에서는 하위가 어떤 유형인지 알 필요 없이 동일한 방식으로 호출할 수 있습니다.

---

## 2. 아키텍처 설계

### 2.1 기존 구조 (Flat)

```
┌─────────────────────────────────┐
│         Client (사용자)          │
└──────────────┬──────────────────┘
               │ POST /debate
               ▼
┌─────────────────────────────────┐
│       Orchestrator (:8000)      │
│  - 토론 조율                     │
│  - 보고서 생성                   │
└──┬──────────┬───────────────┬───┘
   │          │               │
   ▼          ▼               ▼
┌──────┐  ┌──────┐       ┌──────┐
│Agent │  │Agent │  ...  │Agent │
│  A   │  │  B   │       │  N   │
└──────┘  └──────┘       └──────┘
```

### 2.2 계층형 구조 (Hierarchical)

```
┌─────────────────────────────────────────┐
│             Client (사용자)              │
└──────────────────┬──────────────────────┘
                   │ POST /debate
                   ▼
┌─────────────────────────────────────────┐
│       Meta-Orchestrator (:9000)         │
│  - 하위 오케스트레이터 조율              │
│  - 팀 간 의견 종합                       │
└──┬──────────────────┬───────────────┬───┘
   │ A2A message/send │               │
   ▼                  ▼               ▼
┌──────────────┐  ┌──────────────┐  ┌──────┐
│ Sub-Orch A   │  │ Sub-Orch B   │  │Agent │
│   (:8000)    │  │   (:8100)    │  │  C   │
│ agent_type=  │  │ agent_type=  │  │      │
│ orchestrator │  │ orchestrator │  │      │
└──┬───────┬───┘  └──┬───────┬───┘  └──────┘
   │       │         │       │
   ▼       ▼         ▼       ▼
┌─────┐ ┌─────┐  ┌─────┐ ┌─────┐
│ A-1 │ │ A-2 │  │ B-1 │ │ B-2 │
└─────┘ └─────┘  └─────┘ └─────┘
```

### 2.3 설계 원칙

| 원칙 | 설명 |
|------|------|
| **프로토콜 투명성** | 상위 Orchestrator는 하위가 Agent인지 Orchestrator인지 A2A 프로토콜 레벨에서 구분하지 않음 |
| **자기 등록(Self-Registration)** | 하위 Orchestrator가 시작 시 상위에 자동 등록 (`PARENT_ORCHESTRATOR_URL` 설정) |
| **타임아웃 분리** | `agent_type=orchestrator`인 대상은 내부 토론 시간을 고려한 확장 타임아웃 적용 |
| **하위 호환** | `PARENT_ORCHESTRATOR_URL`을 설정하지 않으면 기존 단일 계층과 동일하게 동작 |
| **재귀 가능** | 3단계 이상 중첩도 동일 메커니즘으로 지원 |

---

## 3. 통신 흐름

### 3.1 시퀀스 다이어그램: 계층형 토론

```
Client          Meta-Orch(:9000)      Sub-Orch-A(:8000)     Agent A-1    Agent A-2    Sub-Orch-B(:8100)
  │                    │                     │                  │            │              │
  │ POST /debate       │                     │                  │            │              │
  │ {"topic":"..."}    │                     │                  │            │              │
  ├───────────────────→│                     │                  │            │              │
  │                    │                     │                  │            │              │
  │                    │  [스킬 매칭]         │                  │            │              │
  │                    │  Sub-Orch-A,B 선택   │                  │            │              │
  │                    │                     │                  │            │              │
  │                    │  ─── 라운드 0: 초기 의견 수집 ──────────────────────────────────────│
  │                    │                     │                  │            │              │
  │                    │  A2A message/send   │                  │            │              │
  │                    │  (timeout=600s)     │                  │            │              │
  │                    ├────────────────────→│                  │            │              │
  │                    │                     │                  │            │              │
  │                    │                     │ ┌─ 내부 토론 ──┐ │            │              │
  │                    │                     │ │ gather()     │ │            │              │
  │                    │                     │ │ A2A send     ├→│            │              │
  │                    │                     │ │              │ │←───────────│              │
  │                    │                     │ │ A2A send     ├──────────────→│             │
  │                    │                     │ │              │ │←────────────│             │
  │                    │                     │ │ synthesize() │ │            │              │
  │                    │                     │ └──────────────┘ │            │              │
  │                    │                     │                  │            │              │
  │                    │←────────────────────┤                  │            │              │
  │                    │  "팀A 토론 결과:..."  │                  │            │              │
  │                    │                     │                  │            │              │
  │                    │  A2A message/send   │                  │            │              │
  │                    ├──────────────────────────────────────────────────────────────────→│
  │                    │                     │                  │            │   ┌─ 내부 토론│
  │                    │                     │                  │            │   │          │
  │                    │                     │                  │            │   └──────────│
  │                    │←──────────────────────────────────────────────────────────────────┤
  │                    │  "팀B 토론 결과:..."  │                  │            │              │
  │                    │                     │                  │            │              │
  │                    │  ─── 라운드 1: 상호 토론 ───────────────────────────────────────────│
  │                    │  (팀B 결과를 팀A에 전달, 그 반대도)      │            │              │
  │                    │                     │                  │            │              │
  │                    │  ─── 최종 종합 ─────│──────────────────│────────────│──────────────│
  │                    │  synthesize_with_claude()              │            │              │
  │                    │                     │                  │            │              │
  │← 종합 보고서        │                     │                  │            │              │
  │                    │                     │                  │            │              │
```

### 3.2 등록 흐름

```
1. Meta-Orchestrator 시작 (:9000)
   └─ agents.json 로드 (비어 있거나 사전 정의된 에이전트)

2. Sub-Orchestrator A 시작 (:8000)
   ├─ 자체 agents.json 로드 (팀 A 에이전트)
   └─ lifespan hook → POST /agents/register to :9000
       {
         "name": "Team-A-Orchestrator",
         "url": "http://localhost:8000",
         "agent_type": "orchestrator",     ← 핵심: orchestrator로 등록
         "skills": ["backend", "api-design"]
       }

3. Sub-Orchestrator B 시작 (:8100)
   └─ 동일 과정으로 :9000에 등록

4. Meta-Orchestrator의 registered_agents:
   [
     {name: "Team-A-Orchestrator", type: "orchestrator", url: ":8000"},
     {name: "Team-B-Orchestrator", type: "orchestrator", url: ":8100"}
   ]
```

---

## 4. 핵심 구현 상세

### 4.1 `AgentInfo.agent_type`

```python
@dataclass
class AgentInfo:
    name: str
    url: str
    agent_type: str = "agent"  # "agent" | "orchestrator"
    ...
```

`call_agent()` 함수는 이 필드를 확인하여:
- `"agent"` → 기존 `http_client` 사용 (120s 타임아웃)
- `"orchestrator"` → 전용 `httpx.AsyncClient(timeout=600s)` 생성 후 사용

### 4.2 `OrchestratorConfig` 계층형 필드

```python
@dataclass
class OrchestratorConfig:
    ...
    parent_url: str = ""              # 상위 오케스트레이터 URL
    public_url: str = ""              # 상위에서 접근 가능한 자신의 URL
    skills: str = ""                  # 상위에 광고할 스킬 목록
    sub_orchestrator_timeout: float = 600.0  # 하위 오케스트레이터 타임아웃
```

### 4.3 자동 등록 메커니즘

```python
async def register_with_parent(config: OrchestratorConfig) -> None:
    """상위 오케스트레이터에 이 오케스트레이터를 에이전트로 등록"""
    payload = {
        "name": config.name,
        "url": config.public_url,
        "agent_type": "orchestrator",  # 핵심: 타입 명시
        "skills": config.skills.split(","),
    }
    # POST {parent_url}/agents/register
```

### 4.4 타임아웃 전략

| 호출 대상 | 기본 타임아웃 | 이유 |
|-----------|-------------|------|
| 일반 Agent | 120초 | 단일 Claude 호출 |
| Sub-Orchestrator | 600초 | 내부 토론 (N라운드 × M에이전트 × 120초) + 합성 |

계산 근거: 하위 오케스트레이터가 2라운드 × 2에이전트로 토론하면:
- 라운드 0: 2개 동시 호출 ≈ 120초
- 라운드 1: 2개 동시 호출 ≈ 120초
- 합성: 1회 ≈ 60초
- **총 ≈ 300초**, 여유분 포함 600초

---

## 5. 활용 시나리오

### 5.1 팀 간 크로스 리뷰

```
Meta-Orchestrator
├── Backend-Orchestrator (DB팀, API팀 에이전트)
├── Frontend-Orchestrator (Web팀, Mobile팀 에이전트)
└── DevOps-Orchestrator (Infra팀, SRE팀 에이전트)

주제: "시스템 마이그레이션 전략"
→ 각 팀이 자체 토론 → 팀 간 의견 교차 → 종합 보고서
```

### 5.2 지역 분산 구조

```
Global-Orchestrator (US)
├── Asia-Orchestrator (한국, 일본 에이전트)
├── Europe-Orchestrator (독일, 영국 에이전트)
└── Americas-Orchestrator (미국, 브라질 에이전트)
```

### 5.3 전문가 패널 + 종합 분석

```
Meta-Orchestrator
├── Legal-Orchestrator (법률 자문 에이전트들)
├── Tech-Orchestrator (기술 분석 에이전트들)
├── Business-Orchestrator (사업 분석 에이전트들)
└── 독립 에이전트 C (종합 코멘테이터)

→ 일반 에이전트와 오케스트레이터를 혼합 가능
```

---

## 6. 환경변수 레퍼런스

### Meta-Orchestrator (최상위)

| 변수 | 설명 | 예시 |
|------|------|------|
| `ORCHESTRATOR_PORT` | 서버 포트 | `9000` |
| `ORCHESTRATOR_NAME` | 식별 이름 | `Meta-Orchestrator` |
| `SUB_ORCHESTRATOR_TIMEOUT` | 하위 호출 타임아웃(초) | `600` |

### Sub-Orchestrator (하위)

| 변수 | 설명 | 예시 |
|------|------|------|
| `ORCHESTRATOR_PORT` | 서버 포트 | `8000` |
| `ORCHESTRATOR_NAME` | 식별 이름 | `Team-A-Orchestrator` |
| `PARENT_ORCHESTRATOR_URL` | 상위 URL | `http://meta:9000` |
| `ORCHESTRATOR_PUBLIC_URL` | 외부 접근 URL | `http://this:8000` |
| `ORCHESTRATOR_SKILLS` | 상위에 광고할 스킬 | `backend,database` |

---

## 7. 제약사항 및 주의점

### 7.1 지연시간 증폭
- 계층이 깊어질수록 응답 시간이 **곱셈적으로** 증가
- 3단계 이상은 실용적이지 않을 수 있음
- **권장**: 최대 2단계 (Meta → Sub → Agent)

### 7.2 순환 참조 방지
- 현재 순환 참조 감지 로직은 없음
- Orchestrator A가 B를 에이전트로, B가 A를 에이전트로 등록하면 무한 루프
- **운영 지침**: 명확한 상하 관계 설계 필요

### 7.3 장애 전파
- 하위 Orchestrator가 내부 토론 중 실패하면 상위에 에러 메시지 반환
- 상위는 이를 하나의 "의견"으로 처리 (graceful degradation)
- 나머지 에이전트/오케스트레이터의 의견으로 보고서 생성 가능

### 7.4 정보 압축
- 하위 토론의 전체 히스토리는 합성 보고서로 압축되어 상위로 전달
- 상위에서는 원본 토론 내용을 볼 수 없음 (의도된 설계: 팀 자율성)
- 필요 시 하위 보고서 파일을 직접 참조 가능

---

## 8. 향후 확장 방향

| 항목 | 설명 |
|------|------|
| **순환 참조 감지** | 등록 시 그래프 탐색으로 사이클 검출 |
| **계층 깊이 제한** | `max_depth` 설정으로 과도한 중첩 방지 |
| **하위 보고서 첨부** | 상위 보고서에 하위 원본 첨부 옵션 |
| **동적 타임아웃** | 하위 에이전트 수 × 라운드 수 기반 자동 계산 |
| **헬스체크 전파** | 하위 오케스트레이터의 에이전트 상태까지 재귀 확인 |
