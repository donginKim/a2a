# 구현 가이드

## 아키텍처 개요

```
[내 Mac]                          [GCP 인스턴스]                [동료1 Mac]
  └─ agent/server.py               └─ orchestrator/server.py      └─ agent/server.py
     (포트 8001)                       (포트 8000)                    (포트 8001)
     Claude Agent SDK                  Claude Agent SDK               Claude Agent SDK
     (구독 계정)                        (구독 계정)                     (구독 계정)
     │                                 │                              │
     └── cloudflared ──────────────────┤◄─────────────────────────── cloudflared
         https://aaa.trycloudflare.com │           https://bbb.trycloudflare.com
                                       │
                                  A2A 프로토콜 (JSON-RPC 2.0 / HTTP)
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

## 통신 흐름

### 에이전트 등록

```
에이전트 시작
    │
    ▼
POST /agents/register → 오케스트레이터
    │  { name, url, description }
    ▼
agents.json에 저장
```

### 토론 요청

```
클라이언트
    │ POST /debate { "topic": "..." }
    ▼
오케스트레이터
    ├── A2A Task → 에이전트1 (병렬)
    ├── A2A Task → 에이전트2 (병렬)
    └── A2A Task → 에이전트N (병렬)
         │
         ▼ (각 에이전트)
    Claude Agent SDK
         │ data/ 파일 참조
         ▼
    응답 반환
         │
         ▼
오케스트레이터 (결과 취합)
    │
    ▼ (N 라운드 반복)
Claude Agent SDK (보고서 합성)
    │
    ▼
reports/report_YYYYMMDD_HHMMSS.md 저장
```

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
