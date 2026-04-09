# 구현 가이드

## 한 줄 요약

Google A2A 프로토콜 기반으로 각 팀원의 Mac에서 실행되는 에이전트들이 Cloudflare Tunnel을 통해 GCP 오케스트레이터에 연결되어, 주어진 주제에 대해 다중 라운드 토론을 수행하고 최종 보고서를 자동 생성하는 멀티 에이전트 시스템.

## 설계 비유

이 시스템은 **원격 토론회**와 같습니다.

- **오케스트레이터** = 사회자 (GCP에 상주). 주제를 던지고, 패널들의 발언 순서를 조율하며, 마지막에 회의록을 작성합니다.
- **에이전트** = 각 토론 패널 (팀원의 Mac에서 실행). 자신만의 자료(로컬 `data/` 폴더)를 가지고 있고, 그 자료를 기반으로 의견을 제시합니다.
- **Cloudflare Tunnel** = 화상회의 링크. NAT 뒤에 있는 Mac을 외부에서 접근 가능하게 만들어주는 통로입니다.
- **A2A 프로토콜** = 토론 참가자 간의 대화 규칙(JSON-RPC 2.0). "발언 요청→응답" 형식이 표준화되어 있어 누구든 같은 방식으로 참여할 수 있습니다.

## 아키텍처 개요

```
                          ┌─────────────────────────────────────────┐
                          │          GCP Instance (:8000)            │
                          │  ┌───────────────────────────────────┐  │
                          │  │        Orchestrator Server         │  │
                          │  │  ┌─────────────┐ ┌─────────────┐  │  │
                          │  │  │  A2A Server  │ │  REST API   │  │  │
                          │  │  │  (JSON-RPC)  │ │ /debate     │  │  │
                          │  │  │              │ │ /agents     │  │  │
                          │  │  └──────┬───────┘ │ /query      │  │  │
                          │  │         │         │ /stream     │  │  │
                          │  │  ┌──────▼───────┐ │ /dashboard  │  │  │
                          │  │  │ Orchestrator │ └──────┬──────┘  │  │
                          │  │  │    Agent     │────────┘         │  │
                          │  │  │  (토론 로직)  │                  │  │
                          │  │  └──────┬───────┘                  │  │
                          │  │         │ Claude Agent SDK          │  │
                          │  │         ▼ (보고서 합성용)             │  │
                          │  │    Claude Code CLI                  │  │
                          │  └───────────────────────────────────┘  │
                          └────────────┬──────────────┬─────────────┘
                        A2A JSON-RPC   │              │   A2A JSON-RPC
                   ┌───────────────────┘              └──────────────────┐
                   │                                                     │
    ┌──────────────▼──────────────┐            ┌──────────────▼──────────────┐
    │     Mac A (팀원 A) :8001     │            │     Mac B (팀원 B) :8001     │
    │  ┌────────────────────────┐ │            │  ┌────────────────────────┐ │
    │  │    Agent Server        │ │            │  │    Agent Server        │ │
    │  │  ┌──────────────────┐  │ │            │  │  ┌──────────────────┐  │ │
    │  │  │  Claude Agent    │  │ │            │  │  │  Claude Agent    │  │ │
    │  │  │  (Read/Glob/Grep)│  │ │            │  │  │  (Read/Glob/Grep)│  │ │
    │  │  │       │          │  │ │            │  │  │       │          │  │ │
    │  │  │  ┌────▼────┐     │  │ │            │  │  │  ┌────▼────┐     │  │ │
    │  │  │  │ data/   │     │  │ │            │  │  │  │ data/   │     │  │ │
    │  │  │  │ (로컬자료)│     │  │ │            │  │  │  │ (로컬자료)│     │  │ │
    │  │  │  └─────────┘     │  │ │            │  │  │  └─────────┘     │  │ │
    │  │  └──────────────────┘  │ │            │  │  └──────────────────┘  │ │
    │  └────────────────────────┘ │            │  └────────────────────────┘ │
    │       │                     │            │       │                     │
    │  cloudflared tunnel ────────┤            │  cloudflared tunnel ────────┤
    │  https://xxx.trycloudflare  │            │  https://yyy.trycloudflare  │
    └─────────────────────────────┘            └─────────────────────────────┘
```

### 토론 흐름 (Sequence)

