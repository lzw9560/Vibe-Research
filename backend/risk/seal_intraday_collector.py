# -*- coding: utf-8 -*-
"""S055：盘中封单时序采集层。

交易时段（09:25-15:05）每 60s 轮询 ``astock.em_zt_topic_pool`` 写 SQLite
``seal_intraday_snapshots`` 表。同周期用 ``tencent_quote`` 取指数快照（C4 输入）
与候选股流通市值（C6 输入）。非交易时段不落库、不请求东财（门控）。

工程底线：
- 东财端点走 ``em_get()`` 限流/熔断/代理探测（astock 内部已封装），不裸调 requests
- 缺快照/缺市值 → 规则跳过并记 data_status，不补默认值（不臆造）
- 私有数据（.vibe-research/seal_intraday.db）不进 git
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Any

from config import SEAL_INTRADAY_DB_PATH
from vr_paths import is_trading_day

_logger = logging.getLogger(__name__)

_DB_PATH = SEAL_INTRADAY_DB_PATH
_DB_LOCK = threading.Lock()

# 交易时段门控（A 股）：09:25-11:30 + 13:00-15:05（含盘后 5 分钟兜底）
_TRADING_PERIODS = [
    (dtime(9, 25), dtime(11, 30)),
    (dtime(13, 0), dtime(15, 5)),
]


def run_migrations() -> None:
    """执行 seal_intraday 迁移（幂等）。"""
    from migrations import MigrationManager

    manager = MigrationManager(db_path=_DB_PATH)
    migrations_dir = Path(__file__).resolve().parent.parent / "migrations" / "seal_intraday"
    migration_v1 = (migrations_dir / "20260811-001_create_seal_intraday_snapshots.sql").read_text(encoding="utf-8")
    # S070 R6.1：加 low_price + limit_pct 列（R6 分时低点 + R7 涨停价反推）
    migration_v2 = (migrations_dir / "20260818-001_add_low_price_limit_pct.sql").read_text(encoding="utf-8")
    # S070 R3：建 intraday_features（R1 trajectory）+ seal_derived_features（R7 派生）两表
    # S084 follow-up：derived 预采集合并入 seal_derived_features（删冗余 derived_results 表，
    # 其字段为 seal_derived_features 子集，get_derived_result/save_derived_result 接口不变）
    migration_v3 = (migrations_dir / "20260818-002_create_intraday_features.sql").read_text(encoding="utf-8")
    migrations = [
        {"version": "20260811-001", "name": "create_seal_intraday_snapshots", "sql": migration_v1},
        {"version": "20260818-001", "name": "add_low_price_limit_pct", "sql": migration_v2},
        {"version": "20260818-002", "name": "create_intraday_features", "sql": migration_v3},
    ]
    manager.upgrade(migrations)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def is_intraday_trading_time(now: datetime | None = None) -> bool:
    """判断当前是否在盘中交易时段（含是否交易日）。

    组合判断：is_trading_day(日期) 且 当前时间在 _TRADING_PERIODS 内。
    """
    now = now or datetime.now()
    if not is_trading_day(now.date()):
        return False
    t = now.time()
    for start, end in _TRADING_PERIODS:
        if start <= t <= end:
            return True
    return False


def prune_old_snapshots(retention_days: int = 30) -> int:
    """删除超过保留期的快照行。返回删除行数。"""
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    conn = _get_conn()
    try:
        with _DB_LOCK:
            cur = conn.execute(
                "DELETE FROM seal_intraday_snapshots WHERE date < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def save_snapshots(rows: list[dict[str, Any]]) -> int:
    """批量写入快照行。rows 字段对齐 seal_intraday_snapshots 表。返回写入行数。

    缺失字段填 None（不臆造，允许部分字段空）。
    """
    if not rows:
        return 0
    # 补齐缺失字段（允许部分字段缺失）；S070 R6 加 low_price + limit_pct
    fields = ["ts", "date", "code", "name", "pool", "price", "seal_amount",
              "open_count", "first_seal_time", "consec_boards", "sector",
              "float_market_cap", "index_5min_change",
              "low_price", "limit_pct"]
    normalized = [{k: r.get(k) for k in fields} for r in rows]
    conn = _get_conn()
    try:
        with _DB_LOCK:
            cur = conn.executemany(
                """INSERT INTO seal_intraday_snapshots
                (ts, date, code, name, pool, price, seal_amount, open_count,
                 first_seal_time, consec_boards, sector, float_market_cap, index_5min_change,
                 low_price, limit_pct)
                VALUES (:ts, :date, :code, :name, :pool, :price, :seal_amount,
                 :open_count, :first_seal_time, :consec_boards, :sector,
                 :float_market_cap, :index_5min_change,
                 :low_price, :limit_pct)""",
                normalized,
            )
            conn.commit()
            return cur.rowcount
    finally:
        conn.close()


def get_snapshots_by_code(code: str, date: str | None = None) -> list[dict[str, Any]]:
    """查单股封单时序（sparkline 用）。date 缺省取最近交易日。"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM seal_intraday_snapshots WHERE code = ? AND date = ? ORDER BY ts",
            (code, date),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_latest_snapshots(date: str | None = None) -> list[dict[str, Any]]:
    """查当日全部最新快照（按 code 取最近一条）。"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM seal_intraday_snapshots s
            WHERE date = ? AND ts = (
                SELECT MAX(ts) FROM seal_intraday_snapshots WHERE date = ? AND code = s.code
            )
            ORDER BY code""",
            (date, date),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_window(code: str, date: str, minutes: int = 5) -> list[dict[str, Any]]:
    """取近 N 分钟的快照窗口（C1/C5 规则输入）。"""
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT * FROM seal_intraday_snapshots
            WHERE code = ? AND date = ? AND ts >= ?
            ORDER BY ts""",
            (code, date, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# S084 C2/C3：derived 预采集读写（盘后 executor 写 / derived_source 读）
# S084 follow-up：合并入 seal_derived_features（删冗余 derived_results 表，
#   字段为 seal_derived_features 子集，save/get_derived_result 接口不变）。
# ---------------------------------------------------------------------------

#: 派生粒度标注常量（表 granularity_note 列缺值时兜底，与 compute_derived_features 同形）
_DERIVED_GRANULARITY_NOTE = "60s粒度近似"


def save_derived_result(date: str, code: str, derived: dict[str, Any]) -> None:
    """S084 C2：derived 预采集结果写 seal_derived_features 表（INSERT OR REPLACE，幂等）。

    盘后 executor 对昨日涨停股全量扫一遍后逐只调用。批量场景 executor 可复用
    连接直接写（见 ``_execute_derived_precompute``，复用 persist_derived_features），
    本函数供单只/补算场景。
    S084 follow-up：改写 seal_derived_features（原 derived_results 已删，字段为其子集）。
    name 缺省 None（批量场景由 executor 从涨停池取 name 直传 persist_derived_features）。
    """
    conn = _get_conn()
    try:
        with _DB_LOCK:
            conn.execute(
                """INSERT OR REPLACE INTO seal_derived_features
                (date, code, name, last_lock_time, broken_duration_min, max_drop_pct,
                 limit_price, granularity_note, computed_at, data_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (date, code, None,
                 derived.get("last_lock_time"),
                 derived.get("broken_duration_min"),
                 derived.get("max_drop_pct"),
                 derived.get("limit_price"),
                 derived.get("granularity_note") or _DERIVED_GRANULARITY_NOTE,
                 datetime.now().isoformat(),
                 derived.get("data_status")),
            )
            conn.commit()
    finally:
        conn.close()


