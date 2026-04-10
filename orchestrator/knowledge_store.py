"""
SQLite 기반 지식 저장소
- 토론/질의 보고서 메타데이터 및 전문 저장
- FTS5 기반 전문 검색
- 정규화된 토픽 기반 버전 관리 (supersede)
- 에이전트 등록 영속화
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class KnowledgeStore:
    def __init__(self, db_path: str = "./knowledge.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_tables()

    def _init_tables(self):
        cur = self.conn.cursor()

        # 보고서 테이블 (버전 관리 포함)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                normalized_topic TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL DEFAULT 'debate',
                agents TEXT DEFAULT '',
                report TEXT NOT NULL,
                report_path TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                keywords TEXT DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'latest',
                created_at TEXT NOT NULL
            )
        """)

        # normalized_topic 인덱스 (동일 주제 검색용)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_reports_normalized_topic
            ON reports(normalized_topic, status)
        """)

        # FTS5 전문 검색 인덱스
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(
                topic, normalized_topic, report, tags, keywords,
                content='reports',
                content_rowid='id'
            )
        """)

        # FTS 자동 동기화 트리거
        cur.executescript("""
            CREATE TRIGGER IF NOT EXISTS reports_ai AFTER INSERT ON reports BEGIN
                INSERT INTO reports_fts(rowid, topic, normalized_topic, report, tags, keywords)
                VALUES (new.id, new.topic, new.normalized_topic, new.report, new.tags, new.keywords);
            END;
            CREATE TRIGGER IF NOT EXISTS reports_ad AFTER DELETE ON reports BEGIN
                INSERT INTO reports_fts(reports_fts, rowid, topic, normalized_topic, report, tags, keywords)
                VALUES ('delete', old.id, old.topic, old.normalized_topic, old.report, old.tags, old.keywords);
            END;
            CREATE TRIGGER IF NOT EXISTS reports_au AFTER UPDATE ON reports BEGIN
                INSERT INTO reports_fts(reports_fts, rowid, topic, normalized_topic, report, tags, keywords)
                VALUES ('delete', old.id, old.topic, old.normalized_topic, old.report, old.tags, old.keywords);
                INSERT INTO reports_fts(rowid, topic, normalized_topic, report, tags, keywords)
                VALUES (new.id, new.topic, new.normalized_topic, new.report, new.tags, new.keywords);
            END;
        """)

        # 에이전트 등록 테이블
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                name TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                description TEXT DEFAULT '',
                skills TEXT DEFAULT '[]',
                data_paths TEXT DEFAULT '[]',
                mcp_servers TEXT DEFAULT '[]',
                agent_type TEXT DEFAULT 'agent',
                alias TEXT DEFAULT '',
                last_seen TEXT,
                created_at TEXT NOT NULL
            )
        """)

        self.conn.commit()

    # ──────────────────────────────────────
    # 보고서 저장 (버전 관리 포함)
    # ──────────────────────────────────────

    def save_report(
        self,
        topic: str,
        report: str,
        normalized_topic: str = "",
        mode: str = "debate",
        agents: Optional[List[str]] = None,
        report_path: str = "",
        tags: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ) -> int:
        """보고서를 저장합니다.
        normalized_topic이 같은 기존 보고서가 있으면 supersede 처리합니다.
        """
        norm = normalized_topic or topic

        # 동일 정규화 토픽의 기존 latest 보고서 찾기
        existing = self.conn.execute(
            "SELECT id, version FROM reports WHERE normalized_topic = ? AND status = 'latest'",
            (norm,),
        ).fetchone()

        new_version = 1
        if existing:
            # 기존 보고서를 superseded로 변경
            self.conn.execute(
                "UPDATE reports SET status = 'superseded' WHERE id = ?",
                (existing["id"],),
            )
            new_version = existing["version"] + 1

        cur = self.conn.execute(
            """INSERT INTO reports
               (topic, normalized_topic, mode, agents, report, report_path, tags, keywords, version, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'latest', ?)""",
            (
                topic,
                norm,
                mode,
                ",".join(agents or []),
                report,
                report_path,
                ",".join(tags or []),
                ",".join(keywords or []),
                new_version,
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    # ──────────────────────────────────────
    # 보고서 검색 (latest만)
    # ──────────────────────────────────────

    def search_reports(self, query: str, limit: int = 5, include_superseded: bool = False) -> List[Dict]:
        """FTS5로 관련 보고서를 검색합니다. 기본적으로 latest만 반환합니다."""
        try:
            status_filter = "" if include_superseded else "AND r.status = 'latest'"
            rows = self.conn.execute(
                f"""SELECT r.id, r.topic, r.normalized_topic, r.mode, r.agents,
                           r.report, r.tags, r.keywords, r.version, r.status, r.created_at,
                           rank
                    FROM reports_fts fts
                    JOIN reports r ON r.id = fts.rowid
                    WHERE reports_fts MATCH ? {status_filter}
                    ORDER BY rank
                    LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def find_by_normalized_topic(self, normalized_topic: str) -> Optional[Dict]:
        """정규화된 토픽으로 최신(latest) 보고서를 찾습니다."""
        row = self.conn.execute(
            "SELECT * FROM reports WHERE normalized_topic = ? AND status = 'latest'",
            (normalized_topic,),
        ).fetchone()
        return dict(row) if row else None

    def get_topic_history(self, normalized_topic: str) -> List[Dict]:
        """특정 토픽의 전체 버전 이력을 반환합니다."""
        rows = self.conn.execute(
            "SELECT * FROM reports WHERE normalized_topic = ? ORDER BY version DESC",
            (normalized_topic,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_reports(self, limit: int = 20, include_superseded: bool = False) -> List[Dict]:
        """최근 보고서를 반환합니다."""
        status_filter = "" if include_superseded else "WHERE status = 'latest'"
        rows = self.conn.execute(
            f"SELECT * FROM reports {status_filter} ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_report(self, report_id: int) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_report_count(self, include_superseded: bool = False) -> int:
        status_filter = "" if include_superseded else "WHERE status = 'latest'"
        row = self.conn.execute(
            f"SELECT COUNT(*) as cnt FROM reports {status_filter}"
        ).fetchone()
        return row["cnt"]

    # ──────────────────────────────────────
    # 에이전트 등록 영속화
    # ──────────────────────────────────────

    def save_agent(
        self,
        name: str,
        url: str,
        description: str = "",
        skills: Optional[List[str]] = None,
        data_paths: Optional[List[str]] = None,
        mcp_servers: Optional[List[str]] = None,
        agent_type: str = "agent",
        alias: str = "",
    ) -> None:
        now = datetime.now().isoformat()
        self.conn.execute(
            """INSERT INTO agents (name, url, description, skills, data_paths, mcp_servers,
                                   agent_type, alias, last_seen, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   url=excluded.url,
                   description=excluded.description,
                   skills=excluded.skills,
                   data_paths=excluded.data_paths,
                   mcp_servers=excluded.mcp_servers,
                   agent_type=excluded.agent_type,
                   alias=excluded.alias,
                   last_seen=excluded.last_seen""",
            (
                name, url, description,
                json.dumps(skills or []),
                json.dumps(data_paths or []),
                json.dumps(mcp_servers or []),
                agent_type, alias, now, now,
            ),
        )
        self.conn.commit()

    def load_agents(self) -> List[Dict]:
        rows = self.conn.execute("SELECT * FROM agents ORDER BY name").fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["skills"] = json.loads(d["skills"])
            d["data_paths"] = json.loads(d["data_paths"])
            d["mcp_servers"] = json.loads(d["mcp_servers"])
            result.append(d)
        return result

    def delete_agent(self, name: str) -> bool:
        cur = self.conn.execute("DELETE FROM agents WHERE name = ?", (name,))
        self.conn.commit()
        return cur.rowcount > 0

    def update_agent_last_seen(self, name: str) -> None:
        self.conn.execute(
            "UPDATE agents SET last_seen = ? WHERE name = ?",
            (datetime.now().isoformat(), name),
        )
        self.conn.commit()

    # ──────────────────────────────────────
    # 정리
    # ──────────────────────────────────────

    def close(self):
        self.conn.close()