```
  Client          Orchestrator              Agent A              Agent B
    │                  │                       │                     │
    │  POST /debate    │                       │                     │
    │  {"topic":"..."}│                        │                     │
    │─────────────────▶│                       │                     │
    │                  │                       │                     │
    │                  │  ── 스킬 매칭 (Claude) ──                   │
    │                  │                       │                     │
    │                  │  [라운드 0: 초기 의견]  │                     │
    │                  │  A2A message/send ────▶│                     │
    │                  │  A2A message/send ─────────────────────────▶│
    │                  │◀──── 의견 A ──────────│                     │
    │                  │◀────────────────────── 의견 B ──────────────│
    │                  │                       │                     │
    │                  │  [라운드 1: 상대 의견 포함 재토론]             │
    │                  │  "B의 의견: ..." ─────▶│                     │
    │                  │  "A의 의견: ..." ──────────────────────────▶│
    │                  │◀──── 심화 의견 A ─────│                     │
    │                  │◀────────────────────── 심화 의견 B ─────────│
    │                  │                       │                     │
    │                  │  ── 보고서 합성 (Claude) ──                  │
    │                  │                       │                     │
    │◀─ 최종 보고서 ───│                       │                     │
    │                  │                       │                     │
```

---

## 핵심 컴포넌트

### 1. 오케스트레이터 (`orchestrator/`)

| 파일 | 역할 |
|------|------|
| `config.py` | 환경변수 로드, 에이전트 목록 관리 |
| `orchestrator_agent.py` | 토론 로직, 에이전트 호출, 보고서 생성 |
| `server.py` | A2A 서버 + REST API 엔드포인트 |
| `agents.json` | 등록된 에이전트 목록 |

**주요 흐름 (`orchestrator_agent.py`)**:

```python
async def run_debate(config, topic):
    # 1. 모든 에이전트에게 초기 의견 요청 (병렬)
    initial = await gather_opinions(agents, topic)

    # 2. N라운드 토론 (상대 의견 전달 → 심화 의견 요청)
    for round in range(debate_rounds):
        debate = await gather_opinions(agents, topic, context=prev_opinions)

    # 3. Claude로 전체 내용 합성 → 보고서 생성
    report = await synthesize_with_claude(history)
    return report
```

### 2. 에이전트 (`agent/`)

| 파일 | 역할 |
|------|------|
| `config.py` | 환경변수 로드 |
| `claude_agent.py` | Claude Agent SDK 연동 |
| `server.py` | A2A 서버, 오케스트레이터 자동 등록 |
| `data/` | 에이전트가 참고할 로컬 파일 |

**Claude Agent SDK 연동 (`claude_agent.py`)**:

```python
async def process_with_claude(prompt, config):
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=config.data_dir,      # 로컬 데이터 접근
            allowed_tools=["Read", "Glob", "Grep"],
            system_prompt=f"당신은 {config.name} 에이전트입니다...",
        ),
    ):
        if isinstance(message, ResultMessage):
            return message.result
```

---

## 단계별 워크스루

### Phase 1: 시스템 부트스트랩

```
1단계: 에이전트 시작 (각 Mac)
       agent/server.py → load_config() → .env 파일 읽기
       → ClaudeAgentExecutor 생성 → A2A 서버 빌드 → uvicorn 시작 (:8001)

2단계: Cloudflare 터널 생성
       tunnel/start_agent_with_tunnel.sh → cloudflared 실행
       → 임시 public URL 발급 (https://xxx.trycloudflare.com)
       → .env에 AGENT_PUBLIC_URL 자동 갱신

3단계: 오케스트레이터 자동 등록
       agent/server.py → register_with_orchestrator()
       → POST /agents/register {name, url, skills, data_paths}
       → 오케스트레이터가 agents.json에 저장
```

> **왜 이렇게?** → 각 팀원이 `./start_agent_with_tunnel.sh` 하나만 실행하면 터널 생성 + 서버 기동 + 오케스트레이터 등록이 전부 자동화됩니다.

### Phase 2: 토론 실행

```
4단계: 토론 요청 수신
       orchestrator/server.py → POST /debate {"topic": "..."}

5단계: 스킬 매칭 (선택적)
       orchestrator_agent.py → select_agents_for_topic()
       → Claude에게 "이 주제에 어떤 에이전트가 적합한가?" 질문
       → JSON 배열로 응답받아 에이전트 필터링

6단계: 라운드 0 — 초기 의견 수집
       orchestrator_agent.py → gather_opinions()
       → 모든 에이전트에 asyncio.gather()로 병렬 요청
       → 각 에이전트는 자신의 data/ 폴더를 탐색하여 근거 기반 의견 생성

7단계: 라운드 1~N — 토론
       다른 에이전트의 의견을 context로 포함하여 재질문
       "다른 참여자 의견: [A: ..., B: ...]를 참고하여 심화된 견해를 제시하세요"

8단계: 보고서 합성
       synthesize_with_claude() → 전체 토론 히스토리를 Claude에 전달
       → 핵심 요약 / 합의 사항 / 쟁점 / 결론 4개 섹션으로 구조화
       → reports/report_YYYYMMDD_HHMMSS.md로 저장
```