def get_derived_result(code: str, date: str) -> dict[str, Any] | None:
    """S084 C3：derived_source 读 seal_derived_features 预采集表（SELECT WHERE code/date）。

    无行 / 缺表 / DB 未就绪 → None（交 derived_source fallback 实时算或降级 None，不臆造）。
    重建与 ``compute_derived_features`` 同形 dict（读 seal_derived_features 全字段；
    granularity_note 列缺值时补常量兜底，保证下游 shape 一致）。
    S084 follow-up：改读 seal_derived_features（原 derived_results 已删），接口不变。
    """
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT last_lock_time, broken_duration_min, max_drop_pct, limit_price, "
                "granularity_note, data_status "
                "FROM seal_derived_features WHERE code = ? AND date = ?",
                (code, date),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # fresh env 未跑迁移 / 表不存在 → None，交 fallback（不臆造）
        return None
    if not row:
        return None
    return {
        "last_lock_time": row["last_lock_time"],
        "broken_duration_min": row["broken_duration_min"],
        "max_drop_pct": row["max_drop_pct"],
        "limit_price": row["limit_price"],
        "granularity_note": row["granularity_note"] or _DERIVED_GRANULARITY_NOTE,
        "data_status": row["data_status"],
    }


def get_trajectory_result(code: str, date: str) -> dict[str, Any] | None:
    """S085 B3：读 intraday_features 表 trajectory 的 seal_delta（修只写不读孤儿）。

    persist_trajectory 写 intraday_features（seal_delta 列），但原无 reader（全仓 grep
    FROM intraday_features 空）。本 reader 让 seal_delta 可读，derived_source 透传到 card。
    无行 / 缺表 / DB 未就绪 → None（不臆造）。消费方待接（目前 dead field，像 A7）。
    """
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT seal_delta, data_status FROM intraday_features WHERE code = ? AND date = ?",
                (code, date),
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return {
        "seal_delta": row["seal_delta"],
        "data_status": row["data_status"],
    }


