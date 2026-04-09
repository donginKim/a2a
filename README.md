# A2A 멀티 에이전트 토론 시스템

Google A2A 프로토콜 기반의 멀티 에이전트 협업 시스템입니다.
여러 사람의 에이전트가 주제에 대해 토론하고 보고서를 자동 생성합니다.

## 전체 구조

```
[내 Mac]          [동료1 Mac]        [동료2 Mac]
  에이전트            에이전트            에이전트
  (Claude)           (Claude)           (Claude)
    │                  │                  │
    └── cloudflared ───┼── cloudflared ───┘
                       │
                  [GCP 인스턴스]
                   오케스트레이터
                   (Claude + A2A)
                       │
                  reports/ 보고서 생성
```

- **오케스트레이터 (GCP)**: 토론 조율, 결과 취합, 보고서 생성
- **에이전트 (각 Mac)**: 로컬 데이터 기반 Claude 응답
- **통신**: A2A 프로토콜 (JSON-RPC 2.0 over HTTPS)
- **LLM**: Claude Code 구독 계정 (API 키 불필요)
- **NAT 통과**: Cloudflare Tunnel (무료)

---

## 빠른 시작

### GCP (오케스트레이터)

```bash
# 1. 설치
bash scripts/install_gcp.sh

# 2. Claude Code 로그인
claude

# 3. 서버 시작
cd orchestrator && python server.py
```

### Mac (에이전트)

```bash
# 1. 설치
bash scripts/install_agent.sh

# 2. Claude Code 로그인
claude

# 3. 로컬 데이터 추가 (선택)
cp ~/Documents/*.pdf agent/data/

# 4. 에이전트 + 터널 시작
cd tunnel && bash start_agent_with_tunnel.sh
```

### 토론 시작

```bash
curl -X POST http://<GCP_IP>:8000/debate \
  -H "Content-Type: application/json" \
  -d '{"topic": "우리 팀의 기술 스택 선택 전략"}'
```

---

## 폴더 구조

```
a2a/
├── orchestrator/           # GCP에서 실행
│   ├── server.py           # A2A 서버 + REST API
│   ├── orchestrator_agent.py  # 토론 로직
│   ├── config.py           # 설정
│   ├── agents.json         # 등록된 에이전트 목록
│   └── requirements.txt
│
├── agent/                  # 각 Mac에서 실행
│   ├── server.py           # A2A 서버
│   ├── claude_agent.py     # Claude Agent SDK 연동
│   ├── config.py           # 설정
│   ├── .env.example        # 환경변수 예시
│   ├── data/               # 로컬 데이터 (에이전트가 참고)
│   └── requirements.txt
│
├── tunnel/
│   ├── setup_tunnel.sh         # 터널 단독 실행
│   └── start_agent_with_tunnel.sh  # 에이전트 + 터널 동시 실행
│
├── scripts/
│   ├── install_gcp.sh      # GCP 자동 설치
│   ├── install_agent.sh    # Mac 자동 설치
│   ├── register_agent.sh   # 에이전트 수동 등록
│   └── test_system.sh      # 시스템 테스트
│
└── docs/
    ├── INSTALL.md          # 설치 가이드
    ├── SETUP.md            # 세팅 가이드
    └── IMPLEMENTATION.md   # 구현 가이드
```

---

## REST API

오케스트레이터 제공 API:

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/.well-known/agent.json` | Agent Card |
| POST | `/debate` | 토론 시작 |
| GET | `/agents` | 등록된 에이전트 목록 |
| POST | `/agents/register` | 에이전트 등록 |
| POST | `/` | A2A JSON-RPC 엔드포인트 |

---

## 확장 로드맵

```
  토론/질문 ──저장──▶ ① Knowledge Base ──조회──▶ 토론 context
      │                    │
      │              활동 이력 제공
      │                    ▼
      │            ③ Skill Analyzer → 스킬 자동 업데이트
      │                    │
      └──▶ ② Stable Registry ◀── 더 정확한 스킬 매칭
             (영속 저장, heartbeat)
```

| 순위 | 기능 | 설명 |
|------|------|------|
| 1 | **Knowledge Base** | 토론/질문 결과를 Vector DB + Document DB에 축적하여 시맨틱 검색 가능한 지식 저장소 구축 |
| 2 | **안정성 강화** | InMemory → SQLite/Redis 영속 저장, 에이전트 heartbeat, 부분 실패 허용 |
| 3 | **자동 스킬 재정의** | 에이전트의 활동 이력(참여 토론, 답변 내용, 로컬 데이터)을 분석하여 스킬 프로파일 자동 갱신 |

> 자세한 설계는 [구현 가이드 - 확장 로드맵](docs/IMPLEMENTATION.md#확장-로드맵) 참조

---

## 문서

- [설치 가이드](docs/INSTALL.md)
- [세팅 가이드](docs/SETUP.md)
- [구현 가이드](docs/IMPLEMENTATION.md)

---

## 요구사항

| 항목 | 버전 |
|------|------|
| Python | 3.11+ |
| Node.js | 18 LTS+ |
| Claude Code CLI | 최신 (구독 필요) |
| cloudflared | 최신 |
| a2a-sdk | 0.2.0+ |
| claude-agent-sdk | 0.1.0+ |
