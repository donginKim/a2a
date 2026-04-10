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
LOG_DIR="$PROJECT_DIR/logs"
PID_DIR="$PROJECT_DIR/.pids"
MIN_PYTHON="3.12"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

pass() { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}!${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
step() { echo -e "\n${CYAN}[$1]${NC} $2"; }
header() { echo -e "\n${BOLD}$1${NC}"; echo "$(printf '=%.0s' $(seq 1 ${#1}))"; }

# 로그/PID 디렉토리 초기화
init_dirs() {
    mkdir -p "$LOG_DIR" "$PID_DIR"
}

# 서버를 백그라운드로 실행하고 로그 리다이렉션
# 사용법: start_server <name> <work_dir> <command...>
start_server() {
    local name="$1"
    local work_dir="$2"
    shift 2
    local log_file="$LOG_DIR/${name}.log"
    local pid_file="$PID_DIR/${name}.pid"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo "───────────────────────────────" >> "$log_file"
    echo "[$timestamp] $name 시작" >> "$log_file"
    echo "───────────────────────────────" >> "$log_file"

    cd "$work_dir"
    nohup "$@" >> "$log_file" 2>&1 &
    local pid=$!
    echo $pid > "$pid_file"
    echo "$pid"
}

# 로그 파일 tail (포그라운드 모니터링용)
tail_logs() {
    echo ""
    echo -e "${CYAN}[로그 모니터링]${NC} 모든 서버 로그를 출력합니다 (Ctrl+C로 종료)"
    echo ""
    tail -F "$LOG_DIR"/*.log 2>/dev/null
}

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
# 누락 항목 수집 → Y/N 한 번에 확인 → 자동 설치
# ──────────────────────────────────────────
verify_environment() {
    header "환경 검증 (Python >= ${MIN_PYTHON})"

    local missing=()
    local python_cmd=""
    local need_venv=false

    # ── 1. 검사: 무엇이 누락되었는지 파악 ──

    # Homebrew (Mac만)
    if [[ "$(uname)" == "Darwin" ]] && ! command -v brew &>/dev/null; then
        missing+=("Homebrew")
    fi

    # Python >= MIN_PYTHON
    for cmd in python3 "python${MIN_PYTHON}" python; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
            if python3 -c "exit(0 if tuple(map(int,'$ver'.split('.'))) >= tuple(map(int,'${MIN_PYTHON}'.split('.'))) else 1)" 2>/dev/null || \
               [ "$(printf '%s\n' "$MIN_PYTHON" "$ver" | sort -V | head -1)" = "$MIN_PYTHON" ]; then
                python_cmd="$cmd"
                break
            fi
        fi
    done
    if [ -z "$python_cmd" ]; then
        missing+=("Python >= ${MIN_PYTHON}")
    fi

    # Node.js
    if ! command -v node &>/dev/null; then
        missing+=("Node.js")
    fi

    # Claude Code CLI
    if ! command -v claude &>/dev/null; then
        missing+=("Claude Code CLI")
    fi

    # cloudflared (Meta 제외)
    if [ "$ROLE" != "meta" ] && ! command -v cloudflared &>/dev/null; then
        missing+=("cloudflared")
    fi

    # venv
    if [ ! -d "$VENV_DIR" ] || ! "$VENV_DIR/bin/python3" -c "import sys" 2>/dev/null; then
        need_venv=true
    fi

    # ── 2. 이미 설치된 항목 출력 ──

    echo ""
    [ -n "$python_cmd" ] && pass "Python: $($python_cmd --version)"
    command -v node &>/dev/null && pass "Node.js: $(node -v)"
    command -v claude &>/dev/null && pass "Claude Code CLI: 설치됨"
    [ "$ROLE" != "meta" ] && command -v cloudflared &>/dev/null && pass "cloudflared: $(cloudflared --version 2>&1 | head -1)"

    # ── 3. 누락 항목이 있으면 Y/N 한 번만 확인 ──

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
            fail "설치를 취소했습니다. 위 항목을 수동으로 설치 후 다시 실행하세요."
            exit 1
        fi
        echo ""
    else
        echo ""
        pass "모든 필수 항목이 설치되어 있습니다"
    fi

    # ── 4. 자동 설치 ──

    # Homebrew (Mac)
    if [[ " ${missing[*]} " =~ "Homebrew" ]]; then
        step "설치" "Homebrew"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Apple Silicon PATH
        [ -f /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
        pass "Homebrew 설치 완료"
    fi

    # Python 고정 버전
    if [[ " ${missing[*]} " =~ "Python" ]]; then
        step "설치" "Python ${MIN_PYTHON}"
        if command -v brew &>/dev/null; then
            brew install "python@${MIN_PYTHON}"
            python_cmd="$(brew --prefix python@${MIN_PYTHON})/bin/python${MIN_PYTHON}"
            [ ! -f "$python_cmd" ] && python_cmd="python${MIN_PYTHON}"
        elif command -v apt-get &>/dev/null; then
            sudo apt-get update -qq
            # Ubuntu: deadsnakes PPA 시도
            if grep -qi ubuntu /etc/os-release 2>/dev/null; then
                sudo apt-get install -y software-properties-common
                sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null || true
                sudo apt-get update -qq
            fi
            sudo apt-get install -y "python${MIN_PYTHON}" "python${MIN_PYTHON}-venv" "python${MIN_PYTHON}-dev" 2>/dev/null || {
                warn "apt 패키지 없음 → 소스 빌드로 설치합니다"
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
                warn "기본 저장소에 없음 → EPEL + CRB 활성화 후 재시도"
                sudo dnf install -y epel-release 2>/dev/null || true
                sudo dnf config-manager --set-enabled crb 2>/dev/null || \
                    sudo dnf config-manager --set-enabled powertools 2>/dev/null || true
                sudo dnf install -y "python${MIN_PYTHON}" "python${MIN_PYTHON}-devel"
            }
            python_cmd="python${MIN_PYTHON}"
        elif command -v yum &>/dev/null; then
            sudo yum install -y epel-release 2>/dev/null || true
            sudo yum install -y "python${MIN_PYTHON}" "python${MIN_PYTHON}-devel" 2>/dev/null || {
                warn "yum에서 설치 실패 → 소스 빌드로 설치"
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

    # Node.js
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
        pass "Node.js 설치 완료: $(node -v)"
    fi

    # Claude Code CLI
    if [[ " ${missing[*]} " =~ "Claude Code CLI" ]]; then
        step "설치" "Claude Code CLI"
        npm install -g @anthropic-ai/claude-code
        pass "Claude Code CLI 설치 완료"
    fi

    # cloudflared
    if [[ " ${missing[*]} " =~ "cloudflared" ]]; then
        step "설치" "cloudflared"
        if command -v brew &>/dev/null; then
            brew install cloudflared
        elif command -v apt-get &>/dev/null; then
            curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
            sudo dpkg -i /tmp/cloudflared.deb
            rm -f /tmp/cloudflared.deb
        elif command -v dnf &>/dev/null || command -v yum &>/dev/null; then
            curl -fsSL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-x86_64.rpm -o /tmp/cloudflared.rpm
            sudo rpm -ivh /tmp/cloudflared.rpm 2>/dev/null || sudo rpm -Uvh /tmp/cloudflared.rpm
            rm -f /tmp/cloudflared.rpm
        fi
        pass "cloudflared 설치 완료"
    fi

    # ── 5. Python venv & 패키지 (항상 실행) ──

    step "설정" "Python ${MIN_PYTHON} 가상환경 & 패키지"

    # venv가 없거나 버전이 다르면 재생성
    if [ "$need_venv" = true ]; then
        rm -rf "$VENV_DIR"
        "$python_cmd" -m venv "$VENV_DIR"
        pass "venv 생성: $("$VENV_DIR/bin/python3" --version)"
    else
        # venv가 있어도 Python 버전 확인
        local venv_ver
        venv_ver=$("$VENV_DIR/bin/python3" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        if [ "$(printf '%s\n' "$MIN_PYTHON" "$venv_ver" | sort -V | head -1)" != "$MIN_PYTHON" ]; then
            warn "venv Python 버전이 ${MIN_PYTHON} 미만 ($venv_ver) → 재생성"
            rm -rf "$VENV_DIR"
            "$python_cmd" -m venv "$VENV_DIR"
            pass "venv 재생성: $("$VENV_DIR/bin/python3" --version)"
        else
            pass "venv: $("$VENV_DIR/bin/python3" --version)"
        fi
    fi

    # 패키지 설치
    local req_file="$ORCH_DIR/requirements.txt"
    if [ "$ROLE" = "agent" ]; then
        req_file="$AGENT_DIR/requirements.txt"
    fi
    "$VENV_DIR/bin/pip" install -q -r "$req_file" 2>/dev/null
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

    echo ""
    local final_ver
    final_ver=$("$VENV_DIR/bin/python3" --version 2>&1)
    pass "환경 준비 완료 ($final_ver)"
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

    init_dirs

    echo ""
    echo -e "${GREEN}━━━ Meta-Orchestrator 시작 ━━━${NC}"
    echo -e "  URL:     http://0.0.0.0:${META_PORT}"
    echo -e "  대시보드: http://0.0.0.0:${META_PORT}/dashboard"
    echo -e "  별칭:    $META_ALIAS"
    echo -e "  로그:    $LOG_DIR/meta-orchestrator.log"
    echo ""
    echo "하위 오케스트레이터에서 이 주소로 등록됩니다:"
    echo -e "  ${CYAN}PARENT_ORCHESTRATOR_URL=http://<이_PC_IP>:${META_PORT}${NC}"
    echo ""

    cd "$ORCH_DIR"
    set -a && source .env && set +a
    local META_PID
    META_PID=$(start_server "meta-orchestrator" "$ORCH_DIR" "$VENV_DIR/bin/python3" server.py)
    pass "Meta-Orchestrator 시작 (PID: $META_PID)"

    cleanup() {
        echo ""
        echo "프로세스 종료 중..."
        kill $META_PID 2>/dev/null || true
        wait $META_PID 2>/dev/null || true
        echo "종료 완료."
    }
    trap cleanup EXIT INT TERM

    tail_logs
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

    init_dirs

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
AGENT_DESCRIPTION=${AG_ALIAS}의 에이전트
ORCHESTRATOR_URL=http://localhost:$SUB_PORT
AGENT_PUBLIC_URL=http://localhost:$AG_PORT
DATA_DIR=./data
ALLOWED_TOOLS=Read,Glob,Grep
AGENT_SKILLS=$AG_SKILLS
EOF
        pass "에이전트 .env 생성"

        cd "$AGENT_DIR"
        set -a && source .env && set +a
        AGENT_PID=$(start_server "agent-${AG_NAME}" "$AGENT_DIR" "$VENV_DIR/bin/python3" server.py)
        pass "에이전트 시작 (PID: $AGENT_PID, 포트: $AG_PORT)"
        pass "에이전트 로그: $LOG_DIR/agent-${AG_NAME}.log"
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

    cd "$ORCH_DIR"
    set -a && source .env && set +a
    local ORCH_PID
    ORCH_PID=$(start_server "sub-orchestrator-${SUB_NAME}" "$ORCH_DIR" "$VENV_DIR/bin/python3" server.py)
    pass "Sub-Orchestrator 시작 (PID: $ORCH_PID)"
    pass "오케스트레이터 로그: $LOG_DIR/sub-orchestrator-${SUB_NAME}.log"

    echo ""
    echo -e "${CYAN}로그 위치:${NC}"
    echo -e "  $LOG_DIR/"
    ls -1 "$LOG_DIR"/*.log 2>/dev/null | while read f; do echo "    $(basename "$f")"; done

    tail_logs
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

    init_dirs

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
        echo -e "  로그: $LOG_DIR/agent-${AG_NAME}.log"
        echo ""
        echo "data/ 폴더에 참고 데이터를 넣으면 에이전트가 활용합니다:"
        echo "  $AGENT_DIR/data/"
        echo ""

        cd "$AGENT_DIR"
        set -a && source .env && set +a
        local AG_PID
        AG_PID=$(start_server "agent-${AG_NAME}" "$AGENT_DIR" "$VENV_DIR/bin/python3" server.py)
        pass "에이전트 시작 (PID: $AG_PID)"

        cleanup() {
            echo ""
            echo "프로세스 종료 중..."
            kill $AG_PID 2>/dev/null || true
            wait $AG_PID 2>/dev/null || true
            echo "종료 완료."
        }
        trap cleanup EXIT INT TERM

        tail_logs
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
