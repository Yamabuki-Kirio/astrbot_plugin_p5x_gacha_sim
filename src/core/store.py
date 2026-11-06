"""SQLite 持久化：保底状态、抽卡记录、个人默认卡池。

只用标准库 ``sqlite3``；所有写入串行化在一把锁后面，避免 AstrBot 多线程调度时
出现 ``database is locked``。
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Iterable, Sequence

from .models import PityState
from .collection import collectible

SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_items (
    platform_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    item_name TEXT NOT NULL,
    rarity INTEGER NOT NULL CHECK(rarity IN (4,5)),
    kind TEXT NOT NULL CHECK(kind IN ('character','weapon')),
    copies INTEGER NOT NULL CHECK(copies BETWEEN 1 AND 7),
    PRIMARY KEY(platform_id,user_id,item_id)
);
CREATE TABLE IF NOT EXISTS plugin_migrations (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS daily_quota (
    platform_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    day TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0 CHECK(used >= 0),
    bonus INTEGER NOT NULL DEFAULT 0 CHECK(bonus >= 0),
    signed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(platform_id, user_id)
);

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
        self._transaction_depth = 0
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._commit()

    def bootstrap_collection(self, items):
        """Once-only import from existing histories. Old excess copies do not grant retroactive currency."""
        with self.transaction():
            if self._conn.execute("SELECT 1 FROM plugin_migrations WHERE name='collection_history_v1'").fetchone():
                return
            rows = self._conn.execute(
                "SELECT platform_id,user_id,item_id,COUNT(*) AS n FROM pull_history "
                "WHERE rarity IN (4,5) AND (item_id LIKE 'char:%' OR item_id LIKE 'weapon:%') "
                "GROUP BY platform_id,user_id,item_id").fetchall()
            for row in rows:
                item = items.get(row['item_id'])
                if not item or not collectible(item):
                    continue
                kind = 'character' if item.id.startswith('char:') else 'weapon'
                self._conn.execute(
                    "INSERT OR IGNORE INTO collection_items VALUES(?,?,?,?,?,?,?)",
                    (row['platform_id'],row['user_id'],item.id,item.name,item.rarity,kind,min(7,row['n'])))
            self._conn.execute("INSERT INTO plugin_migrations VALUES('collection_history_v1')")

    def add_owned(self, platform_id, user_id, item):
        """Return True only for a copy obtained after the seven-copy cap."""
        if not collectible(item):
            return False
        with self.transaction():
            previous = self._conn.execute(
                "SELECT copies FROM collection_items WHERE platform_id=? AND user_id=? AND item_id=?",
                (platform_id,user_id,item.id)).fetchone()
            copies = previous['copies'] if previous else 0
            self._conn.execute(
                "INSERT INTO collection_items VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(platform_id,user_id,item_id) DO UPDATE SET "
                "copies=excluded.copies,item_name=excluded.item_name,rarity=excluded.rarity,kind=excluded.kind",
                (platform_id,user_id,item.id,item.name,item.rarity,
                 'character' if item.id.startswith('char:') else 'weapon',min(7,copies+1)))
            return copies >= 7

    def owned_items(self, platform_id, user_id):
        with self._lock:
            return self._conn.execute(
                "SELECT * FROM collection_items WHERE platform_id=? AND user_id=? ORDER BY item_id",
                (platform_id,user_id)).fetchall()

    def _commit(self):
        if not self._transaction_depth:
            self._conn.commit()

    @contextmanager
    def transaction(self):
        """同一事务保存额度、保底与历史；多连接竞争由 SQLite 写锁串行化。"""
        with self._lock:
            outer = self._transaction_depth == 0
            if outer:
                self._conn.execute("BEGIN IMMEDIATE")
            self._transaction_depth += 1
            try:
                yield
                if outer:
                    self._conn.commit()
            except BaseException:
                if outer:
                    self._conn.rollback()
                raise
            finally:
                self._transaction_depth -= 1

    def daily_status(self, platform_id, user_id, day):
        """按北京时间日期惰性刷新，不依赖后台定时器或进程持续运行。"""
        with self.transaction():
            self._conn.execute(
                "INSERT INTO daily_quota(platform_id,user_id,day) VALUES(?,?,?) "
                "ON CONFLICT(platform_id,user_id) DO UPDATE SET "
                "day=excluded.day, used=0, bonus=0, signed=0 WHERE daily_quota.day != excluded.day",
                (platform_id,user_id,day))
            row = self._conn.execute(
                "SELECT day,used,bonus,signed FROM daily_quota WHERE platform_id=? AND user_id=?",
                (platform_id,user_id)).fetchone()
            return dict(row)

    def save_daily(self, platform_id, user_id, day, used, bonus, signed):
        with self.transaction():
            self._conn.execute(
                "UPDATE daily_quota SET used=?,bonus=?,signed=? WHERE platform_id=? AND user_id=? AND day=?",
                (used,bonus,int(signed),platform_id,user_id,day))

    def refresh_daily_all(self, day, amount=10, base=10):
        """给所有已登记用户的当日余额加额；过期行先刷新至当天基础状态。"""
        with self.transaction():
            self._conn.execute(
                "INSERT INTO daily_quota(platform_id,user_id,day) "
                "SELECT platform_id,user_id,? FROM ("
                "SELECT platform_id,user_id FROM daily_quota UNION "
                "SELECT platform_id,user_id FROM pity_state UNION "
                "SELECT platform_id,user_id FROM user_pref UNION "
                "SELECT platform_id,user_id FROM collection_items UNION "
                "SELECT platform_id,user_id FROM pull_history) WHERE 1 "
                "ON CONFLICT(platform_id,user_id) DO UPDATE SET "
                "day=excluded.day,used=0,bonus=0,signed=0 WHERE daily_quota.day != excluded.day",
                (day,))
            cursor = self._conn.execute(
                "UPDATE daily_quota SET bonus=MAX(bonus,used-?)+? WHERE day=?", (base,amount,day))
            return cursor.rowcount

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

    def total_pulls(self, platform_id: str, user_id: str) -> int:
        """跨卡池累计实际抽数，不包含自选赠送，也不依赖历史开关。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT state_json FROM pity_state WHERE platform_id=? AND user_id=?",
                (platform_id, user_id),
            ).fetchall()
        return sum(PityState.from_dict(json.loads(row["state_json"])).pulls for row in rows)

    def save_state(self, platform_id: str, user_id: str, group_id: str, state: PityState) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO pity_state (platform_id, user_id, group_id, state_json, updated_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(platform_id, user_id, group_id)"
                " DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at",
                (platform_id, user_id, group_id, json.dumps(state.to_dict(), ensure_ascii=False), time.time()),
            )
            self._commit()

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
            self._commit()

    def history(
        self,
        platform_id: str,
        user_id: str,
        limit: int = 10,
        offset: int = 0,
        banner_id: str | None = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM pull_history WHERE platform_id=? AND user_id=? AND rarity IN (4,5) AND (item_id LIKE 'char:%' OR item_id LIKE 'weapon:%')"
        params: list = [platform_id, user_id]
        if banner_id:
            sql += " AND banner_id=?"
            params.append(banner_id)
        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def count_history(self, platform_id: str, user_id: str, banner_id: str | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM pull_history WHERE platform_id=? AND user_id=? AND rarity IN (4,5) AND (item_id LIKE 'char:%' OR item_id LIKE 'weapon:%')"
        params: list = [platform_id, user_id]
        if banner_id:
            sql += " AND banner_id=?"
            params.append(banner_id)
        with self._lock:
            return int(self._conn.execute(sql, params).fetchone()["n"])

    def rarity_summary(self, platform_id: str, user_id: str, banner_id: str | None = None) -> dict[int, int]:
        sql = "SELECT rarity, COUNT(*) AS n FROM pull_history WHERE platform_id=? AND user_id=? AND rarity IN (4,5) AND (item_id LIKE 'char:%' OR item_id LIKE 'weapon:%')"
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
            self._commit()

    # ------------------------------------------------------------------
    def clear_user(self, platform_id: str, user_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM pity_state WHERE platform_id=? AND user_id=?", (platform_id, user_id)
            )
            self._conn.execute(
                "DELETE FROM pull_history WHERE platform_id=? AND user_id=?", (platform_id, user_id)
            )
            self._conn.execute("DELETE FROM collection_items WHERE platform_id=? AND user_id=?", (platform_id,user_id))
            self._conn.execute("DELETE FROM daily_quota WHERE platform_id=? AND user_id=?", (platform_id,user_id))
            self._conn.execute(
                "DELETE FROM user_pref WHERE platform_id=? AND user_id=?", (platform_id, user_id)
            )
            self._commit()

    def leaderboard(self, platform_id: str, limit: int = 10) -> Sequence[sqlite3.Row]:
        """按 5★ 数量排名，用来做群内晒卡榜。"""
        with self._lock:
            return self._conn.execute(
                "SELECT user_id, COUNT(*) AS n FROM pull_history"
                " WHERE platform_id=? AND rarity=5 GROUP BY user_id ORDER BY n DESC LIMIT ?",
                (platform_id, limit),
            ).fetchall()
