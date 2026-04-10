#!/bin/bash
# ============================================================
# A2A 계층형 오케스트레이터 - 올인원 설정 & 실행 스크립트
#
# 사용법:
#   bash scripts/setup_and_run.sh
#
# 인터랙티브하게 역할을 선택하면 환경검증 → 설정 → 실행까지 자동 처리
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_DIR="$PROJECT_DIR/agent"
ORCH_DIR="$PROJECT_DIR/orchestrator"
VENV_DIR="$PROJECT_DIR/.venv"
MIN_PYTHON_VERSION="3.10"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
step() { echo -e "\n${CYAN}[$1]${NC} $2"; }
header() { echo -e "\n${BOLD}$1${NC}"; echo "$(printf '=%.0s' $(seq 1 ${#1}))"; }

# ──────────────────────────────────────────
# 역할 선택
# ──────────────────────────────────────────
select_role() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}║   A2A 계층형 오케스트레이터 올인원 설정    ║${NC}"
    echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
    echo ""
    echo "이 PC의 역할을 선택하세요:"
    echo ""
    echo -e "  ${CYAN}1)${NC} Meta-Orchestrator  (최상위 - 하위 오케스트레이터들을 조율)"
    echo -e "  ${CYAN}2)${NC} Sub-Orchestrator   (하위 - 자체 에이전트 + 상위에 등록)"
    echo -e "  ${CYAN}3)${NC} Agent Only         (에이전트만 - 오케스트레이터에 등록)"
    echo ""
    read -p "선택 [1/2/3]: " ROLE_NUM

    case "$ROLE_NUM" in
        1) ROLE="meta" ;;
        2) ROLE="sub" ;;
        3) ROLE="agent" ;;
        *)
            echo -e "${RED}잘못된 선택입니다.${NC}"
            exit 1
            ;;
    esac
}

# ──────────────────────────────────────────
# 환경 검증 (공통)
# ──────────────────────────────────────────
verify_environment() {
    header "환경 검증"

    # --- Python ---
    step "1/5" "Python 확인 (>= $MIN_PYTHON_VERSION)"
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
        if command -v brew &>/dev/null; then
            warn "Python 미설치 → brew로 설치"
            brew install python@3.12
            python_cmd="python3"
        elif command -v apt-get &>/dev/null; then
            warn "Python 미설치 → apt로 설치"
            sudo apt-get update -qq && sudo apt-get install -y python3 python3-pip python3-venv
            python_cmd="python3"
        else
            fail "Python >= $MIN_PYTHON_VERSION를 수동으로 설치해주세요"
            exit 1
        fi
        pass "Python 설치 완료: $($python_cmd --version)"
    fi

    # --- Node.js ---
    step "2/5" "Node.js 확인"
    if command -v node &>/dev/null; then
        pass "Node.js: $(node -v)"
    else
        if command -v brew &>/dev/null; then
            brew install node
        elif command -v apt-get &>/dev/null; then
            curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
            sudo apt-get install -y nodejs
        fi
        pass "Node.js: $(node -v)"
    fi

    # --- Claude Code CLI ---
    step "3/5" "Claude Code CLI 확인"
    if command -v claude &>/dev/null; then
        pass "Claude Code CLI 설치됨"
    else
        warn "Claude Code CLI 미설치 → 설치 중"
        npm install -g @anthropic-ai/claude-code
        pass "Claude Code CLI 설치 완료"
    fi

    # --- cloudflared (에이전트/하위 오케스트레이터만) ---
    if [ "$ROLE" != "meta" ]; then
        step "4/5" "cloudflared 확인"
        if command -v cloudflared &>/dev/null; then
            pass "cloudflared: $(cloudflared --version 2>&1 | head -1)"
        else
            if command -v brew &>/dev/null; then
                brew install cloudflared
            else
                warn "cloudflared를 수동 설치해주세요: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
            fi
        fi
    else
        step "4/5" "cloudflared 스킵 (Meta-Orchestrator는 불필요)"
        pass "스킵"
    fi

    # --- Python venv & 패키지 ---
    step "5/5" "Python 가상환경 & 패키지"
    if [ ! -d "$VENV_DIR" ] || ! "$VENV_DIR/bin/python3" -c "import sys" 2>/dev/null; then
        warn "venv 생성 중..."
        rm -rf "$VENV_DIR"
        "$python_cmd" -m venv "$VENV_DIR"
    fi
    pass "venv: $("$VENV_DIR/bin/python3" --version)"

    # 패키지 설치
    local req_file="$ORCH_DIR/requirements.txt"
    if [ "$ROLE" = "agent" ]; then
        req_file="$AGENT_DIR/requirements.txt"
    fi
    "$VENV_DIR/bin/pip" install -q -r "$req_file" 2>/dev/null
    # 하위 오케스트레이터는 두 requirements 모두 필요
    if [ "$ROLE" = "sub" ]; then
        "$VENV_DIR/bin/pip" install -q -r "$AGENT_DIR/requirements.txt" 2>/dev/null
    fi
    pass "패키지 설치 완료"

    # import 검증
    if "$VENV_DIR/bin/python3" -c "from a2a.server.apps import A2AStarletteApplication" 2>/dev/null; then
        pass "a2a-sdk import 정상"
    else
        fail "a2a-sdk import 실패. 수동 확인 필요"
        exit 1
    fi
}

