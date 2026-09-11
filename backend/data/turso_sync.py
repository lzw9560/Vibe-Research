"""S185 路径 A KISS：Turso 云同步工具——读本地 SQLite 表 → HTTP POST Turso v2/pipeline REST API。

设计（grill rethink 后）：
- VR_TURSO_URL 未设→纯本地模式（跳过 sync，当前生产不破坏）
- Turso 挂/GFW 断→circuit_breaker('turso') OPEN 跳过，下次 sync 重试
- 不改现有 store（零侵入——所有 store 继续用 stdlib sqlite3）
- stdlib urllib 无新依赖（零 libsql）
- 数据湖只读沉淀（生产 DB 本地实时写 vs 数据湖 Turso 只读，物理分离）

Turso v2/pipeline API（实测确认 2026-09-11）：
- POST https://<db>.turso.io/v2/pipeline
- Authorization: Bearer <token>
- Body: {"requests": [{"type":"execute","stmt":{"sql":"INSERT OR REPLACE INTO ... VALUES (?,...)","args":[{"type":"text","value":"..."},...]}}]}
- typed args: text/integer/real/null/blob

用法（scheduler cron turso_sync）：
    from data.turso_sync import sync_all
    result = sync_all()  # VR_TURSO_URL 未设返 {skipped: True}
"""
import os
import sqlite3
import json
import urllib.request
import urllib.error
import logging
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
]


def is_configured() -> bool:
    """VR_TURSO_URL/TOKEN 是否配置（未配置=纯本地模式）。"""
    return bool(_TURSO_URL and _TURSO_TOKEN)


def _get_http_url() -> str:
    """libsql:// → https:// for HTTP REST API."""
    url = _TURSO_URL or ""
    return url.replace("libsql://", "https://").replace("http://", "https://")


def _get_breaker():
    """获取 turso 熔断器（延迟创建，VR_TURSO_URL 未设返 None）。"""
    if not is_configured():
        return None
    try:
        from engine.circuit_breaker import get_breaker  # noqa: PLC0415
        return get_breaker("turso")
    except Exception:
        return None


def _to_turso_arg(val) -> dict:
    """Python value → Turso typed arg（v2/pipeline args 格式）。"""
    if val is None:
        return {"type": "null"}
    if isinstance(val, bool):
        return {"type": "integer", "value": "1" if val else "0"}
    if isinstance(val, int):
        return {"type": "integer", "value": str(val)}
    if isinstance(val, float):
        return {"type": "float", "value": val}  # Turso float value 是 number 非 string
    return {"type": "text", "value": str(val)}


def _post_pipeline(sql: str, args: list, table: str) -> bool:
    """HTTP POST Turso v2/pipeline 执行单条 SQL。返 True 成功 / False 失败（降级）。"""
    breaker = _get_breaker()
    if breaker and hasattr(breaker, "is_open") and breaker.is_open():
        return False

    http_url = _get_http_url()
    data = json.dumps({"requests": [{"type": "execute", "stmt": {"sql": sql, "args": args}}]}).encode()
    req = urllib.request.Request(
        f"{http_url}/v2/pipeline",
        data=data,
        headers={"Authorization": f"Bearer {_TURSO_TOKEN}", "Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        body = json.loads(resp.read().decode())
        ok = body.get("results", [{}])[0].get("type") == "ok"
        if not ok and breaker:
            breaker.record_failure()
        return ok
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        logger.warning("[turso_sync] %s HTTP POST 失败: %s（本地数据不受影响）", table, e)
        if breaker:
            breaker.record_failure()
        return False
    except Exception as e:  # noqa: BLE001
        logger.warning("[turso_sync] %s 异常: %s", table, e)
        if breaker:
            breaker.record_failure()
        return False


def _ensure_turso_table(local_db: str, table: str) -> bool:
    """从本地 DB 提取 schema + CREATE TABLE IF NOT EXISTS in Turso（schema migration）。"""
    db_path = _DATA_DIR / local_db
    if not db_path.exists():
        return False
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not row or not row[0]:
            return False
        schema_sql = row[0].replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
        return _post_pipeline(schema_sql, [], table)
    finally:
        conn.close()


def sync_table(local_db: str, table: str, pk: str, batch_size: int = 100) -> dict:
    """读本地 SQLite 表 → HTTP POST Turso v2/pipeline（batch INSERT OR REPLACE）。

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

    # CREATE TABLE IF NOT EXISTS in Turso（从本地 schema 提取，自动 migration）
    if not _ensure_turso_table(local_db, table):
        return {"error": f"CREATE {table} in Turso 失败", "table": table}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            return {"synced": 0, "table": table}
        cols = list(rows[0].keys())
        col_list = ",".join(cols)
        placeholders = ",".join(["?" for _ in cols])
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({placeholders})"

        synced = 0
        failed = 0
        http_url = _get_http_url()
        breaker = _get_breaker()
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            # batch POST：500 行 = 500 INSERT OR REPLACE 一个 v2/pipeline request（7 POST 替代 3354）
            requests = []
            for row in batch:
                args = [_to_turso_arg(row[c]) for c in cols]
                requests.append({"type": "execute", "stmt": {"sql": sql, "args": args}})
            data = json.dumps({"requests": requests}).encode()
            req = urllib.request.Request(
                f"{http_url}/v2/pipeline",
                data=data,
                headers={"Authorization": f"Bearer {_TURSO_TOKEN}", "Content-Type": "application/json"},
            )
            try:
                resp = urllib.request.urlopen(req, timeout=60)
                body = json.loads(resp.read().decode())
                results = body.get("results", [])
                for r in results:
                    if r.get("type") == "ok":
                        synced += 1
                    else:
                        failed += 1
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                logger.warning("[turso_sync] %s batch POST 失败: %s（本地不受影响）", table, e)
                failed += len(batch)
                if breaker:
                    breaker.record_failure()
                if failed > 50:
                    logger.warning("[turso_sync] %s 连续失败 >50，跳过剩余", table)
                    break
        logger.info("[turso_sync] %s.%s synced=%d failed=%d/%d (batch=%d/POST)", local_db, table, synced, failed, len(rows), batch_size)
        return {"synced": synced, "failed": failed, "table": table, "total": len(rows)}
    except Exception as e:  # noqa: BLE001
        logger.warning("[turso_sync] %s.%s sync 失败: %s（本地数据不受影响）", local_db, table, e)
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
    total_failed = sum(r.get("failed", 0) for r in results.values())
    logger.info("[turso_sync] sync_all done: %d rows synced, %d failed", total_synced, total_failed)
    return {"synced_total": total_synced, "failed_total": total_failed, "tables": results}


def health_status() -> dict:
    """健康检查——turso 同步状态（local_only / connected / degraded）。"""
    if not is_configured():
        return {"status": "local_only", "configured": False}
    breaker = _get_breaker()
    if breaker and hasattr(breaker, "is_open") and breaker.is_open():
        return {"status": "degraded", "configured": True, "breaker": "OPEN"}
    return {"status": "connected", "configured": True}