def collect_once(date_str: str | None = None) -> dict[str, Any]:
    """单次采集：取涨停池 + 腾讯行情 → 写快照。

    返回 {written, skipped, error?}。非交易时段直接返 skipped=1 不请求东财。
    缺数据诚实标注，不臆造。
    """
    now = datetime.now()
    if not is_intraday_trading_time(now):
        return {"written": 0, "skipped": 1, "reason": "非交易时段或非交易日"}

    date_str = date_str or now.strftime("%Y-%m-%d")
    compact_date = now.strftime("%Y%m%d")
    ts = now.isoformat()

    # 1. 涨停池（走 em_get 限流）
    import astock
    try:
        zt_pool = astock.em_zt_topic_pool("getTopicZTPool", compact_date, "fbt:asc") or []
    except Exception as exc:
        _logger.warning("[seal_intraday] em_zt_topic_pool 失败: %s", exc)
        return {"written": 0, "skipped": 1, "reason": f"东财请求失败: {exc}", "data_status": "degraded"}

    # 2. 指数 5 分钟跌幅（C4 输入）—— 腾讯行情，不封 IP
    # tencent_quote 接受个股代码（带前缀映射），但指数需走 data.sources.tencent.index_raw()
    # （A_INDICES 固定前缀，tencent_quote 的 get_prefix 不处理 sh/sz 指数代码）
    index_5min_change = None
    try:
        from data.sources.tencent import index_raw
        indices = index_raw()
        # 上证指数（sh000001）作为大盘 5 分钟跌幅代理
        sh_idx = next((i for i in indices if "上证" in i.get("name", "")), None)
        if sh_idx:
            index_5min_change = sh_idx.get("change_pct")
    except Exception:
        index_5min_change = None

    # 3. 候选股流通市值（C6 输入）—— 涨停池已含 float_shares
    # 东财 getTopicZTPool 字段：c=代码/n=名/p=最新价/zdp=涨幅/amount=成交额/
    # ltsz=流通市值/tshare=总股本/hs=换手/lbc=连板/fbt=首封时间/fund=封单额(元)/
    # zbc=炸板次数/hybk=行业。封单额键名是 fund（非 seal_amount）。

    # S070 R6.2：批量取涨停池个股 tencent_quote（分时低点 low=vals[34]）
    # 一次请求全池 codes（60s TTL 缓存，同周期内复用，不重复请求）
    # tencent_quote 失败 → low_price 留 None，不臆造（与 S055 data_status 范式一致）
    codes = [str(item.get("c", "")) for item in zt_pool if item.get("c")]
    quotes: dict[str, dict] = {}
    if codes:
        try:
            quotes = astock.tencent_quote(codes) or {}
        except Exception as exc:
            _logger.warning("[seal_intraday] tencent_quote 取 low 失败: %s", exc)
            quotes = {}

    rows: list[dict[str, Any]] = []
    for item in zt_pool:
        code = str(item.get("c", ""))
        if not code:
            continue
        # 流通市值直接用 ltsz（元），不再手算 float_shares*price
        float_cap = item.get("ltsz")
        price = item.get("p") or item.get("zje") or 0
        seal_amount = item.get("fund")  # 封单额（元）
        # S070 R6：分时低点（tencent_quote 的 low 字段，缺失时 None 不臆造）
        q = quotes.get(code) or {}
        low_price = q.get("low") if q else None
        # S070 R7 前置：涨停涨幅%（zdp，用于反推涨停价 limit_price=price/(1+limit_pct/100)）
        limit_pct = item.get("zdp")
        rows.append({
            "ts": ts,
            "date": date_str,
            "code": code,
            "name": item.get("n"),
            "pool": "zt",
            "price": price,
            "seal_amount": seal_amount,
            "open_count": item.get("zbc"),
            "first_seal_time": item.get("fbt"),
            "consec_boards": item.get("lbc"),
            "sector": item.get("hybk"),
            "float_market_cap": float_cap,
            "index_5min_change": index_5min_change,
            "low_price": low_price,
            "limit_pct": limit_pct,
        })

    written = save_snapshots(rows)
    return {"written": written, "skipped": 0, "data_status": "ok" if written else "empty"}