# ──────────────────────────────────────────
# Meta-Orchestrator 설정 & 실행
# ──────────────────────────────────────────
setup_meta() {
    header "Meta-Orchestrator 설정"

    read -p "별칭 (대시보드 표시명, 예: 메타): " META_ALIAS
    META_ALIAS=${META_ALIAS:-"Meta"}

    read -p "포트 (기본: 9000): " META_PORT
    META_PORT=${META_PORT:-9000}

    read -p "토론 라운드 수 (기본: 1): " META_ROUNDS
    META_ROUNDS=${META_ROUNDS:-1}

    read -p "하위 오케스트레이터 타임아웃(초, 기본: 600): " META_TIMEOUT
    META_TIMEOUT=${META_TIMEOUT:-600}

    # .env 생성
    local ENV_FILE="$ORCH_DIR/.env"
    cat > "$ENV_FILE" << EOF
ORCHESTRATOR_HOST=0.0.0.0
ORCHESTRATOR_PORT=$META_PORT
ORCHESTRATOR_NAME=Meta-Orchestrator
ORCHESTRATOR_ALIAS=$META_ALIAS
DEBATE_ROUNDS=$META_ROUNDS
OUTPUT_DIR=./reports
AGENTS_FILE=./agents.json
SUB_ORCHESTRATOR_TIMEOUT=$META_TIMEOUT
EOF
    pass ".env 생성: $ENV_FILE"

    # agents.json 초기화
    if [ ! -f "$ORCH_DIR/agents.json" ]; then
        echo '{"agents":[]}' > "$ORCH_DIR/agents.json"
        pass "agents.json 초기화"
    fi

    echo ""
    echo -e "${GREEN}━━━ Meta-Orchestrator 시작 ━━━${NC}"
    echo -e "  URL:   http://0.0.0.0:${META_PORT}"
    echo -e "  대시보드: http://0.0.0.0:${META_PORT}/dashboard"
    echo -e "  별칭:  $META_ALIAS"
    echo ""
    echo "하위 오케스트레이터에서 이 주소로 등록됩니다:"
    echo -e "  ${CYAN}PARENT_ORCHESTRATOR_URL=http://<이_PC_IP>:${META_PORT}${NC}"
    echo ""
    echo "Ctrl+C로 종료"
    echo ""

    cd "$ORCH_DIR"
    source "$VENV_DIR/bin/activate"
    set -a && source .env && set +a
    exec python server.py
}

