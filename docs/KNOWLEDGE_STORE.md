# 지식 저장소 아키텍처

## 1. 개요

### 문제
토론 결과가 `.md` 파일로만 저장되어 다음 토론에 활용되지 않음. 동일 주제가 반복되면 매번 처음부터 시작하고, 과거 합의 사항이 무시됨.

### 해결
SQLite 기반 지식 저장소를 도입하여:
- 토론 결과를 **정규화된 토픽** 단위로 관리
- **동일 주제 재토론 시 기존 보고서를 자동 대체** (버전 관리)
- **새 토론 시작 시 관련 과거 보고서를 자동 참조** (FTS5 검색)
- Claude가 토픽 정규화 + 검색 키워드 추출을 담당

---

## 2. 전체 흐름

```
사용자 입력: "우리 팀에서 API 게이트웨이를 도입해야 할까요?"
                │
                ▼
        ┌──────────────────┐
        │  토픽 정규화       │  ← Claude 호출
        │  (normalize_topic) │
        └──────┬───────────┘
               │
               ▼
    normalized: "API 게이트웨이 도입"
    keywords: ["API", "게이트웨이", "마이크로서비스", "인프라"]
               │
               ├───────────────────────────────────────┐
               ▼                                       ▼
    ┌───────────────────┐               ┌──────────────────────┐
    │ 동일 토픽 확인      │               │  검색 키워드 추출      │
    │ find_by_normalized │               │  (extract_search_     │
    │ _topic()           │               │   keywords)           │
    └──────┬────────────┘               └──────┬───────────────┘
           │                                    │
           │ 기존 v2 발견                        ▼
           │                          ┌──────────────────┐
           │                          │ FTS5 검색         │
           │                          │ (latest만 반환)   │
           │                          └──────┬───────────┘
           │                                 │
           │                                 ▼
           │                          관련 과거 보고서 3건
           │                                 │
           ▼                                 ▼
    ┌─────────────────────────────────────────────────┐
    │              토론 진행                             │
    │                                                   │
    │  에이전트들에게 전달:                               │
    │  "주제: API 게이트웨이 도입해야 할까요?"            │
    │  "과거 관련 토론 참고:                              │
    │    [2026-04-05] API 게이트웨이 도입 (v2)           │
    │    결론: Istio로 최종 결정..."                      │
    │                                                   │
    └──────────────────────┬──────────────────────────┘
                           │
                           ▼
                    토론 완료, 보고서 생성
                           │
                           ▼
                ┌──────────────────────┐
                │ 지식 저장소 저장        │
                │                        │
                │ normalized_topic =     │
                │   "API 게이트웨이 도입" │
                │ version = 3            │
                │ status = "latest"      │
                │                        │
                │ 기존 v2 →              │
                │   status = "superseded"│
                └────────────────────────┘
```

---

## 3. 토픽 정규화 (Topic Normalization)

### 왜 필요한가

사용자 입력은 매번 다르지만 같은 주제일 수 있음:
```
"API 게이트웨이를 도입해야 할까요?"
"API 게이트웨이 도입 관련 추가 논의"
"게이트웨이 아키텍처 결정"
→ 모두 "API 게이트웨이 도입" 으로 정규화
```

### 동작

```python
async def normalize_topic(topic: str) -> Dict:
    """Claude에게 요청하여 정규화된 토픽과 키워드를 추출"""
    # Claude 응답:
    # {
    #   "normalized": "API 게이트웨이 도입",
    #   "keywords": ["API", "게이트웨이", "마이크로서비스", "인프라"]
    # }
```

- **normalized**: 동일 주제는 항상 같은 문자열로 매핑 (명사형, 간결)
- **keywords**: 관련 검색어 3~7개 (유의어, 상위 개념 포함)

### Claude 프롬프트

```
사용자 입력에서 핵심 토픽과 검색 키워드를 추출하세요.
규칙:
- normalized: 동일 주제는 항상 같은 문자열이 되도록 일관성 유지
- keywords: 토픽과 관련된 핵심 단어 3~7개, 유의어/상위 개념 포함
```

---

## 4. 검색 키워드 추출 (Search Keyword Extraction)

### 왜 필요한가

사용자 질문이 항상 직접적이지 않음:
```
"어제 얘기했던 거 결론이 뭐였지?"     → 검색 불가
"아키텍처 관련 합의 사항 정리해줘"     → "아키텍처" 하나로는 부정확
```

### 동작

```python
async def extract_search_keywords(user_input: str) -> str:
    """Claude에게 요청하여 FTS 검색용 키워드를 추출"""
    # 입력: "어제 얘기했던 아키텍처 관련 결론"
    # 출력: "아키텍처 마이크로서비스 API 게이트웨이"
```

