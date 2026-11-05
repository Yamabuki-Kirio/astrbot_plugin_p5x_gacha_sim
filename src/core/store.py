"""SQLite 持久化：保底状态、抽卡记录、个人默认卡池。

只用标准库 ``sqlite3``；所有写入串行化在一把锁后面，避免 AstrBot 多线程调度时
出现 ``database is locked``。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Sequence

from .models import PityState

SCHEMA = """
CREATE TABLE IF NOT EXISTS pity_state (
    platform_id TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    group_id    TEXT NOT NULL,
    state_json  TEXT NOT NULL,
    updated_at  REAL NOT NULL,
    PRIMARY KEY (platform_id, user_id, group_id)
);

CREATE TABLE IF NOT EXISTS pull_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    platform_id TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    banner_id   TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    item_name   TEXT NOT NULL,
    rarity      INTEGER NOT NULL,
    is_up       INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_user ON pull_history (platform_id, user_id, id DESC);

CREATE TABLE IF NOT EXISTS user_pref (
    platform_id TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    banner_id   TEXT NOT NULL,
    PRIMARY KEY (platform_id, user_id)
);
"""


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # 保底状态
    # ------------------------------------------------------------------
    def load_state(self, platform_id: str, user_id: str, group_id: str) -> PityState:
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM pity_state WHERE platform_id=? AND user_id=? AND group_id=?",
                (platform_id, user_id, group_id),
            ).fetchone()
        return PityState.from_dict(json.loads(row["state_json"])) if row else PityState()

    def save_state(self, platform_id: str, user_id: str, group_id: str, state: PityState) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO pity_state (platform_id, user_id, group_id, state_json, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(platform_id, user_id, group_id)"
                " DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at",
                (platform_id, user_id, group_id, json.dumps(state.to_dict(), ensure_ascii=False), time.time()),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # 历史
    # ------------------------------------------------------------------
    def add_history(
        self,
        platform_id: str,
        user_id: str,
        banner_id: str,
        rows: Iterable[tuple[str, str, int, bool]],
    ) -> None:
        now = time.time()
        with self._lock:
            self._conn.executemany(
                "INSERT INTO pull_history (platform_id, user_id, banner_id, item_id, item_name, rarity, is_up, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (platform_id, user_id, banner_id, item_id, name, rarity, int(is_up), now)
                    for item_id, name, rarity, is_up in rows
                ],
            )
            self._conn.commit()

    def history(
        self,
        platform_id: str,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
        banner_id: str | None = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM pull_history WHERE platform_id=? AND user_id=?"
        params: list = [platform_id, user_id]
        if banner_id:
            sql += " AND banner_id=?"
            params.append(banner_id)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def count_history(self, platform_id: str, user_id: str, banner_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM pull_history WHERE platform_id=? AND user_id=?"
        params: list = [platform_id, user_id]
        if banner_id:
            sql += " AND banner_id=?"
            params.append(banner_id)
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()["n"])

    def rarity_summary(self, platform_id: str, user_id: str, banner_id: str | None = None) -> dict[int, int]:
        sql = "SELECT rarity, COUNT(*) AS n FROM pull_history WHERE platform_id=? AND user_id=?"
        params: list = [platform_id, user_id]
        if banner_id:
            sql += " AND banner_id=?"
            params.append(banner_id)
        sql += " GROUP BY rarity"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return {int(row["rarity"]): int(row["n"]) for row in rows}

    def recent_five_stars(self, platform_id: str, user_id: str, limit: int = 5) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM pull_history WHERE platform_id=? AND user_id=? AND rarity=5"
                " ORDER BY id DESC LIMIT ?",
                (platform_id, user_id, limit),
            ).fetchall()

    # ------------------------------------------------------------------
    # 个人默认卡池
    # ------------------------------------------------------------------
    def get_default_banner(self, platform_id: str, user_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT banner_id FROM user_pref WHERE platform_id=? AND user_id=?",
                (platform_id, user_id),
            ).fetchone()
        return row["banner_id"] if row else None

    def set_default_banner(self, platform_id: str, user_id: str, banner_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO user_pref (platform_id, user_id, banner_id) VALUES (?, ?, ?)"
                " ON CONFLICT(platform_id, user_id) DO UPDATE SET banner_id=excluded.banner_id",
                (platform_id, user_id, banner_id),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    def clear_user(self, platform_id: str, user_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM pity_state WHERE platform_id=? AND user_id=?", (platform_id, user_id)
            )
            self._conn.execute(
                "DELETE FROM pull_history WHERE platform_id=? AND user_id=?", (platform_id, user_id)
            )
            self._conn.execute(
                "DELETE FROM user_pref WHERE platform_id=? AND user_id=?", (platform_id, user_id)
            )
            self._conn.commit()

    def leaderboard(self, platform_id: str, limit: int = 10) -> Sequence[sqlite3.Row]:
        """按 5★ 数量排名，用来做群内晒卡榜。"""
        with self._lock:
            return self._conn.execute(
                "SELECT user_id, COUNT(*) AS n FROM pull_history"
                " WHERE platform_id=? AND rarity=5 GROUP BY user_id ORDER BY n DESC LIMIT ?",
                (platform_id, limit),
            ).fetchall()
