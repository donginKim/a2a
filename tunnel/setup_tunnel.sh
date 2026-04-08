#!/bin/bash
# Cloudflare Tunnel 설정 스크립트
# 로컬 에이전트 포트를 공개 URL로 노출합니다

set -e

AGENT_PORT=${AGENT_PORT:-8001}
TUNNEL_TOOL=${TUNNEL_TOOL:-cloudflared}  # cloudflared 또는 ngrok

echo "=========================================="
echo "Cloudflare Tunnel 설정"
echo "에이전트 포트: $AGENT_PORT"
echo "=========================================="

# cloudflared 설치 확인
if ! command -v cloudflared &>/dev/null; then
    echo "cloudflared 설치 중..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install cloudflared
    else
        # Linux
        curl -L --output cloudflared.deb \
            https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
        sudo dpkg -i cloudflared.deb
        rm cloudflared.deb
    fi
fi

echo ""
echo "터널 시작 중... (Ctrl+C로 종료)"
echo "아래에 나타나는 https://xxxx.trycloudflare.com URL을"
echo ".env 파일의 AGENT_PUBLIC_URL에 입력하세요."
echo ""

# 임시 터널 (무료, 로그인 불필요)
cloudflared tunnel --url http://localhost:${AGENT_PORT}
