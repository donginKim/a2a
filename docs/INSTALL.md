# 설치 가이드

## 사전 요구사항

| 항목 | 버전 | 필요 위치 |
|------|------|-----------|
| Python | 3.11 이상 | GCP + 각 Mac |
| Node.js | 18 LTS 이상 | GCP + 각 Mac |
| Claude Code CLI | 최신 | GCP + 각 Mac |
| cloudflared | 최신 | 각 Mac |
| GCP 인스턴스 | e2-medium 이상 | GCP |

---

## GCP 오케스트레이터 설치

### 자동 설치 (권장)

GCP 인스턴스에 SSH 접속 후:

```bash
# 프로젝트 파일 복사 후
cd /path/to/a2a
bash scripts/install_gcp.sh
```

### 수동 설치

```bash
# 1. 시스템 패키지
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv nodejs npm

# 2. Claude Code CLI
sudo npm install -g @anthropic-ai/claude-code

# 3. Python 가상환경
python3 -m venv ~/.venv/a2a
source ~/.venv/a2a/bin/activate
pip install -r orchestrator/requirements.txt

# 4. Claude Code 로그인 (구독 계정)
claude

# 5. 오케스트레이터 시작
cd orchestrator
python server.py
```

---

## Mac 에이전트 설치

### 자동 설치 (권장)

```bash
bash scripts/install_agent.sh
```

스크립트 실행 중 다음을 입력합니다:
- 에이전트 이름 (예: `홍길동-agent`)
- GCP 오케스트레이터 URL (예: `http://34.xx.xx.xx:8000`)
- 에이전트 포트 (기본: `8001`)

### 수동 설치

```bash
# 1. Homebrew (없다면)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 2. 의존성
brew install node cloudflared
npm install -g @anthropic-ai/claude-code

# 3. Python 가상환경
python3 -m venv .venv
source .venv/bin/activate
pip install -r agent/requirements.txt

# 4. Claude Code 로그인 (각자의 구독 계정)
claude

# 5. .env 파일 설정
cp agent/.env.example agent/.env
# .env 파일 편집
```

---

## 패키지 버전 확인

```bash
# Python 패키지
pip show a2a-sdk claude-agent-sdk

# Node
node -v && npm -v

# Claude Code
claude --version

# cloudflared
cloudflared --version
```

---

## 방화벽 설정 (GCP)

GCP 콘솔 → VPC 네트워크 → 방화벽 규칙에서:

| 규칙 이름 | 포트 | 설명 |
|-----------|------|------|
| allow-a2a-orchestrator | TCP 8000 | 오케스트레이터 A2A |

```bash
# 또는 gcloud CLI
gcloud compute firewall-rules create allow-a2a \
    --allow tcp:8000 \
    --target-tags a2a-server \
    --description "A2A Orchestrator"
```
