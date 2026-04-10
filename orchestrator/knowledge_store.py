"""
SQLite 기반 지식 저장소
- 토론/질의 보고서 메타데이터 및 전문 저장
- FTS5 기반 전문 검색
- 에이전트 등록 영속화
"""
import json
import sqlite3
import os
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

        # 보고서 테이블
        cur.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'debate',
                agents TEXT DEFAULT '',
                report TEXT NOT NULL,
                report_path TEXT DEFAULT '',
                tags TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        # FTS5 전문 검색 인덱스
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS reports_fts USING fts5(
                topic, report, tags,
                content='reports',
                content_rowid='id'
            )
        """)

        # FTS 자동 동기화 트리거
        cur.executescript("""
            CREATE TRIGGER IF NOT EXISTS reports_ai AFTER INSERT ON reports BEGIN
                INSERT INTO reports_fts(rowid, topic, report, tags)
                VALUES (new.id, new.topic, new.report, new.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS reports_ad AFTER DELETE ON reports BEGIN
                INSERT INTO reports_fts(reports_fts, rowid, topic, report, tags)
                VALUES ('delete', old.id, old.topic, old.report, old.tags);
            END;
            CREATE TRIGGER IF NOT EXISTS reports_au AFTER UPDATE ON reports BEGIN
                INSERT INTO reports_fts(reports_fts, rowid, topic, report, tags)
                VALUES ('delete', old.id, old.topic, old.report, old.tags);
                INSERT INTO reports_fts(rowid, topic, report, tags)
                VALUES (new.id, new.topic, new.report, new.tags);
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
    # 보고서 저장/검색
    # ──────────────────────────────────────

    def save_report(
        self,
        topic: str,
        report: str,
        mode: str = "debate",
        agents: Optional[List[str]] = None,
        report_path: str = "",
        tags: Optional[List[str]] = None,
    ) -> int:
        """보고서를 저장하고 ID를 반환합니다."""
        cur = self.conn.execute(
            """INSERT INTO reports (topic, mode, agents, report, report_path, tags, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                topic,
                mode,
                ",".join(agents or []),
                report,
                report_path,
                ",".join(tags or []),
                datetime.now().isoformat(),
            ),
        )
        self.conn.commit()
        return cur.lastrowid

    def search_reports(self, query: str, limit: int = 5) -> List[Dict]:
        """FTS5로 관련 보고서를 검색합니다."""
        try:
            rows = self.conn.execute(
                """SELECT r.id, r.topic, r.mode, r.agents, r.report, r.tags, r.created_at,
                          rank
                   FROM reports_fts fts
                   JOIN reports r ON r.id = fts.rowid
                   WHERE reports_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def get_recent_reports(self, limit: int = 20) -> List[Dict]:
        """최근 보고서를 반환합니다."""
        rows = self.conn.execute(
            "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_report(self, report_id: int) -> Optional[Dict]:
        """ID로 보고서를 가져옵니다."""
        row = self.conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_report_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM reports").fetchone()
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
        """에이전트를 저장/업데이트합니다."""
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
        """저장된 에이전트 목록을 반환합니다."""
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