# ──────────────────────────────────────────
# Sub-Orchestrator 설정 & 실행
# ──────────────────────────────────────────
setup_sub() {
    header "Sub-Orchestrator 설정"

    read -p "이 오케스트레이터 이름 (고유 ID, 예: team-backend): " SUB_NAME
    SUB_NAME=${SUB_NAME:-"sub-orchestrator"}

    read -p "별칭 (대시보드 표시명, 예: 백엔드팀): " SUB_ALIAS
    SUB_ALIAS=${SUB_ALIAS:-"$SUB_NAME"}

    read -p "포트 (기본: 8000): " SUB_PORT
    SUB_PORT=${SUB_PORT:-8000}

    read -p "상위 Meta-Orchestrator URL (예: http://192.168.1.10:9000): " PARENT_URL
    if [ -z "$PARENT_URL" ]; then
        fail "상위 오케스트레이터 URL은 필수입니다"
        exit 1
    fi

    read -p "스킬셋 (쉼표 구분, 예: backend,database,api): " SUB_SKILLS
    SUB_SKILLS=${SUB_SKILLS:-"general"}

    read -p "토론 라운드 수 (기본: 2): " SUB_ROUNDS
    SUB_ROUNDS=${SUB_ROUNDS:-2}

    # 터널이 필요한지 확인
    local USE_TUNNEL="n"
    echo ""
    echo "상위 오케스트레이터가 이 PC에 직접 접근할 수 있나요?"
    echo "  같은 네트워크면 → n (직접 IP 사용)"
    echo "  외부 네트워크면  → y (Cloudflare 터널 사용)"
    read -p "터널 사용? [y/N]: " USE_TUNNEL
    USE_TUNNEL=${USE_TUNNEL:-n}

    # .env 생성
    local ENV_FILE="$ORCH_DIR/.env"
    cat > "$ENV_FILE" << EOF
ORCHESTRATOR_HOST=0.0.0.0
ORCHESTRATOR_PORT=$SUB_PORT
ORCHESTRATOR_NAME=$SUB_NAME
ORCHESTRATOR_ALIAS=$SUB_ALIAS
DEBATE_ROUNDS=$SUB_ROUNDS
OUTPUT_DIR=./reports
AGENTS_FILE=./agents.json
PARENT_ORCHESTRATOR_URL=$PARENT_URL
ORCHESTRATOR_SKILLS=$SUB_SKILLS
EOF
    pass ".env 생성: $ENV_FILE"

    # agents.json 초기화
    if [ ! -f "$ORCH_DIR/agents.json" ]; then
        echo '{"agents":[]}' > "$ORCH_DIR/agents.json"
    fi

    # 에이전트도 같이 띄울지
    echo ""
    read -p "이 PC에서 에이전트도 같이 실행할까요? [Y/n]: " WITH_AGENT
    WITH_AGENT=${WITH_AGENT:-y}

    local AGENT_PID=""
    local TUNNEL_PID=""
    local ORCH_TUNNEL_PID=""

    cleanup() {
        echo ""
        echo "모든 프로세스 종료 중..."
        [ -n "$AGENT_PID" ] && kill $AGENT_PID 2>/dev/null
        [ -n "$TUNNEL_PID" ] && kill $TUNNEL_PID 2>/dev/null
        [ -n "$ORCH_TUNNEL_PID" ] && kill $ORCH_TUNNEL_PID 2>/dev/null
        wait 2>/dev/null
        echo "종료 완료."
    }
    trap cleanup EXIT INT TERM

    source "$VENV_DIR/bin/activate"

    # 에이전트 설정 & 시작
    if [[ "$WITH_AGENT" =~ ^[Yy] ]]; then
        echo ""
        header "로컬 에이전트 설정"

        read -p "에이전트 이름 (예: 홍길동-agent): " AG_NAME
        AG_NAME=${AG_NAME:-"local-agent"}

        read -p "에이전트 별칭 (예: 길동): " AG_ALIAS
        AG_ALIAS=${AG_ALIAS:-"$AG_NAME"}

        read -p "에이전트 포트 (기본: 8001): " AG_PORT
        AG_PORT=${AG_PORT:-8001}

        read -p "에이전트 스킬셋 (쉼표 구분): " AG_SKILLS
        AG_SKILLS=${AG_SKILLS:-"general,analysis"}

        mkdir -p "$AGENT_DIR/data"

        cat > "$AGENT_DIR/.env" << EOF
AGENT_HOST=0.0.0.0
AGENT_PORT=$AG_PORT
AGENT_NAME=$AG_NAME
AGENT_DESCRIPTION=${AG_ALIAS}의 Claude 에이전트
ORCHESTRATOR_URL=http://localhost:$SUB_PORT
AGENT_PUBLIC_URL=http://localhost:$AG_PORT
DATA_DIR=./data
ALLOWED_TOOLS=Read,Glob,Grep
AGENT_SKILLS=$AG_SKILLS
EOF
        pass "에이전트 .env 생성"

        cd "$AGENT_DIR"
        set -a && source .env && set +a
        python server.py &
        AGENT_PID=$!
        pass "에이전트 시작 (PID: $AGENT_PID, 포트: $AG_PORT)"
        sleep 2
    fi

    # 터널 사용 시 오케스트레이터 터널 시작
    if [[ "$USE_TUNNEL" =~ ^[Yy] ]]; then
        local TUNNEL_LOG=$(mktemp)
        cloudflared tunnel --url http://localhost:${SUB_PORT} \
            --logfile "$TUNNEL_LOG" 2>&1 | tee -a "$TUNNEL_LOG" &
        ORCH_TUNNEL_PID=$!

        echo "터널 시작 대기 중..."
        local TUNNEL_URL=""
        for i in $(seq 1 30); do
            TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
            if [ -n "$TUNNEL_URL" ]; then break; fi
            sleep 1
        done

        if [ -n "$TUNNEL_URL" ]; then
            pass "터널 URL: $TUNNEL_URL"
            echo "ORCHESTRATOR_PUBLIC_URL=$TUNNEL_URL" >> "$ORCH_DIR/.env"
        else
            warn "터널 URL 감지 실패. 수동으로 PUBLIC_URL을 설정해야 합니다"
        fi
    else
        # 직접 IP 사용
        local MY_IP
        MY_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
        echo "ORCHESTRATOR_PUBLIC_URL=http://${MY_IP}:${SUB_PORT}" >> "$ORCH_DIR/.env"
        pass "공개 URL: http://${MY_IP}:${SUB_PORT}"
    fi

    # 오케스트레이터 시작
    echo ""
    echo -e "${GREEN}━━━ Sub-Orchestrator 시작 ━━━${NC}"
    echo -e "  이름:    $SUB_NAME ($SUB_ALIAS)"
    echo -e "  포트:    $SUB_PORT"
    echo -e "  상위:    $PARENT_URL"
    echo -e "  스킬:    $SUB_SKILLS"
    [ -n "$AGENT_PID" ] && echo -e "  에이전트: $AG_NAME (포트 $AG_PORT)"
    echo ""
    echo "Ctrl+C로 종료"
    echo ""

    cd "$ORCH_DIR"
    set -a && source .env && set +a
    python server.py
}

