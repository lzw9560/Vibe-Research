# -*- coding: utf-8 -*-
"""投研记录笔记落库（全局可见，跨设备同步）。

表 notes：id/kind/title/content/ts，按 ts 降序。
与 workflow_state 同库（market_data.db），连接模式平行
（busy_timeout=30000 + WAL）。

接线：
- 前端 Note.ts 旧用 localStorage（vr-notes key，"数据只存本地不上传"），
  本 repo 切换为后端 SQLite 落盘，笔记全局可见、跨设备同步。
- id 格式 ``{timestamp_ms}-{random5}``，ts 毫秒时间戳，与前端 Note.ts 格式一致。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from typing import Any, Dict, List

logger = logging.getLogger("vibe-research")

_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "market_data.db"
)


def _get_conn() -> sqlite3.Connection:
    """连接 market_data.db，连接级 busy_timeout + WAL（与 workflow_state_repo 平行）。"""
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _ensure_table() -> None:
    """建 notes 表（幂等，已有则不动）。"""
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                ts INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_ts ON notes(ts)")
        conn.commit()
    finally:
        conn.close()


# 模块导入时建表（与 workflow_state_repo._ensure_tables() 模式一致）
_ensure_table()


def list_notes(limit: int = 200) -> List[Dict[str, Any]]:
    """列出笔记（按 ts 降序，默认 200 条）。

    Args:
        limit: 返回条数上限。

    Returns:
        list[dict]，每项含 id/kind/title/content/ts。
    """
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT id, kind, title, content, ts FROM notes ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {"id": r[0], "kind": r[1], "title": r[2], "content": r[3], "ts": r[4]}
        for r in rows
    ]


def add_note(kind: str, title: str, content: str) -> Dict[str, Any]:
    """新增笔记。

    Args:
        kind: 笔记类型（复盘/观察/计划等）。
        title: 标题。
        content: 正文。

    Returns:
        新笔记 dict（含生成的 id 和 ts）。
    """
    note = {
        "id": f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:5]}",
        "kind": kind,
        "title": title,
        "content": content,
        "ts": int(time.time() * 1000),
    }
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT INTO notes (id, kind, title, content, ts) VALUES (?, ?, ?, ?, ?)",
            (note["id"], note["kind"], note["title"], note["content"], note["ts"]),
        )
        conn.commit()
    finally:
        conn.close()
    return note


def delete_note(note_id: str) -> bool:
    """删除单条笔记。

    Args:
        note_id: 笔记 id。

    Returns:
        是否删除（rowcount > 0）。不存在 → False。
    """
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_notes() -> int:
    """清空全部笔记。

    Returns:
        删除条数。
    """
    conn = _get_conn()
    try:
        cur = conn.execute("DELETE FROM notes")
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
