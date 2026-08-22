# -*- coding: utf-8 -*-
"""S078 涨停历史 snapshot 数据地基。

每日盘后 snapshot `astock.em_zt_topic_pool` 终盘涨停池 → `zt_history` SQLite DB
（**不 prune，累积 indefinitely**）。涨停池历史 >1 月无可用源（em/ths/akshare 均 ~1 月），
本模块自建累积，供首板流 + 任何涨停类战法长窗 §44 复验。

工程底线：
- em_get 限流（`astock.em_zt_topic_pool` 已包熔断+代理，不裸调 requests）
- 私有 DB 在 `.vibe-research/zt_history.db`（`vr_paths.resolve_data_dir()`，不入 git）
- 缺字段填 None（不臆造，允许部分字段空）
- schema inline `CREATE TABLE IF NOT EXISTS`（fresh DB 首连建表，避开 migration 框架接线坑）

spec: `specs/S078-涨停历史snapshot数据地基/spec.md`
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime
from typing import Any

from vr_paths import resolve_data_dir

_logger = logging.getLogger(__name__)

_DB_PATH = resolve_data_dir() / "zt_history.db"
_DB_LOCK = threading.Lock()

_SCHEMA = """CREATE TABLE IF NOT EXISTS zt_history (
    date TEXT NOT NULL,          -- YYYY-MM-DD（首板日/涨停日）
    code TEXT NOT NULL,          -- 6 位代码
    name TEXT,
    lbc INTEGER,                 -- 连板数（1=首板）
    zbc REAL,                    -- 炸板次数
    fbt REAL,                    -- 首封时间
    fund REAL,                   -- 封单额
    zje REAL,                    -- 涨停价
    p REAL,                      -- 现价
    ltsz REAL,                   -- 流通市值
    fundamt REAL,                -- 成交额
    hybk TEXT,                   -- 行业
    snapshot_at TEXT,            -- 采集时间戳
    is_final INTEGER DEFAULT 0,  -- 1=终盘稳定版（采集时间>=17:15）；每日唯一行级标记
    PRIMARY KEY (date, code)     -- 幂等：同日同 code 重写覆盖
)"""
_INDEX = "CREATE INDEX IF NOT EXISTS idx_zt_history_date ON zt_history(date)"


def _ensure_final_column(conn: sqlite3.Connection) -> None:
    """幂等加 is_final 列（存量 DB 老表无此列，ALTER TABLE ADD COLUMN 若已存在则跳过）。

    PRAGMA table_info 取列名集合，缺则 ALTER TABLE ADD COLUMN is_final INTEGER DEFAULT 0。
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(zt_history)")}
    if "is_final" not in cols:
        conn.execute("ALTER TABLE zt_history ADD COLUMN is_final INTEGER DEFAULT 0")
        conn.commit()


def _get_conn() -> sqlite3.Connection:
    """建库 + 建表（幂等）+ 返连接。row_factory=Row。"""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.execute(_INDEX)
    _ensure_final_column(conn)
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# 归一辅助
# ─────────────────────────────────────────────────────────────────────────────

