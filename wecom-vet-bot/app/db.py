"""SQLite 单文件存储。

messages 表承担两件事：
1. 幂等——msg_id UNIQUE，插入冲突即视为企业微信重试，跳过；
2. 全链路日志——B 线落 reply/latency/status，retrieval/prompt/guardrail/token
   四个字段给 C/D 线预留，保证一条消息的完整处理过程可回放。

低并发场景（诊所客服），每次操作独立短连接 + WAL，不共享连接、无锁状态。
"""

import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    msg_id           TEXT NOT NULL UNIQUE,
    from_user        TEXT NOT NULL,
    msg_type         TEXT NOT NULL,
    content          TEXT,
    wecom_create_time INTEGER,
    status           TEXT NOT NULL DEFAULT 'received',
    reply            TEXT,
    error            TEXT,
    latency_ms       INTEGER,
    retrieval_json   TEXT,
    prompt           TEXT,
    guardrail_json   TEXT,
    token_usage_json TEXT,
    received_at      TEXT NOT NULL,
    done_at          TEXT
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: str) -> None:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)


def insert_message_if_new(
    db_path: str,
    msg_id: str,
    from_user: str,
    msg_type: str,
    content,
    wecom_create_time,
) -> bool:
    """幂等入口：新消息返回 True；msg_id 已存在（重试）返回 False。"""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO messages"
            " (msg_id, from_user, msg_type, content, wecom_create_time, status, received_at)"
            " VALUES (?, ?, ?, ?, ?, 'received', ?)",
            (msg_id, from_user, msg_type, content, wecom_create_time, _utcnow()),
        )
        return cur.rowcount == 1


def mark_done(db_path: str, msg_id: str, reply: str, latency_ms: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE messages SET status='done', reply=?, latency_ms=?, done_at=?"
            " WHERE msg_id=?",
            (reply, latency_ms, _utcnow(), msg_id),
        )


def mark_failed(db_path: str, msg_id: str, error: str, latency_ms: int) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE messages SET status='failed', error=?, latency_ms=?, done_at=?"
            " WHERE msg_id=?",
            (error, latency_ms, _utcnow(), msg_id),
        )


def mark_skipped(db_path: str, msg_id: str, reason: str) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE messages SET status='skipped', error=?, done_at=? WHERE msg_id=?",
            (reason, _utcnow(), msg_id),
        )


def fetch_unfinished(db_path: str) -> list:
    """进程重启后把 status='received' 的消息重新入队，避免确认了却没回。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT msg_id, from_user, msg_type, content FROM messages"
            " WHERE status='received' ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
