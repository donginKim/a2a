# 세팅 가이드

## 1. GCP 오케스트레이터 설정

### 환경변수 (`orchestrator/.env`)

```env
ORCHESTRATOR_HOST=0.0.0.0
ORCHESTRATOR_PORT=8000
ORCHESTRATOR_NAME=A2A Orchestrator
DEBATE_ROUNDS=2          # 토론 라운드 수
OUTPUT_DIR=./reports     # 보고서 저장 디렉토리
AGENTS_FILE=./agents.json
```

### 에이전트 등록 파일 (`orchestrator/agents.json`)

에이전트가 자동 등록되지만, 수동으로도 관리할 수 있습니다:

```json
{
  "agents": [
    {
      "name": "홍길동-agent",
      "url": "https://xxxx.trycloudflare.com",
      "description": "홍길동의 에이전트"
    },
    {
      "name": "김철수-agent",
      "url": "https://yyyy.trycloudflare.com",
      "description": "김철수의 에이전트"
    }
  ]
}
```

### 오케스트레이터 시작

```bash
cd orchestrator
source ~/.venv/a2a/bin/activate
python server.py
```

---

## 2. Mac 에이전트 설정

### 환경변수 (`agent/.env`)

```env
AGENT_HOST=0.0.0.0
AGENT_PORT=8001

# 본인 이름으로 변경
AGENT_NAME=홍길동-agent
AGENT_DESCRIPTION=홍길동의 Claude 기반 A2A 에이전트

# GCP IP 주소로 변경
ORCHESTRATOR_URL=http://34.xx.xx.xx:8000

# 터널 시작 후 나온 URL 입력
AGENT_PUBLIC_URL=https://xxxx.trycloudflare.com

# 에이전트가 읽을 로컬 데이터 폴더
DATA_DIR=./data

# Claude에게 허용할 도구
ALLOWED_TOOLS=Read,Glob,Grep
```

### 로컬 데이터 준비

에이전트가 참고할 파일을 `agent/data/` 에 넣습니다:

```
agent/data/
├── report_2024.pdf       # 분석 자료
├── data.csv              # 데이터
├── notes.md              # 메모
└── ...
```

Claude는 토론 시 이 파일들을 읽어 의견을 구성합니다.

### 에이전트 시작 (터널 포함)

```bash
# 터널 + 에이전트 동시 시작 (권장)
cd tunnel
bash start_agent_with_tunnel.sh

# 또는 개별 실행
# 터미널 1: 터널
cloudflared tunnel --url http://localhost:8001

# 터미널 2: 에이전트
cd agent
source ../.venv/bin/activate
python server.py
```

---

## 3. 동료 에이전트 추가

동료가 동일한 `install_agent.sh` 를 실행하고:
- `ORCHESTRATOR_URL`을 GCP IP로 설정
- 각자 다른 `AGENT_NAME` 사용
- 각자의 Claude Code 구독 계정으로 로그인

에이전트가 시작되면 **자동으로 GCP 오케스트레이터에 등록**됩니다.

수동 등록이 필요하다면:

```bash
bash scripts/register_agent.sh 홍길동-agent https://xxxx.trycloudflare.com
```

---

## 4. 토론 시작

### API로 직접 호출

```bash
curl -X POST http://<GCP_IP>:8000/debate \
  -H "Content-Type: application/json" \
  -d '{"topic": "AI가 소프트웨어 개발에 미치는 영향"}'
```

### 등록된 에이전트 확인

```bash
curl http://<GCP_IP>:8000/agents
```

### 보고서 확인

GCP 서버의 `orchestrator/reports/` 폴더에 Markdown 보고서가 생성됩니다.

---

## 5. 포트 정리

| 서비스 | 포트 | 위치 |
|--------|------|------|
| 오케스트레이터 A2A | 8000 | GCP |
| 내 에이전트 | 8001 | 내 Mac (로컬) |
| 동료1 에이전트 | 8001 | 동료1 Mac (로컬) |
| Cloudflare tunnel | 자동 | 각 Mac |
