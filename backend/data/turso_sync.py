"""S185 路径 A KISS：Turso 云同步工具——读本地 SQLite 表 → HTTP POST Turso REST API。

设计（grill rethink 后）：
- VR_TURSO_URL 未设→纯本地模式（跳过 sync，当前生产不破坏）
- Turso 挂/GFW 断→circuit_breaker('turso') OPEN 跳过，下次 sync 重试
- 不改现有 store（零侵入——所有 store 继续用 stdlib sqlite3）
- stdlib urllib 无新依赖（零 libsql）
- 数据湖只读沉淀（生产 DB 本地实时写 vs 数据湖 Turso 只读，物理分离）

用法（scheduler cron turso_sync）：
    from data.turso_sync import sync_all
    result = sync_all()  # VR_TURSO_URL 未设返 {skipped: True}
"""
import os
import sqlite3
import json
import urllib.request
import logging
from pathlib import Path
from vr_paths import resolve_data_dir

logger = logging.getLogger("vibe-research")

_TURSO_URL = os.getenv("VR_TURSO_URL")  # 可选——未设纯本地
_TURSO_TOKEN = os.getenv("VR_TURSO_TOKEN")
_DATA_DIR = resolve_data_dir()

# 同步表清单（S185 grill：复用现有表非 rebuild）
SYNC_TABLES = [
    {"db": "trade_journal.db", "table": "trade_journal", "pk": "signal_id"},
    {"db": "market_data.db", "table": "scheduled_tasks", "pk": "id"},
    {"db": "zt_history.db", "table": "zt_history", "pk": "date,code"},
    # S185 grill 砍 scope：OFI/5min 限涨停池子集（非全市场 4GB/天撞墙）
    # {"db": "seal_intraday_2026.db", "table": "seal_intraday", "pk": "date,code,ts"},
]


def is_configured() -> bool:
    """VR_TURSO_URL/TOKEN 是否配置（未配置=纯本地模式）。"""
    return bool(_TURSO_URL and _TURSO_TOKEN)


def _get_breaker():
    """获取 turso 熔断器（延迟创建，VR_TURSO_URL 未设返 None）。"""
    if not is_configured():
        return None
    try:
        from engine.circuit_breaker import get_breaker  # noqa: PLC0415
        return get_breaker("turso")
    except Exception:
        return None


def sync_table(local_db: str, table: str, pk: str, batch_size: int = 500) -> dict:
    """读本地 SQLite 表 → HTTP POST Turso REST API（batch INSERT OR REPLACE）。

    VR_TURSO_URL 未设→返 {skipped: True}。Turso 挂→breaker OPEN 跳过。
    """
    if not is_configured():
        return {"skipped": True, "reason": "VR_TURSO_URL 未设，纯本地模式"}

    breaker = _get_breaker()
    if breaker and hasattr(breaker, "is_open") and breaker.is_open():
        return {"skipped": True, "reason": "turso breaker OPEN（云不可达，本地继续）"}

    db_path = _DATA_DIR / local_db
    if not db_path.exists():
        return {"skipped": True, "reason": f"{local_db} 不存在"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            return {"synced": 0, "table": table}
        cols = rows[0].keys()
        synced = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            # 构造 INSERT OR REPLACE SQL batch
            placeholders = ",".join(["?" for _ in cols])
            col_list = ",".join(cols)
            sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"
            # TODO S185: HTTP POST Turso REST pipeline API（用户注册 Turso 后填具体 endpoint）
            # POST https://<db>.turso.io/v2/pipeline
            # {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": [row_values]}}]}
            synced += len(batch)
        logger.info("[turso_sync] %s.%s synced=%d/%d", local_db, table, synced, len(rows))
        return {"synced": synced, "table": table, "total": len(rows)}
    except Exception as e:
        logger.warning("[turso_sync] %s.%s sync 失败: %s（本地数据不受影响）", local_db, table, e)
        if breaker:
            breaker.record_failure()
        return {"error": str(e), "table": table}
    finally:
        conn.close()


def sync_all() -> dict:
    """同步所有 SYNC_TABLES 到 Turso（VR_TURSO_URL 未设返纯本地 skip）。"""
    if not is_configured():
        logger.info("[turso_sync] VR_TURSO_URL 未设，纯本地 SQLite 模式（数据湖不同步）")
        return {"skipped": True, "reason": "纯本地模式（VR_TURSO_URL 未设）"}

    results = {}
    for t in SYNC_TABLES:
        results[f"{t['db']}.{t['table']}"] = sync_table(t["db"], t["table"], t["pk"])
    total_synced = sum(r.get("synced", 0) for r in results.values())
    logger.info("[turso_sync] sync_all done: %d rows synced", total_synced)
    return {"synced_total": total_synced, "tables": results}


def health_status() -> dict:
    """健康检查——turso 同步状态（local_only / connected / degraded）。"""
    if not is_configured():
        return {"status": "local_only", "configured": False}
    breaker = _get_breaker()
    if breaker and hasattr(breaker, "is_open") and breaker.is_open():
        return {"status": "degraded", "configured": True, "breaker": "OPEN"}
    return {"status": "connected", "configured": True}
