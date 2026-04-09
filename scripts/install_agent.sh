#!/bin/bash
# Mac 에이전트 설치 자동화 스크립트
# 환경 검증 + 자동 복구 + 설치를 모두 처리합니다

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_DIR="$PROJECT_DIR/agent"
VENV_DIR="$PROJECT_DIR/.venv"
MIN_PYTHON_VERSION="3.10"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
step() { echo -e "\n${GREEN}[$1]${NC} $2"; }

# ──────────────────────────────────────────
# 환경 검증
# ──────────────────────────────────────────
verify_environment() {
    echo ""
    echo "=========================================="
    echo "환경 검증 시작"
    echo "=========================================="

    local issues=0

    # --- Homebrew ---
    step "1/7" "Homebrew 확인"
    if command -v brew &>/dev/null; then
        pass "Homebrew: $(brew --version | head -1)"
    else
        warn "Homebrew 미설치 → 설치합니다"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        pass "Homebrew 설치 완료"
    fi

    # --- Python ---
    step "2/7" "Python 확인 (>= $MIN_PYTHON_VERSION)"
    local python_cmd=""
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
            if python3 -c "exit(0 if tuple(map(int,'$ver'.split('.'))) >= tuple(map(int,'$MIN_PYTHON_VERSION'.split('.'))) else 1)" 2>/dev/null; then
                python_cmd="$cmd"
                break
            fi
        fi
    done

    if [ -n "$python_cmd" ]; then
        pass "Python: $($python_cmd --version)"
    else
        warn "Python >= $MIN_PYTHON_VERSION 미설치 → 설치합니다"
        brew install python@3.12
        python_cmd="python3"
        pass "Python 설치 완료: $($python_cmd --version)"
    fi

    # --- Node.js ---
    step "3/7" "Node.js 확인"
    if command -v node &>/dev/null; then
        pass "Node.js: $(node -v)"
    else
        warn "Node.js 미설치 → 설치합니다"
        brew install node
        pass "Node.js 설치 완료: $(node -v)"
    fi

    # --- Claude Code CLI ---
    step "4/7" "Claude Code CLI 확인"
    if command -v claude &>/dev/null; then
        pass "Claude Code: $(claude --version 2>/dev/null || echo '설치됨')"
    else
        warn "Claude Code CLI 미설치 → 설치합니다"
        npm install -g @anthropic-ai/claude-code
        pass "Claude Code CLI 설치 완료"
    fi

    # --- cloudflared ---
    step "5/7" "cloudflared 확인"
    if command -v cloudflared &>/dev/null; then
        pass "cloudflared: $(cloudflared --version 2>&1 | head -1)"
    else
        warn "cloudflared 미설치 → 설치합니다"
        brew install cloudflared
        pass "cloudflared 설치 완료"
    fi

    # --- Python venv ---
    step "6/7" "Python 가상환경 검증"
    local need_venv=false

    if [ ! -d "$VENV_DIR" ]; then
        warn "venv 디렉토리 없음 → 생성합니다"
        need_venv=true
    elif [ ! -f "$VENV_DIR/bin/python3" ] && [ ! -f "$VENV_DIR/bin/python" ]; then
        warn "venv에 python 바이너리 없음 → 재생성합니다"
        need_venv=true
    else
        # 심볼릭 링크 검증: 실제로 실행 가능한지 확인
        local venv_python="$VENV_DIR/bin/python3"
        [ ! -f "$venv_python" ] && venv_python="$VENV_DIR/bin/python"

        if ! "$venv_python" -c "import sys" 2>/dev/null; then
            warn "venv의 Python 링크가 깨짐 ($(readlink "$venv_python" 2>/dev/null || echo '?')) → 재생성합니다"
            need_venv=true
        else
            pass "venv Python 정상: $("$venv_python" --version)"
        fi
    fi

    if [ "$need_venv" = true ]; then
        rm -rf "$VENV_DIR"
        "$python_cmd" -m venv "$VENV_DIR"
        pass "venv 생성 완료: $("$VENV_DIR/bin/python3" --version)"
    fi

    # --- Python 패키지 ---
    step "7/7" "Python 패키지 검증"
    local venv_pip="$VENV_DIR/bin/pip"
    local need_install=false

    if [ -f "$AGENT_DIR/requirements.txt" ]; then
        while IFS= read -r line; do
            # 빈 줄, 주석 무시
            [[ -z "$line" || "$line" =~ ^# ]] && continue
            # 패키지 이름만 추출 (>=, ==, ~= 등 제거)
            local pkg
            pkg=$(echo "$line" | sed 's/[><=~!].*//' | sed 's/\[.*\]//' | tr '-' '_' | tr '[:upper:]' '[:lower:]')
            if ! "$VENV_DIR/bin/python3" -c "import importlib; importlib.import_module('$pkg')" 2>/dev/null; then
                # pip list로 한번 더 확인 (패키지명과 import명이 다를 수 있음)
                if ! "$venv_pip" show "$(echo "$line" | sed 's/[><=~!].*//')" &>/dev/null; then
                    warn "패키지 누락: $line"
                    need_install=true
                fi
            fi
        done < "$AGENT_DIR/requirements.txt"
    fi

    if [ "$need_install" = true ]; then
        warn "누락된 패키지 설치 중..."
        "$venv_pip" install -q -r "$AGENT_DIR/requirements.txt"
        pass "패키지 설치 완료"
    else
        pass "모든 패키지 설치됨"
    fi

    # --- 최종 import 테스트 ---
    if "$VENV_DIR/bin/python3" -c "from a2a.server.apps import A2AStarletteApplication" 2>/dev/null; then
        pass "a2a-sdk import 테스트 통과"
    else
        fail "a2a-sdk import 실패 — 패키지 재설치 시도"
        "$venv_pip" install --force-reinstall -q -r "$AGENT_DIR/requirements.txt"
        if "$VENV_DIR/bin/python3" -c "from a2a.server.apps import A2AStarletteApplication" 2>/dev/null; then
            pass "재설치 후 import 성공"
        else
            fail "a2a-sdk import 여전히 실패. 수동 확인 필요"
            exit 1
        fi
    fi
}

# ──────────────────────────────────────────
# .env 설정
# ──────────────────────────────────────────
setup_env() {
    echo ""
    echo "=========================================="
    echo ".env 설정"
    echo "=========================================="

    mkdir -p "$AGENT_DIR/data"

    ENV_FILE="$AGENT_DIR/.env"
    if [ -f "$ENV_FILE" ]; then
        pass ".env 파일 이미 존재: $ENV_FILE"
        echo "    (수정하려면 직접 편집하세요)"
        return
    fi

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
AGENT_NAME="$AGENT_NAME"
AGENT_DESCRIPTION="$AGENT_DESC"
ORCHESTRATOR_URL="$ORCH_URL"
AGENT_PUBLIC_URL=
DATA_DIR="$AGENT_DIR/data"
ALLOWED_TOOLS="Read,Glob,Grep"

# 스킬셋
AGENT_SKILLS="$AGENT_SKILLS"

# 참고 데이터 경로
AGENT_DATA_PATHS="$AGENT_DATA_PATHS"

# MCP 서버
AGENT_MCP_SERVERS="$AGENT_MCP_SERVERS"
EOF
    pass ".env 파일 생성: $ENV_FILE"
}

# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────
echo "=========================================="
echo "A2A 에이전트 설치 및 환경 검증"
echo "=========================================="

verify_environment
setup_env

echo ""
echo "=========================================="
echo -e "${GREEN}설치 및 검증 완료!${NC}"
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
