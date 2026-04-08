#!/bin/bash
# GCP 인스턴스 설치 자동화 스크립트
# 오케스트레이터 환경을 완전히 설정합니다

set -e

PROJECT_DIR="$HOME/a2a"
REPO_URL=${REPO_URL:-""}  # git repo가 있다면 설정

echo "=========================================="
echo "A2A 오케스트레이터 GCP 설치 스크립트"
echo "=========================================="

# 1. 시스템 패키지 업데이트
echo "[1/7] 시스템 패키지 업데이트..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv nodejs npm curl git

# 2. Node.js 최신 LTS 설치 (Claude Code CLI 요구사항)
echo "[2/7] Node.js LTS 설치..."
if ! node -v | grep -q "v2"; then
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi
echo "Node.js: $(node -v)"
echo "npm: $(npm -v)"

# 3. Claude Code CLI 설치
echo "[3/7] Claude Code CLI 설치..."
sudo npm install -g @anthropic-ai/claude-code
echo "Claude Code: $(claude --version 2>/dev/null || echo '설치됨 - 로그인 필요')"

# 4. 프로젝트 디렉토리 설정
echo "[4/7] 프로젝트 디렉토리 설정..."
mkdir -p "$PROJECT_DIR"

# 5. Python 가상환경 생성 및 패키지 설치
echo "[5/7] Python 가상환경 설정..."
if [ ! -d "$PROJECT_DIR/venv" ]; then
    python3 -m venv "$PROJECT_DIR/venv"
fi
source "$PROJECT_DIR/venv/bin/activate"

# orchestrator requirements 설치
if [ -f "$(dirname "$0")/../orchestrator/requirements.txt" ]; then
    pip install -q -r "$(dirname "$0")/../orchestrator/requirements.txt"
else
    pip install -q a2a-sdk claude-agent-sdk uvicorn httpx starlette python-dotenv
fi
echo "Python 패키지 설치 완료"

# 6. 환경변수 파일 생성
echo "[6/7] 환경변수 파일 생성..."
ENV_FILE="$PROJECT_DIR/orchestrator/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'EOF'
ORCHESTRATOR_HOST=0.0.0.0
ORCHESTRATOR_PORT=8000
ORCHESTRATOR_NAME=A2A Orchestrator
DEBATE_ROUNDS=2
OUTPUT_DIR=./reports
AGENTS_FILE=./agents.json
EOF
    echo ".env 파일 생성: $ENV_FILE"
else
    echo ".env 파일 이미 존재: $ENV_FILE"
fi

# 7. systemd 서비스 등록 (선택)
echo "[7/7] systemd 서비스 설정..."
SERVICE_FILE="/etc/systemd/system/a2a-orchestrator.service"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=A2A Orchestrator Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$SCRIPT_DIR/orchestrator
Environment="PATH=$PROJECT_DIR/venv/bin:/usr/bin:/bin"
EnvironmentFile=$SCRIPT_DIR/orchestrator/.env
ExecStart=$PROJECT_DIR/venv/bin/python server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable a2a-orchestrator
echo "systemd 서비스 등록 완료"

echo ""
echo "=========================================="
echo "설치 완료!"
echo ""
echo "다음 단계:"
echo "1. Claude Code 로그인: claude"
echo "2. 서비스 시작: sudo systemctl start a2a-orchestrator"
echo "3. 로그 확인: sudo journalctl -u a2a-orchestrator -f"
echo "4. 상태 확인: sudo systemctl status a2a-orchestrator"
echo "=========================================="
