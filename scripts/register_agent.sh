#!/bin/bash
# 에이전트를 오케스트레이터에 등록하는 스크립트
# .env 파일이 있으면 자동으로 값을 읽어옵니다

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../agent/.env"

# .env 파일에서 기본값 로드
if [ -f "$ENV_FILE" ]; then
    set -a && source "$ENV_FILE" && set +a
fi

ORCHESTRATOR_URL=${ORCHESTRATOR_URL:-"http://localhost:8000"}
AGENT_NAME=${1:-${AGENT_NAME:-"my-agent"}}
AGENT_URL=${2:-${AGENT_PUBLIC_URL:-""}}
AGENT_DESC=${3:-${AGENT_DESCRIPTION:-"Claude 기반 A2A 에이전트"}}
AGENT_SKILLS=${4:-'["general","analysis"]'}

if [ -z "$AGENT_URL" ]; then
    echo "사용법: $0 [이름] [URL] [설명] [스킬]"
    echo ""
    echo ".env 파일이 있으면 자동으로 값을 읽습니다."
    echo "예시:"
    echo "  $0                                          # .env에서 자동 로드"
    echo "  $0 홍길동-agent https://xxxx.trycloudflare.com"
    echo "  $0 홍길동-agent https://xxxx.trycloudflare.com '설명' '[\"finance\",\"data\"]'"
    exit 1
fi

echo "에이전트 등록 중..."
echo "  오케스트레이터: $ORCHESTRATOR_URL"
echo "  이름: $AGENT_NAME"
echo "  URL: $AGENT_URL"
echo "  스킬: $AGENT_SKILLS"

RESPONSE=$(curl -s -X POST "$ORCHESTRATOR_URL/agents/register" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$AGENT_NAME\", \"url\": \"$AGENT_URL\", \"description\": \"$AGENT_DESC\", \"skills\": $AGENT_SKILLS}")

echo "응답: $RESPONSE"
