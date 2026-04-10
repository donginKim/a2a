#!/bin/bash
# GCP 인스턴스 설치 자동화 스크립트
# 오케스트레이터 환경을 완전히 설정합니다
# 지원: Ubuntu/Debian (apt), RHEL/CentOS/Amazon Linux (dnf/yum)

set -e

PROJECT_DIR="$HOME/a2a"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REQUIRED_PYTHON="3.12"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }

echo "=========================================="
echo "A2A 오케스트레이터 GCP 설치 (Python ${REQUIRED_PYTHON})"
echo "=========================================="

# ── 패키지 관리자 감지 ──
PKG=""
if command -v apt-get &>/dev/null; then
    PKG="apt"
elif command -v dnf &>/dev/null; then
    PKG="dnf"
elif command -v yum &>/dev/null; then
    PKG="yum"
else
    fail "지원하지 않는 패키지 관리자입니다 (apt, dnf, yum 중 하나 필요)"
    exit 1
fi
pass "패키지 관리자: $PKG"

# ── 1. 시스템 패키지 ──
echo ""
echo "[1/7] 시스템 패키지 업데이트..."
if [ "$PKG" = "apt" ]; then
    sudo apt-get update -qq
    sudo apt-get install -y curl git
elif [ "$PKG" = "dnf" ]; then
    sudo dnf install -y curl git
elif [ "$PKG" = "yum" ]; then
    sudo yum install -y curl git
fi
pass "시스템 패키지 완료"

# ── 2. Python 고정 버전 ──
echo ""
echo "[2/7] Python ${REQUIRED_PYTHON} 설치..."
python_cmd=""
for cmd in "python${REQUIRED_PYTHON}" python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        if [ "$ver" = "$REQUIRED_PYTHON" ]; then
            python_cmd="$cmd"
            break
        fi
    fi
done

if [ -n "$python_cmd" ]; then
    pass "이미 설치됨: $($python_cmd --version)"
else
    if [ "$PKG" = "apt" ]; then
        if grep -qi ubuntu /etc/os-release 2>/dev/null; then
            sudo apt-get install -y software-properties-common
            sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
            sudo apt-get update -qq
        fi
        sudo apt-get install -y "python${REQUIRED_PYTHON}" "python${REQUIRED_PYTHON}-venv" "python${REQUIRED_PYTHON}-dev" 2>/dev/null || {
            warn "apt 패키지 없음 → 소스 빌드"
            sudo apt-get install -y build-essential zlib1g-dev libncurses5-dev \
                libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev \
                libsqlite3-dev wget libbz2-dev
            curl -fsSL "https://www.python.org/ftp/python/${REQUIRED_PYTHON}.0/Python-${REQUIRED_PYTHON}.0.tgz" -o /tmp/python.tgz
            cd /tmp && tar xzf python.tgz && cd "Python-${REQUIRED_PYTHON}.0"
            ./configure --enable-optimizations --prefix=/usr/local
            make -j"$(nproc)" && sudo make altinstall
            cd ~ && rm -rf /tmp/python.tgz /tmp/Python-*
        }
    elif [ "$PKG" = "dnf" ]; then
        sudo dnf install -y "python${REQUIRED_PYTHON}" "python${REQUIRED_PYTHON}-devel" 2>/dev/null || {
            sudo dnf install -y epel-release 2>/dev/null || true
            sudo dnf config-manager --set-enabled crb 2>/dev/null || \
                sudo dnf config-manager --set-enabled powertools 2>/dev/null || true
            sudo dnf install -y "python${REQUIRED_PYTHON}" "python${REQUIRED_PYTHON}-devel"
        }
    elif [ "$PKG" = "yum" ]; then
        sudo yum install -y epel-release 2>/dev/null || true
        sudo yum install -y "python${REQUIRED_PYTHON}" "python${REQUIRED_PYTHON}-devel" 2>/dev/null || {
            warn "패키지 없음 → 소스 빌드"
            sudo yum groupinstall -y "Development Tools"
            sudo yum install -y openssl-devel bzip2-devel libffi-devel zlib-devel
            curl -fsSL "https://www.python.org/ftp/python/${REQUIRED_PYTHON}.0/Python-${REQUIRED_PYTHON}.0.tgz" -o /tmp/python.tgz
            cd /tmp && tar xzf python.tgz && cd "Python-${REQUIRED_PYTHON}.0"
            ./configure --enable-optimizations --prefix=/usr/local
            make -j"$(nproc)" && sudo make altinstall
            cd ~ && rm -rf /tmp/python.tgz /tmp/Python-*
        }
    fi
    python_cmd="python${REQUIRED_PYTHON}"
    pass "Python 설치 완료: $($python_cmd --version)"
