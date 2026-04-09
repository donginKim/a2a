#!/bin/bash
# 오케스트레이터 재시작 스크립트

echo "오케스트레이터 재시작 중..."

# 기존 프로세스 종료
sudo fuser -k 8000/tcp 2>/dev/null
sleep 1

# 서비스 재시작
sudo systemctl restart a2a-orchestrator

# 상태 확인
sudo systemctl status a2a-orchestrator --no-pager

echo ""
echo "로그 확인: sudo journalctl -u a2a-orchestrator -f"