def _to_float(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = str(v).strip().replace(",", "")
    if not s or s in ("-", "--", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(v) -> int | None:
    f = _to_float(v)
    return int(f) if f is not None else None


def _to_iso(d: str) -> str:
    """归一 YYYYMMDD 或 YYYY-MM-DD → YYYY-MM-DD。"""
    if not d:
        return ""
    s = str(d).strip()
    if "-" in s:
        return s
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


# ─────────────────────────────────────────────────────────────────────────────
# 采集 + 读取
# ─────────────────────────────────────────────────────────────────────────────

def snapshot_zt_pool(
    date: str | None = None,
    pool: list[dict] | None = None,
    is_final: bool = False,
) -> int:
    """snapshot 当日涨停池 → zt_history。返回写入行数。

    Args:
        date: YYYY-MM-DD 或 YYYYMMDD。None=最近交易日（vr_paths.last_trading_date_str）。
        pool: 预填涨停池（测试/复用，跳过 em 调用）；None=调 astock.em_zt_topic_pool 取。
        is_final: True=终盘稳定版（采集时间>=17:15，东财池已稳定）。final 一旦落定，
            后续 is_final=False 的写入被**拒绝覆盖**（保守，避免旧时点快照污染终盘）。

    **每日唯一 + final 标记（2026-08-23 落地）**：
    单事务内 DELETE 同 date 全行 → INSERT 新池。解决"INSERT OR REPLACE 只覆盖同 code 行，
    新旧快照 code 集合不同时残行混入"（实证 2026-08-21 同日存 16:00 68 条 + 08-23 00:08 54 条
    两个时点混合 122 行）。

    幂等：同日重跑覆盖（DELETE+INSERT，不翻倍）。缺字段填 None（不臆造）。空池→返回 0
    （非交易日/端点空；空池不触发 DELETE 旧数据，避免误清已落定终盘）。
    """
    d_iso = _to_iso(date) if date else ""
    if not d_iso:
        from vr_paths import last_trading_date_str
        d_iso = last_trading_date_str()
    d_compact = d_iso.replace("-", "")

    if pool is None:
        import astock
        try:
            pool = astock.em_zt_topic_pool("getTopicZTPool", d_compact, "fbt:asc") or []
        except Exception as e:  # noqa: BLE001
            _logger.warning("snapshot_zt_pool em_zt_topic_pool 失败 date=%s err=%s", d_iso, e)
            return 0
    if not pool:
        _logger.info("snapshot_zt_pool date=%s 涨停池空，跳过", d_iso)
        return 0

    snap_at = datetime.now().isoformat(timespec="seconds")
    rows: list[dict] = []
    for it in pool:
        if not isinstance(it, dict):
            continue
        code = str(it.get("c", "") or "").strip()
        if not code:
            continue
        rows.append({
            "date": d_iso, "code": code, "name": it.get("n"),
            "lbc": _to_int(it.get("lbc")), "zbc": _to_float(it.get("zbc")),
            "fbt": _to_float(it.get("fbt")), "fund": _to_float(it.get("fund")),
            "zje": _to_float(it.get("zje")), "p": _to_float(it.get("p")),
            "ltsz": _to_float(it.get("ltsz")), "fundamt": _to_float(it.get("fundamt")),
            "hybk": it.get("hybk"), "snapshot_at": snap_at,
        })
    if not rows:
        return 0
    conn = _get_conn()
    try:
        with _DB_LOCK:
            # final 保护：旧行已 is_final=1 且新数据 is_final=False → 拒绝覆盖
            prev = conn.execute(
                "SELECT is_final FROM zt_history WHERE date = ? LIMIT 1", (d_iso,)
            ).fetchone()
            if prev is not None and prev["is_final"] == 1 and not is_final:
                _logger.warning(
                    "snapshot_zt_pool date=%s 拒绝覆盖：旧行已 is_final=1，新数据非 final", d_iso)
                return 0
            # UPSERT 同日行：单事务 DELETE 旧日全行 + INSERT 新池（每日唯一，不残留旧时点残行）
            conn.execute("DELETE FROM zt_history WHERE date = ?", (d_iso,))
            cur = conn.executemany(
                """INSERT INTO zt_history
                (date, code, name, lbc, zbc, fbt, fund, zje, p, ltsz, fundamt, hybk,
                 snapshot_at, is_final)
                VALUES (:date, :code, :name, :lbc, :zbc, :fbt, :fund, :zje, :p,
                        :ltsz, :fundamt, :hybk, :snapshot_at, :is_final)""",
                [{**r, "is_final": 1 if is_final else 0} for r in rows],
            )
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def load_zt_history(start: str, end: str) -> list[dict[str, Any]]:
    """读 [start, end] 涨停历史（date, code 升序）。start/end: YYYY-MM-DD 或 YYYYMMDD。"""
    s, e = _to_iso(start), _to_iso(end)
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM zt_history WHERE date >= ? AND date <= ? ORDER BY date, code",
            (s, e),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_history_dates() -> list[str]:
    """列出有历史快照的日期（YYYY-MM-DD，升序）。"""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT DISTINCT date FROM zt_history ORDER BY date").fetchall()
        return [r["date"] for r in rows]
    finally:
        conn.close()


if __name__ == "__main__":
    # 手动触发当日 snapshot（或传日期）
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    n = snapshot_zt_pool(d)
    print(f"snapshot_zt_pool({d}): 写入 {n} 行")
