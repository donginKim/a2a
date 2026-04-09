#!/bin/bash
# Mac 에이전트 설치 자동화 스크립트
# 에이전트 환경을 완전히 설정합니다

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_DIR="$PROJECT_DIR/agent"

echo "=========================================="
echo "A2A 에이전트 Mac 설치 스크립트"
echo "=========================================="

# 1. Homebrew 확인
echo "[1/6] Homebrew 확인..."
if ! command -v brew &>/dev/null; then
    echo "Homebrew 설치 중..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
echo "Homebrew: $(brew --version | head -1)"

# 2. Node.js 설치 (Claude Code CLI 요구사항)
echo "[2/6] Node.js 확인..."
if ! command -v node &>/dev/null; then
    brew install node
fi
echo "Node.js: $(node -v)"

# 3. Claude Code CLI 설치
echo "[3/6] Claude Code CLI 설치..."
if ! command -v claude &>/dev/null; then
    npm install -g @anthropic-ai/claude-code
fi
echo "Claude Code: $(claude --version 2>/dev/null || echo '설치됨')"

# 4. Cloudflare tunnel 설치
echo "[4/6] cloudflared 설치..."
if ! command -v cloudflared &>/dev/null; then
    brew install cloudflared
fi
echo "cloudflared: $(cloudflared --version)"

# 5. Python 가상환경 설정
echo "[5/6] Python 가상환경 설정..."
VENV_DIR="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install -q -r "$AGENT_DIR/requirements.txt"
echo "Python 패키지 설치 완료"

# 6. .env 파일 생성
echo "[6/6] 환경변수 파일 설정..."
ENV_FILE="$AGENT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo ""
    echo "--- 에이전트 정보 입력 ---"
    echo ""

    read -p "에이전트 이름 (예: 홍길동-agent): " AGENT_NAME
    AGENT_NAME=${AGENT_NAME:-"my-agent"}

    read -p "에이전트 설명 (예: 데이터 분석 전문 에이전트): " AGENT_DESC
    AGENT_DESC=${AGENT_DESC:-"${AGENT_NAME}의 Claude 기반 A2A 에이전트"}

    read -p "GCP 오케스트레이터 URL (예: http://35.224.189.143:8000): " ORCH_URL
    ORCH_URL=${ORCH_URL:-"http://localhost:8000"}

    read -p "에이전트 포트 (기본: 8001): " AGENT_PORT
    AGENT_PORT=${AGENT_PORT:-8001}

    echo ""
    echo "--- 스킬 & 데이터 설정 ---"
    echo ""

    read -p "스킬셋 (쉼표 구분, 예: analysis,coding,finance): " AGENT_SKILLS
    AGENT_SKILLS=${AGENT_SKILLS:-"general,analysis"}

    read -p "참고할 데이터 경로 (쉼표 구분, 기본: agent/data): " AGENT_DATA_PATHS
    AGENT_DATA_PATHS=${AGENT_DATA_PATHS:-"$AGENT_DIR/data"}

    read -p "MCP 서버 (쉼표 구분, 없으면 Enter): " AGENT_MCP_SERVERS

    cat > "$ENV_FILE" << EOF
AGENT_HOST=0.0.0.0
AGENT_PORT=$AGENT_PORT
AGENT_NAME=$AGENT_NAME
AGENT_DESCRIPTION="$AGENT_DESC"
ORCHESTRATOR_URL=$ORCH_URL
AGENT_PUBLIC_URL=
DATA_DIR=$AGENT_DIR/data
ALLOWED_TOOLS=Read,Glob,Grep

# 스킬셋
AGENT_SKILLS=$AGENT_SKILLS

# 참고 데이터 경로
AGENT_DATA_PATHS=$AGENT_DATA_PATHS

# MCP 서버
AGENT_MCP_SERVERS=$AGENT_MCP_SERVERS
EOF
    echo ".env 파일 생성: $ENV_FILE"
else
    echo ".env 파일 이미 존재 (수정하려면 직접 편집): $ENV_FILE"
fi

# data 디렉토리 생성
mkdir -p "$AGENT_DIR/data"
echo "데이터 디렉토리 생성: $AGENT_DIR/data"

echo ""
echo "=========================================="
echo "설치 완료!"
echo ""
echo "다음 단계:"
echo "  1. Claude Code 로그인: claude"
echo "  2. 참고할 데이터 파일을 $AGENT_DIR/data/ 에 넣기"
echo "  3. 에이전트 + 터널 시작:"
echo "     cd $PROJECT_DIR/tunnel"
echo "     bash start_agent_with_tunnel.sh"
echo ""
echo "대시보드 확인: http://<GCP_IP>:8000/dashboard"
echo "=========================================="
