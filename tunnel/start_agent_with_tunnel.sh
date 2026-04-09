#!/bin/bash
# 에이전트와 터널을 동시에 시작하는 스크립트
# 터널 URL을 자동으로 감지하여 환경변수에 설정합니다

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AGENT_PORT=${AGENT_PORT:-8001}
ENV_FILE=${ENV_FILE:-"$SCRIPT_ROOT/agent/.env"}
AGENT_DIR=${AGENT_DIR:-"$SCRIPT_ROOT/agent"}

echo "=========================================="
echo "에이전트 + Cloudflare Tunnel 동시 시작"
echo "=========================================="

# 환경 검증 (install_agent.sh 호출)
echo "환경 검증 중..."
bash "$SCRIPT_ROOT/scripts/install_agent.sh"
echo ""

# 임시 로그 파일
TUNNEL_LOG=$(mktemp)
TUNNEL_URL_FILE=$(mktemp)

# 백그라운드에서 터널 시작 + URL 캡처
cloudflared tunnel --url http://localhost:${AGENT_PORT} \
    --logfile "$TUNNEL_LOG" 2>&1 | \
    tee -a "$TUNNEL_LOG" &
TUNNEL_PID=$!

echo "터널 시작 중..."

# URL이 나타날 때까지 대기 (최대 30초)
for i in $(seq 1 30); do
    TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    sleep 1
done

if [ -z "$TUNNEL_URL" ]; then
    echo "오류: 터널 URL을 가져올 수 없습니다."
    kill $TUNNEL_PID 2>/dev/null
    exit 1
fi

echo "터널 URL: $TUNNEL_URL"

# .env 파일에 URL 자동 업데이트
if [ -f "$ENV_FILE" ]; then
    if grep -q "AGENT_PUBLIC_URL" "$ENV_FILE"; then
        sed -i.bak "s|AGENT_PUBLIC_URL=.*|AGENT_PUBLIC_URL=$TUNNEL_URL|" "$ENV_FILE"
    else
        echo "AGENT_PUBLIC_URL=$TUNNEL_URL" >> "$ENV_FILE"
    fi
    echo ".env 업데이트 완료: AGENT_PUBLIC_URL=$TUNNEL_URL"
fi

# 에이전트 시작
echo "에이전트 시작 중..."
cd "$AGENT_DIR"

# venv 활성화
if [ -d "$SCRIPT_ROOT/.venv" ]; then
    source "$SCRIPT_ROOT/.venv/bin/activate"
elif [ -d "$SCRIPT_ROOT/venv" ]; then
    source "$SCRIPT_ROOT/venv/bin/activate"
fi

export AGENT_PUBLIC_URL="$TUNNEL_URL"
[ -f .env ] && set -a && source .env && set +a

python server.py &
AGENT_PID=$!

echo ""
echo "실행 중:"
echo "  터널 PID: $TUNNEL_PID  URL: $TUNNEL_URL"
echo "  에이전트 PID: $AGENT_PID  포트: $AGENT_PORT"
echo ""
echo "종료하려면 Ctrl+C"

# 종료 시 모두 정리
trap "echo '종료 중...'; kill $TUNNEL_PID $AGENT_PID 2>/dev/null; rm -f $TUNNEL_LOG $TUNNEL_URL_FILE" EXIT

wait
