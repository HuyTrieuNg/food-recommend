"""SQLite lưu user mới tạo + rating nhập từ giao diện demo."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

NEW_USER_ID_START = 900_000_000  # tránh trùng user_id của Foody


class Store:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock, self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ratings (
                    user_id INTEGER NOT NULL,
                    place_id INTEGER NOT NULL,
                    rating REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, place_id)
                );
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_user(self, name: str) -> dict:
        with self.lock, self.conn:
            (max_id,) = self.conn.execute("SELECT COALESCE(MAX(id), ?) FROM users", (NEW_USER_ID_START,)).fetchone()
            uid = max_id + 1
            self.conn.execute("INSERT INTO users VALUES (?, ?, ?)", (uid, name, self._now()))
        return {"id": uid, "name": name}

    def users(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                """SELECT u.id, u.name, COUNT(r.place_id) AS n
                   FROM users u LEFT JOIN ratings r ON r.user_id = u.id
                   GROUP BY u.id ORDER BY u.id DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_user(self, uid: int) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT id, name FROM users WHERE id = ?", (uid,)).fetchone()
        return dict(row) if row else None

    def ratings(self, uid: int) -> dict[int, float]:
        with self.lock:
            rows = self.conn.execute("SELECT place_id, rating FROM ratings WHERE user_id = ?", (uid,)).fetchall()
        return {r["place_id"]: r["rating"] for r in rows}

    def set_rating(self, uid: int, place_id: int, rating: float) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                """INSERT INTO ratings VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, place_id) DO UPDATE SET rating = excluded.rating,
                   created_at = excluded.created_at""",
                (uid, place_id, rating, self._now()),
            )

    def delete_rating(self, uid: int, place_id: int) -> bool:
        with self.lock, self.conn:
            cur = self.conn.execute("DELETE FROM ratings WHERE user_id = ? AND place_id = ?", (uid, place_id))
        return cur.rowcount > 0
