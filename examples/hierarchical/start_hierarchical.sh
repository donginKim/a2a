#!/bin/bash
# 계층형 오케스트레이터 로컬 테스트 스크립트
# Meta-Orchestrator + 2개의 Sub-Orchestrator를 순차적으로 실행합니다.
#
# 사용법: ./start_hierarchical.sh
# 종료: Ctrl+C (모든 프로세스 종료)

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ORCH_DIR="$PROJECT_DIR/orchestrator"
LOG_DIR="$PROJECT_DIR/logs"
PID_DIR="$PROJECT_DIR/.pids"

mkdir -p "$LOG_DIR" "$PID_DIR"

cleanup() {
    echo ""
    echo "모든 프로세스 종료 중..."
    kill $META_PID $SUB_A_PID $SUB_B_PID 2>/dev/null || true
    wait $META_PID $SUB_A_PID $SUB_B_PID 2>/dev/null || true
    echo "종료 완료."
}
trap cleanup EXIT INT TERM

start_server() {
    local name="$1"
    local env_file="$2"
    local log_file="$LOG_DIR/${name}.log"
    local pid_file="$PID_DIR/${name}.pid"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    echo "───────────────────────────────" >> "$log_file"
    echo "[$timestamp] $name 시작" >> "$log_file"
    echo "───────────────────────────────" >> "$log_file"

    cd "$ORCH_DIR"
    nohup env $(cat "$env_file" | grep -v '^#' | xargs) \
        python server.py >> "$log_file" 2>&1 &
    local pid=$!
    echo $pid > "$pid_file"
    echo "$pid"
}

echo "=== 계층형 오케스트레이터 시작 ==="
echo ""

# 1. Meta-Orchestrator (포트 9000)
echo "[1/3] Meta-Orchestrator 시작 (포트 9000)..."
META_PID=$(start_server "meta-orchestrator" "$SCRIPT_DIR/meta_orchestrator.env")
echo "  PID: $META_PID | 로그: $LOG_DIR/meta-orchestrator.log"
sleep 2

# 2. Sub-Orchestrator A (포트 8000)
echo "[2/3] Sub-Orchestrator A 시작 (포트 8000)..."
SUB_A_PID=$(start_server "sub-orchestrator-a" "$SCRIPT_DIR/sub_orchestrator_a.env")
echo "  PID: $SUB_A_PID | 로그: $LOG_DIR/sub-orchestrator-a.log"
sleep 2

# 3. Sub-Orchestrator B (포트 8100)
echo "[3/3] Sub-Orchestrator B 시작 (포트 8100)..."
SUB_B_PID=$(start_server "sub-orchestrator-b" "$SCRIPT_DIR/sub_orchestrator_b.env")
echo "  PID: $SUB_B_PID | 로그: $LOG_DIR/sub-orchestrator-b.log"
sleep 2

echo ""
echo "=== 모든 오케스트레이터 실행 중 ==="
echo "  Meta-Orchestrator : http://localhost:9000 (PID: $META_PID)"
echo "  Sub-Orchestrator A: http://localhost:8000 (PID: $SUB_A_PID)"
echo "  Sub-Orchestrator B: http://localhost:8100 (PID: $SUB_B_PID)"
echo ""
echo "로그 위치: $LOG_DIR/"
ls -1 "$LOG_DIR"/*.log 2>/dev/null | while read f; do echo "  $(basename "$f")"; done
echo ""
echo "테스트 예시:"
echo "  curl -X POST http://localhost:9000/debate -H 'Content-Type: application/json' -d '{\"topic\": \"마이크로서비스 vs 모놀리식 아키텍처\"}'"
echo ""
echo "등록 확인:"
echo "  curl http://localhost:9000/agents"
echo ""
echo "개별 로그 확인:"
echo "  tail -f $LOG_DIR/meta-orchestrator.log"
echo ""
echo "=== 로그 모니터링 (Ctrl+C로 종료) ==="
echo ""
tail -F "$LOG_DIR"/*.log 2>/dev/null
