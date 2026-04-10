#!/bin/bash
# Mac 에이전트 설치 자동화 스크립트
# Python 3.12 고정 + 환경 검증 + 자동 설치

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_DIR="$PROJECT_DIR/agent"
VENV_DIR="$PROJECT_DIR/.venv"
MIN_PYTHON="3.12"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
step() { echo -e "\n${CYAN}[$1]${NC} $2"; }

echo ""
echo "=========================================="
echo "A2A 에이전트 설치 (Python >= ${MIN_PYTHON})"
echo "=========================================="

# ── 1. 누락 항목 검사 ──
missing=()
python_cmd=""

# Homebrew
if [[ "$(uname)" == "Darwin" ]] && ! command -v brew &>/dev/null; then
    missing+=("Homebrew")
fi

# Python 정확한 버전
for cmd in python3 "python${MIN_PYTHON}" python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        if [ "$(printf '%s\n' "$MIN_PYTHON" "$ver" | sort -V | head -1)" = "$MIN_PYTHON" ]; then
            python_cmd="$cmd"
            break
        fi
    fi
done
[ -z "$python_cmd" ] && missing+=("Python >= ${MIN_PYTHON}")

command -v node &>/dev/null || missing+=("Node.js")
command -v claude &>/dev/null || missing+=("Claude Code CLI")
command -v cloudflared &>/dev/null || missing+=("cloudflared")

# ── 2. 현황 출력 ──
echo ""
[ -n "$python_cmd" ] && pass "Python: $($python_cmd --version)"
command -v node &>/dev/null && pass "Node.js: $(node -v)"
command -v claude &>/dev/null && pass "Claude Code CLI: 설치됨"
command -v cloudflared &>/dev/null && pass "cloudflared: $(cloudflared --version 2>&1 | head -1)"

# ── 3. 누락 시 Y/N 확인 ──
need_venv=false
if [ ! -d "$VENV_DIR" ] || ! "$VENV_DIR/bin/python3" -c "import sys" 2>/dev/null; then
    need_venv=true
fi