### Phase 3: 에이전트 내부 처리

```
9단계: A2A 메시지 수신
       agent/server.py → ClaudeAgentExecutor.execute()
       → 텍스트 추출 → process_with_claude() 호출

10단계: Claude Agent SDK 실행
        agent/claude_agent.py → process_with_claude()
        → 허용 도구: Read, Glob, Grep만 (읽기 전용)
        → 작업 디렉토리: data/ 폴더로 제한 (샌드박스)
        → 시스템 프롬프트로 data/ 외부 접근 차단
```

> **왜 읽기 전용?** → 팀원의 로컬 파일 보호 + 데이터 기반 답변 강제

---

## A2A 프로토콜 핵심

### Agent Card (자동 생성)

`GET /.well-known/agent.json` 에서 확인:

```json
{
  "name": "홍길동-agent",
  "description": "...",
  "url": "https://xxxx.trycloudflare.com/",
  "version": "1.0.0",
  "capabilities": { "streaming": true },
  "skills": [
    {
      "id": "analyze",
      "name": "데이터 분석 및 의견 제시",
      "description": "..."
    }
  ]
}
```

### Task 전송 (JSON-RPC 2.0)

오케스트레이터 → 에이전트:

```json
{
  "jsonrpc": "2.0",
  "method": "message/send",
  "id": "uuid",
  "params": {
    "message": {
      "role": "user",
      "parts": [{ "text": "AI 윤리에 대한 의견을 제시해주세요" }]
    }
  }
}
```

---

## 커스터마이징

### 에이전트에게 특정 데이터 제공

`agent/data/` 폴더에 파일 추가:

```bash
# 예: CSV 데이터
cp ~/Downloads/sales_data.csv agent/data/

# 예: 보고서
cp ~/Documents/annual_report.pdf agent/data/

# 예: 노트
echo "우리 팀 전략: ..." > agent/data/strategy.md
```

### 토론 라운드 조정

`orchestrator/.env`:
```env
DEBATE_ROUNDS=3  # 더 깊은 토론
```

### 허용 도구 확장

`agent/.env`:
```env
# 코드 실행도 허용
ALLOWED_TOOLS=Read,Glob,Grep,Bash,Write
```

---

## 문제 해결

### 에이전트가 오케스트레이터에 등록 안 됨

```bash
# 수동 등록
bash scripts/register_agent.sh <이름> <tunnel_URL>

# 또는 오케스트레이터 API로 직접
curl -X POST http://<GCP_IP>:8000/agents/register \
  -H "Content-Type: application/json" \
  -d '{"name":"홍길동-agent","url":"https://xxxx.trycloudflare.com"}'
```

### Claude Code 로그인 오류

```bash
# 로그인 상태 확인
claude --version

# 재로그인
claude logout
claude
```

### tunnel URL이 바뀜

Cloudflare free tunnel은 재시작할 때마다 URL이 바뀝니다.
`start_agent_with_tunnel.sh` 는 자동으로 `.env`를 업데이트하고 오케스트레이터에 재등록합니다.

---

## 설계 핵심 포인트

### 핵심 원칙

- **데이터 주권**: 각 에이전트의 자료(`data/`)는 절대 외부로 복사되지 않음. Claude가 로컬에서 읽고 "의견"만 전송
- **읽기 전용 샌드박스**: 에이전트는 `Read`, `Glob`, `Grep`만 사용 가능 — 파일 수정/삭제 불가
- **NAT 우회**: Cloudflare Tunnel로 포트포워딩 없이 내부 Mac을 외부에 노출
- **자동 등록**: 에이전트 시작 시 lifespan hook으로 오케스트레이터에 자동 등록

### 수정 시 주의할 점

- `agents.json`은 런타임에만 사용되며 재시작 시 초기화됨 — 영속 저장이 필요하면 DB 도입 필요
- Cloudflare 무료 티어는 재시작마다 URL이 변경됨 — 에이전트 재시작 시 반드시 재등록 필요
- `InMemoryTaskStore`를 사용하므로 서버 재시작 시 진행 중인 Task가 소실됨
- `call_agent`의 응답 파싱(`orchestrator_agent.py`)은 A2A SDK 버전에 따라 구조가 달라질 수 있어 방어적으로 작성되어 있음

