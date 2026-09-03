import sqlite3
import json
import threading
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict

from config import config


@dataclass
class Meeting:
    id: str
    title: str
    transcript: str = ""
    summary: Optional[str] = None
    key_points: List[str] = field(default_factory=list)
    action_items: List[Dict] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    next_steps: List[str] = field(default_factory=list)
    sentiment: Optional[str] = None
    duration_seconds: int = 0
    source: str = "live"
    video_filename: Optional[str] = None
    raw_mom: Optional[str] = None
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


class Database:
    _init_lock = threading.Lock()

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.storage.DB_PATH
        self._local = threading.local()

    def _get_conn(self) -> sqlite3.Connection:
        conn_key = f"conn_{id(self)}"
        conn = getattr(self._local, conn_key, None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            setattr(self._local, conn_key, conn)
        return conn

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def init_db(self):
        with self._init_lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meetings (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    transcript TEXT DEFAULT '',
                    summary TEXT,
                    key_points TEXT DEFAULT '[]',
                    action_items TEXT DEFAULT '[]',
                    decisions TEXT DEFAULT '[]',
                    next_steps TEXT DEFAULT '[]',
                    sentiment TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'live',
                    video_filename TEXT,
                    raw_mom TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

    def create_meeting(self, meeting: Meeting) -> Meeting:
        with self._cursor() as cursor:
            cursor.execute("""
                INSERT INTO meetings (
                    id, title, transcript, summary, key_points, action_items,
                    decisions, next_steps, sentiment, duration_seconds, source,
                    video_filename, raw_mom, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                meeting.id,
                meeting.title,
                meeting.transcript,
                meeting.summary,
                json.dumps(meeting.key_points),
                json.dumps(meeting.action_items),
                json.dumps(meeting.decisions),
                json.dumps(meeting.next_steps),
                meeting.sentiment,
                meeting.duration_seconds,
                meeting.source,
                meeting.video_filename,
                meeting.raw_mom,
                meeting.status,
                meeting.created_at,
                meeting.updated_at,
            ))
        return meeting

    def get_meeting(self, meeting_id: str) -> Optional[Meeting]:
        with self._cursor() as cursor:
            cursor.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_meeting(row)

    def get_meetings(self, page: int = 1, per_page: int = 20) -> tuple[List[Meeting], int]:
        offset = (page - 1) * per_page
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM meetings")
            total = cursor.fetchone()[0]
            cursor.execute(
                "SELECT * FROM meetings ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (per_page, offset)
            )
            rows = cursor.fetchall()
            meetings = [self._row_to_meeting(row) for row in rows]
        return meetings, total

    def update_meeting(self, meeting: Meeting) -> Meeting:
        meeting.updated_at = datetime.utcnow().isoformat()
        with self._cursor() as cursor:
            cursor.execute("""
                UPDATE meetings SET
                    title=?, transcript=?, summary=?, key_points=?, action_items=?,
                    decisions=?, next_steps=?, sentiment=?, duration_seconds=?,
                    source=?, video_filename=?, raw_mom=?, status=?, updated_at=?
                WHERE id=?
            """, (
                meeting.title,
                meeting.transcript,
                meeting.summary,
                json.dumps(meeting.key_points),
                json.dumps(meeting.action_items),
                json.dumps(meeting.decisions),
                json.dumps(meeting.next_steps),
                meeting.sentiment,
                meeting.duration_seconds,
                meeting.source,
                meeting.video_filename,
                meeting.raw_mom,
                meeting.status,
                meeting.updated_at,
                meeting.id,
            ))
        return meeting

    def delete_meeting(self, meeting_id: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            return cursor.rowcount > 0

    def _row_to_meeting(self, row: sqlite3.Row) -> Meeting:
        return Meeting(
            id=row["id"],
            title=row["title"],
            transcript=row["transcript"] or "",
            summary=row["summary"],
            key_points=json.loads(row["key_points"] or "[]"),
            action_items=json.loads(row["action_items"] or "[]"),
            decisions=json.loads(row["decisions"] or "[]"),
            next_steps=json.loads(row["next_steps"] or "[]"),
            sentiment=row["sentiment"],
            duration_seconds=row["duration_seconds"] or 0,
            source=row["source"] or "live",
            video_filename=row["video_filename"],
            raw_mom=row["raw_mom"],
            status=row["status"] or "pending",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


db = Database()
db.init_db()