if [ ${#missing[@]} -gt 0 ] || [ "$need_venv" = true ]; then
    echo ""
    echo -e "${YELLOW}다음 항목이 설치되지 않았습니다:${NC}"
    for item in "${missing[@]}"; do
        echo -e "  ${RED}✗${NC} $item"
    done
    [ "$need_venv" = true ] && echo -e "  ${RED}✗${NC} Python 가상환경 (venv)"
    echo ""
    read -p "모두 자동 설치를 진행할까요? [Y/n]: " CONFIRM
    CONFIRM=${CONFIRM:-y}
    if [[ ! "$CONFIRM" =~ ^[Yy] ]]; then
        fail "설치를 취소했습니다."
        exit 1
    fi
fi

# ── 4. 자동 설치 ──

if [[ " ${missing[*]} " =~ "Homebrew" ]]; then
    step "설치" "Homebrew"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    [ -f /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
    pass "Homebrew 설치 완료"
fi

if [[ " ${missing[*]} " =~ "Python" ]]; then
    step "설치" "Python ${MIN_PYTHON}"
    if command -v brew &>/dev/null; then
        brew install "python@${MIN_PYTHON}"
        python_cmd="$(brew --prefix python@${MIN_PYTHON})/bin/python${MIN_PYTHON}"
        [ ! -f "$python_cmd" ] && python_cmd="python${MIN_PYTHON}"
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        if grep -qi ubuntu /etc/os-release 2>/dev/null; then
            sudo apt-get install -y software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
            sudo apt-get update -qq
        fi
        sudo apt-get install -y "python${MIN_PYTHON}" "python${MIN_PYTHON}-venv" "python${MIN_PYTHON}-dev" 2>/dev/null || {
            warn "apt 패키지 없음 → 소스 빌드"
            sudo apt-get install -y build-essential zlib1g-dev libncurses5-dev \
                libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev \
                libsqlite3-dev wget libbz2-dev
            curl -fsSL "https://www.python.org/ftp/python/${MIN_PYTHON}.0/Python-${MIN_PYTHON}.0.tgz" -o /tmp/python.tgz
            cd /tmp && tar xzf python.tgz && cd "Python-${MIN_PYTHON}.0"
            ./configure --enable-optimizations --prefix=/usr/local
            make -j"$(nproc)" && sudo make altinstall
            cd "$PROJECT_DIR" && rm -rf /tmp/python.tgz /tmp/Python-*
        }
        python_cmd="python${MIN_PYTHON}"
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y "python${MIN_PYTHON}" "python${MIN_PYTHON}-devel" 2>/dev/null || {
            sudo dnf install -y epel-release 2>/dev/null || true
            sudo dnf config-manager --set-enabled crb 2>/dev/null || \
                sudo dnf config-manager --set-enabled powertools 2>/dev/null || true
            sudo dnf install -y "python${MIN_PYTHON}" "python${MIN_PYTHON}-devel"
        }
        python_cmd="python${MIN_PYTHON}"
    elif command -v yum &>/dev/null; then
        sudo yum install -y epel-release 2>/dev/null || true
        sudo yum install -y "python${MIN_PYTHON}" "python${MIN_PYTHON}-devel" 2>/dev/null || {
            warn "yum에서 설치 실패 → 소스 빌드"
            sudo yum groupinstall -y "Development Tools"
            sudo yum install -y openssl-devel bzip2-devel libffi-devel zlib-devel
            curl -fsSL "https://www.python.org/ftp/python/${MIN_PYTHON}.0/Python-${MIN_PYTHON}.0.tgz" -o /tmp/python.tgz
            cd /tmp && tar xzf python.tgz && cd "Python-${MIN_PYTHON}.0"
            ./configure --enable-optimizations --prefix=/usr/local
            make -j"$(nproc)" && sudo make altinstall
            cd "$PROJECT_DIR" && rm -rf /tmp/python.tgz /tmp/Python-*
        }
        python_cmd="python${MIN_PYTHON}"
    else
        fail "지원하지 않는 패키지 관리자입니다. Python ${MIN_PYTHON}을 수동으로 설치해주세요."
        exit 1
    fi
    pass "Python 설치 완료: $($python_cmd --version)"
fi

if [[ " ${missing[*]} " =~ "Node.js" ]]; then
    step "설치" "Node.js"
    if command -v brew &>/dev/null; then
        brew install node
    elif command -v apt-get &>/dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        sudo apt-get install -y nodejs
    elif command -v dnf &>/dev/null; then
        curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
        sudo dnf install -y nodejs
    elif command -v yum &>/dev/null; then
        curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
        sudo yum install -y nodejs
    fi
    pass "Node.js: $(node -v)"
fi

if [[ " ${missing[*]} " =~ "Claude Code CLI" ]]; then
    step "설치" "Claude Code CLI"
    npm install -g @anthropic-ai/claude-code
    pass "Claude Code CLI 설치 완료"
fi

if [[ " ${missing[*]} " =~ "cloudflared" ]]; then
    step "설치" "cloudflared"
    if command -v brew &>/dev/null; then
        brew install cloudflared
    elif command -v apt-get &>/dev/null; then
        curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
        sudo dpkg -i /tmp/cloudflared.deb && rm -f /tmp/cloudflared.deb
    elif command -v dnf &>/dev/null || command -v yum &>/dev/null; then
        curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-x86_64.rpm -o /tmp/cloudflared.rpm
        sudo rpm -ivh /tmp/cloudflared.rpm 2>/dev/null || sudo rpm -Uvh /tmp/cloudflared.rpm
        rm -f /tmp/cloudflared.rpm
    fi
    pass "cloudflared 설치 완료"
fi

# ── 5. venv + 패키지 ──
step "설정" "Python ${MIN_PYTHON} 가상환경"

if [ "$need_venv" = true ]; then
    rm -rf "$VENV_DIR"
    "$python_cmd" -m venv "$VENV_DIR"
    pass "venv 생성: $("$VENV_DIR/bin/python3" --version)"
else
    venv_ver=$("$VENV_DIR/bin/python3" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    if [ "$(printf '%s\n' "$MIN_PYTHON" "$venv_ver" | sort -V | head -1)" != "$MIN_PYTHON" ]; then
        warn "venv Python 버전 불일치 ($venv_ver) → 재생성"
        rm -rf "$VENV_DIR"
        "$python_cmd" -m venv "$VENV_DIR"
        pass "venv 재생성: $("$VENV_DIR/bin/python3" --version)"
    else
        pass "venv: $("$VENV_DIR/bin/python3" --version)"
    fi
fi

if [ -f "$AGENT_DIR/requirements.txt" ]; then
    "$VENV_DIR/bin/pip" install -q -r "$AGENT_DIR/requirements.txt"
fi
pass "패키지 설치 완료"

if "$VENV_DIR/bin/python3" -c "from a2a.server.apps import A2AStarletteApplication" 2>/dev/null; then
    pass "a2a-sdk import 정상"
else
    fail "a2a-sdk import 실패"
    exit 1
fi

# ── 6. .env 설정 ──
step "설정" ".env 파일"
mkdir -p "$AGENT_DIR/data"

ENV_FILE="$AGENT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    pass ".env 이미 존재: $ENV_FILE"
else
    echo ""
    read -p "에이전트 이름 (예: 홍길동-agent): " AGENT_NAME
    AGENT_NAME=${AGENT_NAME:-"my-agent"}
    read -p "에이전트 설명: " AGENT_DESC
    AGENT_DESC=${AGENT_DESC:-"${AGENT_NAME}의 Claude 에이전트"}
    read -p "오케스트레이터 URL (예: http://35.224.189.143:8000): " ORCH_URL
    ORCH_URL=${ORCH_URL:-"http://localhost:8000"}
    read -p "포트 (기본: 8001): " AGENT_PORT
    AGENT_PORT=${AGENT_PORT:-8001}
    read -p "스킬셋 (쉼표 구분): " AGENT_SKILLS
    AGENT_SKILLS=${AGENT_SKILLS:-"general,analysis"}

    cat > "$ENV_FILE" << EOF
AGENT_HOST=0.0.0.0
AGENT_PORT=$AGENT_PORT
AGENT_NAME="$AGENT_NAME"
AGENT_DESCRIPTION="$AGENT_DESC"
ORCHESTRATOR_URL="$ORCH_URL"
AGENT_PUBLIC_URL=
DATA_DIR=./data
ALLOWED_TOOLS=Read,Glob,Grep
AGENT_SKILLS="$AGENT_SKILLS"
EOF
    pass ".env 생성: $ENV_FILE"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}설치 완료! (Python ${MIN_PYTHON})${NC}"
echo ""
echo "다음 단계:"
echo "  1. Claude Code 로그인: claude"
echo "  2. 참고 데이터: $AGENT_DIR/data/ 에 넣기"
echo "  3. 시작: cd $PROJECT_DIR/tunnel && bash start_agent_with_tunnel.sh"
echo "=========================================="