### REST API 전체 목록

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/.well-known/agent.json` | GET | A2A Agent Card (자동 생성) |
| `/agents/register` | POST | 에이전트 등록/업데이트 |
| `/agents` | GET | 등록된 에이전트 목록 |
| `/agents/{name}` | DELETE | 에이전트 삭제 |
| `/agents/health` | GET | 에이전트 연결 상태 확인 |
| `/debate` | POST | 토론 시작 (동기) |
| `/stream/debate` | GET (SSE) | 토론 시작 (스트리밍) |
| `/query` | POST | 스킬 기반 단일 질문 |
| `/reports` | GET | 생성된 보고서 목록 |
| `/dashboard` | GET | 웹 대시보드 |

---

## 확장 로드맵

향후 세 가지 방향으로 시스템을 확장할 예정입니다. 세 기능은 서로 데이터를 주고받는 **선순환** 구조를 형성합니다.

```
  ┌─────────────────────────────────────────────────────────────┐
  │                    전체 확장 아키텍처                          │
  │                                                             │
  │   토론/질문 ──저장──▶ ① Knowledge Base ──조회──▶ 토론 context │
  │       │                    │                                │
  │       │              활동 이력 제공                            │
  │       │                    │                                │
  │       │                    ▼                                │
  │       │            ③ Skill Analyzer                         │
  │       │                    │                                │
  │       │              스킬 업데이트                             │
  │       │                    │                                │
  │       │                    ▼                                │
  │       └──▶ ② Stable Registry ◀── 더 정확한 스킬 매칭          │
  │              (영속 저장, heartbeat)                           │
  └─────────────────────────────────────────────────────────────┘

  순환: 토론 → 지식 축적 → 스킬 분석 → 더 나은 에이전트 매칭 → 더 좋은 토론
```

### 확장 1: 지식 저장소 (Knowledge Base)

토론 보고서와 질문 답변 리포트를 축적하여 거대한 지식 창고로 활용합니다.

**현재 문제**: 보고서가 `reports/` 폴더에 마크다운 파일로만 저장됨. 검색 불가, 관계 파악 불가.

**설계 방향**:

```
                    ┌──────────────────────────────────┐
                    │         Knowledge Base            │
                    │  ┌────────────┐ ┌──────────────┐ │
                    │  │ Vector DB  │ │ Document DB  │ │
                    │  │ (ChromaDB/ │ │ (SQLite/     │ │
                    │  │  Qdrant)   │ │  PostgreSQL) │ │
                    │  └─────┬──────┘ └──────┬───────┘ │
                    │        │               │         │
                    │  ┌─────▼───────────────▼───────┐ │
                    │  │    Knowledge Manager API     │ │
                    │  │  - 저장 (토론/질문 결과)       │ │
                    │  │  - 검색 (시맨틱 + 키워드)      │ │
                    │  │  - 연관 문서 추천              │ │
                    │  └─────────────┬───────────────┘ │
                    └───────────────│───────────────────┘
                                   │
          ┌────────────────────────┼─────────────────────────┐
          │                        │                         │
   ┌──────▼──────┐         ┌──────▼──────┐          ┌───────▼──────┐
   │ 토론 시 자동  │         │ 질문 시 과거 │          │  대시보드에서  │
   │ 결과 축적     │         │ 지식 참조    │          │  지식 검색/탐색│
   └─────────────┘         └─────────────┘          └──────────────┘
```

**핵심 변경점**:

1. **저장**: `orchestrator_agent.py`의 보고서 저장 시점에 Knowledge Base에도 저장

```python
# 현재: 파일로만 저장
with open(report_path, "w") as f:
    f.write(report)

# 확장: Knowledge Base에도 저장
await knowledge_base.store({
    "type": "debate" | "query",
    "topic": topic,
    "agents": [agent names],
    "content": report,
    "opinions": history,        # 개별 의견도 보존
    "tags": auto_extract_tags(report),
    "created_at": datetime.now(),
})
```

2. **검색**: 토론 시작 전에 과거 지식을 context로 주입

```python
# run_debate() 시작 부분에 추가
related_knowledge = await knowledge_base.search(topic, top_k=3)
if related_knowledge:
    context = "과거 관련 토론/분석 결과:\n" + format(related_knowledge)
    # 이 context를 초기 의견 수집 시 함께 전달
