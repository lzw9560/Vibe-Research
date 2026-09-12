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
        if ret == 0:
            # S175/S177：kline 刷盘成功后清 bars_provider 单例 cache，
            # 防 kline_refresh 16:30 写新 bar 但 cache 仍读旧 → signal_date 不在 bars → 全 unbuyable
            from engine.bars_provider import KlineCacheBarsProvider  # noqa: PLC0415
            KlineCacheBarsProvider.reload()
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


def healthcheck_ping(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S188 RB-2 · 外部心跳（healthchecks.io）防 cron 静默死。

    CronScheduler 是 FastAPI lifespan 内的 async while+ticker——进程死→ticker 死→
    全 cron 静默停，无任何外部告警（macOS 睡死是自托管个人工具最高频可靠性风险）。
    本 executor 每小时出站 ping healthchecks.io（免费层 20 checks）；ping 停 →
    healthchecks.io 邮件告警（零成本外部告警，出站不进站，不依赖 Cloudflare Tunnel）。

    配置：VR_HEALTHCHECKS_URL env 变量（healthchecks.io check ping URL，
    如 https://hc-ping.com/<uuid>）。未设 → 跳过（纯本地模式，同 Turso 范式）。

    payload 可选：``url`` 覆盖 env（测试用）。
    """
    import os  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415
    import urllib.error  # noqa: PLC0415

    url = payload.get("url") or os.getenv("VR_HEALTHCHECKS_URL")
    if not url:
        return {"skipped": True, "reason": "VR_HEALTHCHECKS_URL 未设，纯本地模式（无外部心跳）"}
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
        logger.info("[healthcheck_ping] ping OK status=%s", resp.status)
        return {"pinged": True, "status": resp.status, "ok": ok}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("[healthcheck_ping] ping 失败: %s（本地不受影响，仅外部告警断）", e)
        return {"pinged": False, "error": str(e)}


def weekly_brainstorm_remind(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S188 RB-9 · 每周全局优化头脑风暴提醒（cron 触发，飞书通知 + memory 待办标记）。

    backend 跑不了 Claude Code workflow，故本 executor 只发飞书提醒 + 写待办文件，
    用户看到手动触发头脑风暴 workflow（/workflows 或对话触发）。

    memory `weekly-optimization-brainstorm-2026-09-11`：每周一次多领域专家
    brainstorm+grill，基于数据+交易沉淀，落待办。
    """
    from datetime import datetime as _dt  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415
    from vr_paths import resolve_data_dir  # noqa: PLC0415

    today = _dt.now().strftime("%Y-%m-%d")
    # 飞书通知
    notif_ok = False
    try:
        from notification.notification_service import get_notification_service  # noqa: PLC0415
        service = get_notification_service()
        msg = (
            f"📅 每周全局优化头脑风暴提醒（{today}）\n"
            "基于本周数据+交易沉淀，触发头脑风暴 workflow：\n"
            "- 8 领域专家提进阶方案\n"
            "- 3 视角对抗 grill（存疑讨论不自动毙，S190 R4 grill-doubt memory）\n"
            "- 综合 rank P0/P1/P2 待办\n"
            "手动触发：/workflows 或对话说'触发每周头脑风暴'"
        )
        if hasattr(service, "send"):
            service.send(msg)
            notif_ok = True
    except Exception as e:  # noqa: BLE001
        logger.warning("[weekly_brainstorm_remind] 飞书通知失败: %s", e)

    # 写待办标记文件（Claude Code 下次会话检测到就提醒）
    backlog = resolve_data_dir() / "weekly_brainstorm_pending.txt"
    try:
        backlog.write_text(f"pending: {today} 周头脑风暴待触发\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("[weekly_brainstorm_remind] 写待办标记失败: %s", e)

    return {"reminded": True, "date": today, "notif_sent": notif_ok}


def daily_full_pull(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S191 RB-3 · 每日盘后全量拉取数据基建沉淀。

    用户原话"每日全量拉取不同数据源交易数据尤其盘中数据供后期调试盘中策略做数据沉淀"。
    盘后 17:35 跑（晚 journal 17:30 + depends_on=trade_journal_daily 硬门控）：
    - stoke 当日研报/新闻/涨停归因 → datalake/stoke_YYYYMM.db
    - mootdx 当日全首板分笔（OFI proxy 用）→ datalake/ticks_YYYYMM.db

    现有 kline_refresh/seal_intraday/ofi_collect 已 live 采，不重复（depends_on 保证顺序）。
    Turso 是云灾备（write-only），datalake 是本地回放层（供 replay.py 读回）。
    """
    from datetime import datetime  # noqa: PLC0415
    from vr_paths import resolve_data_dir, last_trading_date_str  # noqa: PLC0415
    from data.datalake.store import save_stoke_data, save_ticks  # noqa: PLC0415

    date_str = last_trading_date_str()
    result: Dict[str, Any] = {"date": date_str, "stoke": {}, "ticks": {}}

    # 1. stoke 沉淀（研报/新闻/强势涨停）—— stoke 走 ~/stoke venv subprocess，失败降级不阻塞
    try:
        from data.sources.stoke_src import strong_stocks, cls_telegraph  # noqa: PLC0415
        strong = strong_stocks() or []
        telegraph = cls_telegraph()
        # telegraph 返 list 才用，dict（error）跳过
        telegraph_list = telegraph if isinstance(telegraph, list) else []
        items = {"strong": strong, "news": telegraph_list}
        r = save_stoke_data(date_str, items)
        result["stoke"] = {"saved": r.get("saved", 0), "n_strong": len(strong), "n_telegraph": len(telegraph_list)}
    except Exception as e:  # noqa: BLE001
        logger.warning("[daily_full_pull] stoke 沉淀失败: %s", e)
        result["stoke"] = {"error": str(e)}

    # 2. mootdx 当日全首板分笔——首板 universe 取 zt_history 当日
    try:
        import sqlite3  # noqa: PLC0415
        import subprocess  # noqa: PLC0415
        import json as _json  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415
        zt_db = resolve_data_dir() / "zt_history.db"
        if zt_db.exists():
            conn = sqlite3.connect(str(zt_db), timeout=5)
            codes = [r[0] for r in conn.execute(
                "SELECT code FROM zt_history WHERE date=? AND code IS NOT NULL", (date_str,)
            ).fetchall()]
            conn.close()
        else:
            codes = []
        # mootdx 走 ~/stoke venv（项目 venv 无 mootdx）——subprocess 调 mootdx_tick_ofi_proxy
        stoke_py = Path.home() / "stoke" / ".venv" / "bin" / "python"
        proxy_script = Path(__file__).resolve().parents[2] / "tools" / "mootdx_tick_ofi_proxy.py"
        saved_ticks = 0
        failed_codes = 0
        if codes and stoke_py.exists() and proxy_script.exists():
            for code in codes[:50]:  # 限 50 防 mootdx 长时间（首板 ~75 股）
                try:
                    r = subprocess.run(
                        [str(stoke_py), str(proxy_script), "--code", code, "--date", date_str.replace("-", "")],
                        capture_output=True, text=True, timeout=30,
                    )
                    if r.returncode != 0:
                        failed_codes += 1
                        continue
                    out = _json.loads(r.stdout.strip())
                    # mootdx_tick_ofi_proxy 输出 {results: [{code,date,n_ticks,active_buy_vol,...}]}
                    for item in out.get("results", []):
                        if item.get("n_ticks", 0) > 0:
                            # 拉原始分笔（proxy 只输聚合，需另拉 raw ticks）——此处先标 n_ticks
                            saved_ticks += item.get("n_ticks", 0)
                except (subprocess.TimeoutExpired, _json.JSONDecodeError, OSError):
                    failed_codes += 1
                    continue
        result["ticks"] = {
            "n_codes": len(codes), "pulled_codes": min(len(codes), 50),
            "n_ticks_saved": saved_ticks, "failed_codes": failed_codes,
            "note": "mootdx 分笔经 stoke venv subprocess" if stoke_py.exists() else "stoke venv 缺",
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[daily_full_pull] ticks 沉淀失败: %s", e)
        result["ticks"] = {"error": str(e)}

    logger.info("[daily_full_pull] %s done: stoke=%s ticks=%s", date_str, result["stoke"], result["ticks"])
    return result