---

## 5. 버전 관리 (Supersede)

### DB 스키마

```sql
CREATE TABLE reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,              -- 원본 사용자 입력
    normalized_topic TEXT NOT NULL,   -- Claude가 정규화한 토픽
    mode TEXT DEFAULT 'debate',
    agents TEXT DEFAULT '',
    report TEXT NOT NULL,
    report_path TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    keywords TEXT DEFAULT '',         -- Claude가 추출한 키워드
    version INTEGER DEFAULT 1,        -- 버전 번호
    status TEXT DEFAULT 'latest',     -- 'latest' | 'superseded'
    created_at TEXT NOT NULL
);
```

### 저장 흐름

```
save_report(normalized_topic="API 게이트웨이 도입"):

1. SELECT ... WHERE normalized_topic = "API 게이트웨이 도입" AND status = "latest"

2-A. 기존 없음:
     → INSERT (version=1, status="latest")

2-B. 기존 있음 (id=5, version=2):
     → UPDATE id=5 SET status="superseded"
     → INSERT (version=3, status="latest")
```

### 검색 흐름

```
search_reports("게이트웨이"):

SELECT ... FROM reports_fts JOIN reports
WHERE reports_fts MATCH "게이트웨이"
  AND reports.status = "latest"     ← superseded 제외
ORDER BY rank
LIMIT 5
```

### 이력 조회

```
get_topic_history("API 게이트웨이 도입"):

v3 [latest]      2026-04-10  "Envoy 도입으로 최종 결정"
v2 [superseded]  2026-04-08  "Istio로 변경"
v1 [superseded]  2026-04-05  "Kong 추천"
```

---

## 6. 데이터 흐름 종합

```
토론 시작
  ├── 1. normalize_topic(user_input)
  │     → normalized_topic, keywords
  │
  ├── 2. find_by_normalized_topic(normalized_topic)
  │     → 기존 보고서 있으면 "v2 있음, supersede 예정" 로그
  │
  ├── 3. extract_search_keywords(user_input)
  │     → FTS 검색 키워드
  │
  ├── 4. search_reports(keywords, latest_only=True)
  │     → 관련 과거 보고서 (최신 버전만)
  │
  ├── 5. 에이전트에게 과거 컨텍스트 + 주제 전달
  │     → 토론 진행
  │
  ├── 6. 보고서 생성
  │
  └── 7. save_report(normalized_topic=..., keywords=...)
        → 기존 latest → superseded
        → 신규 latest (version+1)
```

---

## 7. 계층형 구조에서의 지식 저장소

각 오케스트레이터가 독립된 지식 저장소를 가짐:

```
Meta-Orchestrator
  └── knowledge.db (팀 간 종합 토론 결과)

Sub-Orchestrator A
  └── knowledge.db (팀 A 내부 토론 결과)

Sub-Orchestrator B
  └── knowledge.db (팀 B 내부 토론 결과)
```

- **팀 내부 토론**: Sub-Orchestrator의 knowledge.db에 저장/검색
- **팀 간 토론**: Meta-Orchestrator의 knowledge.db에 저장/검색
- 교차 참조 없음 (각 수준의 독립성 보장)

---

## 8. API

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /knowledge/stats` | 저장소 활성화 여부, 보고서 수 |
| `GET /knowledge/search?q=키워드&limit=5` | FTS5 검색 (latest만) |

---

## 9. 파일 구조

```
orchestrator/
  ├── knowledge_store.py   # SQLite 지식 저장소 (버전 관리, FTS5)
  ├── orchestrator_agent.py # normalize_topic(), extract_search_keywords()
  ├── server.py             # 저장소 초기화, API 라우팅
  └── reports/
       ├── knowledge.db     # SQLite DB 파일
       ├── report_*.md      # 마크다운 보고서 (기존 호환)
       └── query_*.md
```

---

## 10. 제약사항 및 향후 개선

| 항목 | 현재 | 향후 |
|------|------|------|
| **토픽 정규화 정확도** | Claude 의존 (간혹 불일치 가능) | 임베딩 기반 유사도로 보완 |
| **검색 방식** | FTS5 키워드 매칭 | 벡터DB 의미 검색 추가 (하이브리드) |
| **교차 참조** | 계층 간 독립 | 상위가 하위 지식도 검색 가능하게 |
| **보고서 크기** | 전문 저장 | 요약본 별도 저장으로 검색 성능 개선 |
| **동시성** | SQLite WAL 모드 | 대규모 시 PostgreSQL 전환 |