# ──────────────────────────────────────────
# Agent Only 설정 & 실행
# ──────────────────────────────────────────
setup_agent() {
    header "에이전트 설정"

    read -p "에이전트 이름 (예: 홍길동-agent): " AG_NAME
    AG_NAME=${AG_NAME:-"my-agent"}

    read -p "에이전트 별칭 (예: 길동): " AG_ALIAS
    AG_ALIAS=${AG_ALIAS:-"$AG_NAME"}

    read -p "에이전트 설명: " AG_DESC
    AG_DESC=${AG_DESC:-"${AG_ALIAS}의 Claude 에이전트"}

    read -p "포트 (기본: 8001): " AG_PORT
    AG_PORT=${AG_PORT:-8001}

    read -p "오케스트레이터 URL (예: http://192.168.1.10:8000): " ORCH_URL
    if [ -z "$ORCH_URL" ]; then
        fail "오케스트레이터 URL은 필수입니다"
        exit 1
    fi

    read -p "스킬셋 (쉼표 구분, 예: analysis,coding): " AG_SKILLS
    AG_SKILLS=${AG_SKILLS:-"general,analysis"}

    mkdir -p "$AGENT_DIR/data"

    echo ""
    echo "오케스트레이터가 이 PC에 직접 접근할 수 있나요?"
    read -p "터널 사용? [y/N]: " USE_TUNNEL
    USE_TUNNEL=${USE_TUNNEL:-n}

    cat > "$AGENT_DIR/.env" << EOF
AGENT_HOST=0.0.0.0
AGENT_PORT=$AG_PORT
AGENT_NAME=$AG_NAME
AGENT_DESCRIPTION=$AG_DESC
ORCHESTRATOR_URL=$ORCH_URL
AGENT_PUBLIC_URL=
DATA_DIR=./data
ALLOWED_TOOLS=Read,Glob,Grep
AGENT_SKILLS=$AG_SKILLS
EOF
    pass ".env 생성"

    source "$VENV_DIR/bin/activate"

    if [[ "$USE_TUNNEL" =~ ^[Yy] ]]; then
        # 터널 모드 - 기존 스크립트 활용
        echo ""
        echo -e "${GREEN}━━━ 에이전트 + 터널 시작 ━━━${NC}"
        exec bash "$PROJECT_DIR/tunnel/start_agent_with_tunnel.sh"
    else
        # 직접 접속 모드
        local MY_IP
        MY_IP=$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
        export AGENT_PUBLIC_URL="http://${MY_IP}:${AG_PORT}"
        # .env 업데이트
        sed -i.bak "s|AGENT_PUBLIC_URL=.*|AGENT_PUBLIC_URL=$AGENT_PUBLIC_URL|" "$AGENT_DIR/.env"
        pass "공개 URL: $AGENT_PUBLIC_URL"

        echo ""
        echo -e "${GREEN}━━━ 에이전트 시작 ━━━${NC}"
        echo -e "  이름: $AG_NAME ($AG_ALIAS)"
        echo -e "  포트: $AG_PORT"
        echo -e "  오케스트레이터: $ORCH_URL"
        echo ""
        echo "data/ 폴더에 참고 데이터를 넣으면 에이전트가 활용합니다:"
        echo "  $AGENT_DIR/data/"
        echo ""
        echo "Ctrl+C로 종료"
        echo ""

        cd "$AGENT_DIR"
        set -a && source .env && set +a
        exec python server.py
    fi
}

# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────
select_role
verify_environment

case "$ROLE" in
    meta)  setup_meta ;;
    sub)   setup_sub ;;
    agent) setup_agent ;;
esac