fi

# ── 3. Node.js LTS ──
echo ""
echo "[3/7] Node.js 설치..."
if command -v node &>/dev/null; then
    pass "이미 설치됨: $(node -v)"
else
    if [ "$PKG" = "apt" ]; then
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        sudo apt-get install -y nodejs
    else
        curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
        sudo $PKG install -y nodejs
    fi
    pass "Node.js: $(node -v), npm: $(npm -v)"
fi

# ── 4. Claude Code CLI ──
echo ""
echo "[4/7] Claude Code CLI 설치..."
if command -v claude &>/dev/null; then
    pass "이미 설치됨"
else
    sudo npm install -g @anthropic-ai/claude-code
    pass "Claude Code CLI 설치 완료"
fi

# ── 5. Python venv + 패키지 ──
echo ""
echo "[5/7] Python 가상환경 설정..."
mkdir -p "$PROJECT_DIR"
VENV_DIR="$PROJECT_DIR/.venv"

need_venv=false
if [ ! -d "$VENV_DIR" ] || ! "$VENV_DIR/bin/python3" -c "import sys" 2>/dev/null; then
    need_venv=true
else
    venv_ver=$("$VENV_DIR/bin/python3" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    [ "$venv_ver" != "$REQUIRED_PYTHON" ] && need_venv=true
fi

if [ "$need_venv" = true ]; then
    rm -rf "$VENV_DIR"
    "$python_cmd" -m venv "$VENV_DIR"
fi
pass "venv: $("$VENV_DIR/bin/python3" --version)"

source "$VENV_DIR/bin/activate"
if [ -f "$SCRIPT_DIR/../orchestrator/requirements.txt" ]; then
    pip install -q -r "$SCRIPT_DIR/../orchestrator/requirements.txt"
else
    pip install -q a2a-sdk claude-agent-sdk uvicorn httpx starlette python-dotenv
fi
pass "패키지 설치 완료"

# ── 6. 환경변수 파일 ──
echo ""
echo "[6/7] 환경변수 파일..."
ORCH_DIR="$SCRIPT_DIR/../orchestrator"
ENV_FILE="$ORCH_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'EOF'
ORCHESTRATOR_HOST=0.0.0.0
ORCHESTRATOR_PORT=8000
ORCHESTRATOR_NAME=A2A Orchestrator
DEBATE_ROUNDS=2
OUTPUT_DIR=./reports
AGENTS_FILE=./agents.json
EOF
    pass ".env 파일 생성: $ENV_FILE"
else
    pass ".env 이미 존재: $ENV_FILE"
fi

# ── 7. systemd 서비스 ──
echo ""
echo "[7/7] systemd 서비스 설정..."
SERVICE_FILE="/etc/systemd/system/a2a-orchestrator.service"
FULL_ORCH_DIR="$(cd "$ORCH_DIR" && pwd)"

sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=A2A Orchestrator Service
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$FULL_ORCH_DIR
Environment="PATH=$VENV_DIR/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=$FULL_ORCH_DIR/.env
ExecStart=$VENV_DIR/bin/python server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable a2a-orchestrator
pass "systemd 서비스 등록 완료"

echo ""
echo "=========================================="
echo -e "${GREEN}설치 완료! (Python ${REQUIRED_PYTHON})${NC}"
echo ""
echo "다음 단계:"
echo "  1. Claude Code 로그인: claude"
echo "  2. 서비스 시작: sudo systemctl start a2a-orchestrator"
echo "  3. 로그 확인: sudo journalctl -u a2a-orchestrator -f"
echo "  4. 대시보드: http://<IP>:8000/dashboard"
echo "=========================================="
