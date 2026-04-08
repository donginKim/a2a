#!/bin/bash
# 에이전트를 오케스트레이터에 수동 등록하는 스크립트

ORCHESTRATOR_URL=${ORCHESTRATOR_URL:-"http://localhost:8000"}
AGENT_NAME=${1:-"my-agent"}
AGENT_URL=${2:-""}
AGENT_DESC=${3:-"Claude 기반 A2A 에이전트"}

if [ -z "$AGENT_URL" ]; then
    echo "사용법: $0 <에이전트이름> <에이전트URL> [설명]"
    echo "예시: $0 홍길동-agent https://xxxx.trycloudflare.com '홍길동의 에이전트'"
    exit 1
fi

echo "에이전트 등록 중..."
echo "  오케스트레이터: $ORCHESTRATOR_URL"
echo "  에이전트 이름: $AGENT_NAME"
echo "  에이전트 URL: $AGENT_URL"

RESPONSE=$(curl -s -X POST "$ORCHESTRATOR_URL/agents/register" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$AGENT_NAME\", \"url\": \"$AGENT_URL\", \"description\": \"$AGENT_DESC\"}")

echo "응답: $RESPONSE"