```

3. **데이터 모델**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `id` | UUID | 고유 식별자 |
| `type` | enum | `"debate"` or `"query"` |
| `topic` | string | 원본 주제 |
| `content` | text | 최종 보고서 본문 |
| `agents` | list | 참여 에이전트 목록 |
| `tags` | list | 자동 추출 태그 |
| `embedding` | vector | 벡터 임베딩 (시맨틱 검색용) |
| `created_at` | datetime | 생성 시각 |
| `references` | list | 관련 문서 ID 목록 |

### 확장 2: 안정성 강화

**현재 취약점과 해결 방안**:

| 현재 문제 | 해결 방안 |
|-----------|-----------|
| `InMemoryTaskStore` (재시작 시 Task 소실) | SQLite/Redis 기반 TaskStore (영속 저장) |
| `agents.json` 런타임만 유지 (재시작 시 초기화) | DB 기반 에이전트 레지스트리 + heartbeat 체크 |
| Cloudflare 무료 URL 변경 (재시작마다 바뀜) | 고정 터널 이름 사용 (유료) 또는 자동 재등록 강화 |
| 에이전트 응답 타임아웃 120초 고정 | 적응형 타임아웃 + 재시도 로직 + circuit breaker |
| 에러 시 전체 토론 실패 | 부분 실패 허용 (일부 에이전트 오류 시 나머지로 진행) |

**에이전트 헬스체크 강화**:

```python
# 현재: 수동 GET /agents/health
# 개선: 주기적 자동 헬스체크 + 상태 관리

class AgentRegistry:
    async def heartbeat_loop(self, interval=60):
        while True:
            for agent in self.agents:
                ok = await self.ping(agent)
                agent.status = "online" if ok else "offline"
                agent.last_seen = datetime.now()
            await asyncio.sleep(interval)

    async def get_available_agents(self):
        """온라인 에이전트만 반환"""
        return [a for a in self.agents if a.status == "online"]
```

### 확장 3: 자동 스킬 재정의

사용자의 작업물과 질문/답변 내용을 분석하여 에이전트의 스킬을 자동으로 재정의합니다.

**개념**:

```
  에이전트의 활동 이력                    스킬 프로파일 자동 생성
  ────────────────                     ─────────────────────

  질문: "K8s 배포 전략?"     ─┐
  질문: "Docker 최적화?"      │        ┌─────────────────────────┐
  토론: "CI/CD 파이프라인"    ├──분석──▶│ skills: ["devops",       │
  답변: 인프라 관련 인사이트   │        │   "kubernetes", "docker",│
  data/: terraform 파일들    ─┘        │   "infrastructure"]      │
                                      │ expertise_level: "senior"│
                                      └─────────────────────────┘
```

**동작 흐름**:

```
  매 N회 토론/질문 완료 후 (또는 주기적)
          │
          ▼
  ┌─────────────────────┐
  │ 에이전트별 활동 로그   │
  │ 수집 (KB에서 조회)    │
  └─────────┬───────────┘
            ▼
  ┌─────────────────────┐
  │ Claude에 분석 요청    │
  │                     │
  │ "dongone-agent가     │
  │  참여한 토론 10건,    │
  │  답변 15건을 분석하여  │
  │  스킬을 재정의하세요"  │
  └─────────┬───────────┘
            ▼
  ┌─────────────────────┐     ┌──────────────────────┐
  │ 결과 예시:           │     │ 오케스트레이터 반영     │
  │ {                   │────▶│                      │
  │   "primary": [      │     │ select_agents_for_   │
  │     "agent-infra",  │     │ topic() 에서 더       │
  │     "devops"        │     │ 정확한 매칭 가능       │
  │   ],                │     └──────────────────────┘
  │   "secondary": [    │
  │     "backend",      │
  │     "security"      │
  │   ],                │
  │   "confidence": 0.85│
  │ }                   │
  └─────────────────────┘
```

**Skill Analyzer 구조**:

1. **데이터 수집** — 에이전트가 참여한 토론 주제 목록, 받은 질문과 답변, `data/` 폴더의 파일 구조, 답변 품질 피드백
2. **Claude 분석** — 활동 이력을 Claude에 전달하여 전문 분야와 스킬을 JSON으로 정의
3. **스킬 업데이트** — AgentRegistry의 skills 필드 자동 갱신

### 구현 우선순위

KB가 중심 허브 역할을 하므로, 구현 순서는 다음과 같습니다:

```
  1순위: Knowledge Base    → 데이터 축적 인프라 확보
  2순위: 안정성 강화         → 영속 저장소, heartbeat, 부분 실패 허용
  3순위: 자동 스킬 재정의    → KB에 축적된 활동 이력 기반 분석
```
