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

cleanup() {
    echo ""
    echo "모든 프로세스 종료 중..."
    kill $META_PID $SUB_A_PID $SUB_B_PID 2>/dev/null || true
    wait $META_PID $SUB_A_PID $SUB_B_PID 2>/dev/null || true
    echo "종료 완료."
}
trap cleanup EXIT INT TERM

echo "=== 계층형 오케스트레이터 시작 ==="
echo ""

# 1. Meta-Orchestrator (포트 9000)
echo "[1/3] Meta-Orchestrator 시작 (포트 9000)..."
cd "$ORCH_DIR"
env $(cat "$SCRIPT_DIR/meta_orchestrator.env" | grep -v '^#' | xargs) \
    python server.py &
META_PID=$!
sleep 2

# 2. Sub-Orchestrator A (포트 8000)
echo "[2/3] Sub-Orchestrator A 시작 (포트 8000)..."
env $(cat "$SCRIPT_DIR/sub_orchestrator_a.env" | grep -v '^#' | xargs) \
    python server.py &
SUB_A_PID=$!
sleep 2

# 3. Sub-Orchestrator B (포트 8100)
echo "[3/3] Sub-Orchestrator B 시작 (포트 8100)..."
env $(cat "$SCRIPT_DIR/sub_orchestrator_b.env" | grep -v '^#' | xargs) \
    python server.py &
SUB_B_PID=$!
sleep 2

echo ""
echo "=== 모든 오케스트레이터 실행 중 ==="
echo "  Meta-Orchestrator : http://localhost:9000 (PID: $META_PID)"
echo "  Sub-Orchestrator A: http://localhost:8000 (PID: $SUB_A_PID)"
echo "  Sub-Orchestrator B: http://localhost:8100 (PID: $SUB_B_PID)"
echo ""
echo "테스트 예시:"
echo "  curl -X POST http://localhost:9000/debate -H 'Content-Type: application/json' -d '{\"topic\": \"마이크로서비스 vs 모놀리식 아키텍처\"}'"
echo ""
echo "등록 확인:"
echo "  curl http://localhost:9000/agents"
echo ""
echo "Ctrl+C로 종료합니다."

wait
