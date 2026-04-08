#!/bin/bash
# 시스템 전체 동작 테스트 스크립트

ORCHESTRATOR_URL=${ORCHESTRATOR_URL:-"http://localhost:8000"}

echo "=========================================="
echo "A2A 시스템 테스트"
echo "오케스트레이터: $ORCHESTRATOR_URL"
echo "=========================================="

PASS=0
FAIL=0

check() {
    local desc="$1"
    local cmd="$2"
    local expect="$3"

    result=$(eval "$cmd" 2>/dev/null)
    if echo "$result" | grep -q "$expect"; then
        echo "  ✅ $desc"
        ((PASS++))
    else
        echo "  ❌ $desc"
        echo "     결과: $result"
        ((FAIL++))
    fi
}

echo ""
echo "[1] 오케스트레이터 헬스체크"
check "Agent Card 접근" \
    "curl -s $ORCHESTRATOR_URL/.well-known/agent.json" \
    "name"

check "에이전트 목록 API" \
    "curl -s $ORCHESTRATOR_URL/agents" \
    "agents"

echo ""
echo "[2] 등록된 에이전트 확인"
AGENTS=$(curl -s "$ORCHESTRATOR_URL/agents" 2>/dev/null)
echo "  등록된 에이전트: $AGENTS"

echo ""
echo "[3] 간단한 토론 테스트"
check "토론 API 응답" \
    "curl -s -X POST $ORCHESTRATOR_URL/debate -H 'Content-Type: application/json' -d '{\"topic\": \"테스트: AI의 장점\"}'" \
    "topic"

echo ""
echo "=========================================="
echo "결과: ✅ $PASS 통과 / ❌ $FAIL 실패"
echo "=========================================="

[ $FAIL -eq 0 ] && exit 0 || exit 1
