# -*- coding: utf-8 -*-
"""data_ops executors——数据刷新/同步/清理/kline 刷新/月度 VACUUM。"""
from __future__ import annotations

import logging
from datetime import date as _date, datetime, timedelta
from typing import Any, Dict

from scheduler.db import _get_connection

logger = logging.getLogger("vibe-research")


def daily_data_refresh(payload: Dict[str, Any]) -> Dict[str, Any]:
    """每日数据刷新：刷新持仓。

    R7（S031）：复盘预计算统一由 limitup_precompute 驱动
    （_execute_limitup_precompute 内对 back_days 各日调 reviewer.precompute_daily），
    此处只保留持仓刷新——单一事实源，不再重复调 daily_review。
    """
    import portfolio as pf

    results: Dict[str, Any] = {}
    try:
        pf.refresh_all()
        results["portfolio"] = "ok"
    except Exception as e:
        logger.warning("[daily_data_refresh] 持仓刷新失败: %s", e)
        results["portfolio"] = f"error: {e}"

    return results


def market_data_sync(payload: Dict[str, Any]) -> Dict[str, Any]:
    """同步市场数据（M12：空壳桩，未实现具体同步逻辑）。"""
    results: Dict[str, Any] = {}
    results["market"] = "stub: market_data_sync 未实现具体同步逻辑"
    return results


def cleanup_old_runs(payload: Dict[str, Any]) -> Dict[str, Any]:
    """清理旧的运行记录。"""
    results: Dict[str, Any] = {}
    keep_days = int(payload.get("keep_days", 30))
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat()

    conn = _get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM scheduled_task_runs WHERE started_at < ?",
            (cutoff,),
        )
        deleted = cursor.rowcount
        conn.commit()
        results["deleted_runs"] = deleted
        results["keep_days"] = keep_days
    finally:
        conn.close()

    return results


def kline_refresh(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S090 B：baostock_kline_cache 日更——盘后增量刷新当日新 bar。

    调 ``tools/refresh_kline_cache.main`` 增量刷新（从各股最新 bar 后拉到
    last_trading_date，原子写 temp→rename）。baostock 非东财不被 IP 限流
    （§44 grill 资金流被 push2his 限流，kline 不受影响），可每日跑。

    payload 可选：``max_stocks``（None=全量，debug 用）。
    返回 ``{"status": "ok"|"degraded", "return_code": int}``。baostock 未装 /
    cache 不存在 / login 失败标 degraded 不崩（main 内部返 1）。
    """
    max_stocks = payload.get("max_stocks")
    try:
        from tools.refresh_kline_cache import main as _refresh_kline  # noqa: PLC0415
        ret = _refresh_kline(max_stocks)
        return {"status": "ok" if ret == 0 else "degraded", "return_code": ret}
    except ImportError as e:  # noqa: BLE001
        logger.warning("[kline_refresh] baostock 未安装: %s", e)
        return {"status": "degraded", "reason": f"baostock 未安装: {e}"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[kline_refresh] 刷新失败（不阻塞）: %s", exc)
        return {"status": "degraded", "reason": str(exc)}


def monthly_vacuum(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S089 D2：月度 VACUUM + wal_checkpoint(TRUNCATE)——热库（当年）月初触发。

    遍历 ``.vibe-research/`` 下的 ``seal_intraday_YYYY.db``，对当年库执行
    ``VACUUM``（回收碎片）+ ``PRAGMA wal_checkpoint(TRUNCATE)``（截断 -wal 文件，
    防止长期累积膨胀）。历史年冷库默认不 VACUUM（归档时单独跑一次，spec §R6.2）。

    payload 可选字段：
    - ``year``: 指定年（默认当年），debug/补跑用
    - ``include_cold``: True 时连历史年冷库一起 VACUUM（默认 False）

    返回 ``{"vacuumed": [db...], "checkpointed": [db...]}``。单库失败不阻塞其余
    （catch 记 error，标 status）。
    """
    import os
    import sqlite3
    from config import SEAL_INTRADAY_DIR
    from db_health import get_healthy_conn

    target_year = str(payload.get("year", _date.today().year))
    include_cold = bool(payload.get("include_cold", False))

    if not os.path.isdir(SEAL_INTRADAY_DIR):
        logger.info("[monthly_vacuum] SEAL_INTRADAY_DIR=%s 不存在，跳过", SEAL_INTRADAY_DIR)
        return {"vacuumed": [], "checkpointed": [], "status": "no_dir"}

    vacuumed: list[str] = []
    checkpointed: list[str] = []
    errors: list[str] = []
    for fname in sorted(os.listdir(SEAL_INTRADAY_DIR)):
        # seal_intraday_YYYY.db（排除 .bak / -wal / -shm）
        if not fname.startswith("seal_intraday_") or not fname.endswith(".db"):
            continue
        if fname.endswith(".bak"):
            continue
        year = fname[len("seal_intraday_"):-len(".db")]
        if len(year) != 4 or not year.isdigit():
            continue
        is_hot = year == target_year
        if not is_hot and not include_cold:
            continue  # 冷库默认跳过

        db_path = os.path.join(SEAL_INTRADAY_DIR, fname)
        try:
            # VACUUM 需独占连接（WAL 模式下 VACUUM 仍要求无并发写）；用裸 connect
            # 避免 get_healthy_conn 的 row_factory 干扰 VACUUM（VACUUM 不返行）。
            # wal_checkpoint 在 get_healthy_conn 已开 WAL 的连接上执行。
            vconn = sqlite3.connect(db_path)
            try:
                vconn.execute("PRAGMA journal_mode=WAL")
                vconn.execute("PRAGMA busy_timeout=5000")
                vconn.execute("VACUUM")
                vacuumed.append(fname)
            finally:
                vconn.close()

            cconn = get_healthy_conn(db_path)
            try:
                # TRUNCATE 模式：checkpoint 后将 -wal 截断为 0（防膨胀）
                row = cconn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                # row = (busy, log, checkpointed_frames)；busy=1 表示有并发写未完成
                if row and row[0] == 0:
                    checkpointed.append(fname)
                elif row:
                    logger.warning(
                        "[monthly_vacuum] %s wal_checkpoint busy（有并发写，未截断）: %s",
                        fname, tuple(row),
                    )
                    checkpointed.append(fname)  # 仍记（已尽力）
            finally:
                cconn.close()
        except Exception as e:
            logger.warning("[monthly_vacuum] %s VACUUM/checkpoint 失败: %s", fname, e)
            errors.append(f"{fname}: {e}")

    logger.info(
        "[monthly_vacuum] year=%s vacuumed=%s checkpointed=%s errors=%s",
        target_year, vacuumed, checkpointed, errors,
    )
    return {
        "vacuumed": vacuumed,
        "checkpointed": checkpointed,
        "errors": errors,
        "status": "ok" if not errors else "partial",
    }
