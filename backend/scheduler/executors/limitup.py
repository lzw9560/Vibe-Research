# -*- coding: utf-8 -*-
"""limitup executors——涨停预计算/STI 盘后/涨停历史快照/ST radar/derived 预计算。"""
from __future__ import annotations

import asyncio
import logging
from datetime import date as _date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("vibe-research")


def limitup_precompute(payload: Dict[str, Any]) -> Dict[str, Any]:
    """盘后预计算：涨停板基因得分 + STI + 竞价选股 + 复盘报告。"""
    import limitup_screener as _ls
    import limitup_sti as _ls_sti
    import auction_screener as _asc
    import daily_review as _dr

    results: Dict[str, Any] = {}
    back_days = int(payload.get("back_days", 3))

    # 异步预计算逻辑在线程中运行
    async def _precompute_async() -> None:
        # 交易日守卫（P1·日期语义完整性第4通道）：本闭包按自然日回溯遍历，
        # 非交易日（周末/节假日）下调东财相关接口会因静默回退拿到最近交易日数据，
        # 错位入库。daily_review.generate_review 现对非交易日抛 ValueError，
        # 跳过非交易日还能避免异常日志。统一用 vr_paths.is_trading_day 判断。
        from vr_paths import is_trading_day as _is_trading_day  # noqa: PLC0415

        for back in range(back_days):
            d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
            if not _is_trading_day(datetime.strptime(d, "%Y-%m-%d").date()):
                logger.info("[limitup_precompute] %s 非交易日，跳过涨停板基因得分预计算", d)
                continue
            await _ls.get_screener_result(d)

        try:
            engine = _ls_sti.get_sti_engine()
            for back in range(back_days):
                d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                if not _is_trading_day(datetime.strptime(d, "%Y-%m-%d").date()):
                    continue
                await asyncio.to_thread(engine.precompute_daily, d)
        except Exception as e:
            logger.warning("[limitup_precompute] STI 预计算失败: %s", e)

        try:
            screener = _asc.get_screener()
            for back in range(back_days):
                d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                if not _is_trading_day(datetime.strptime(d, "%Y-%m-%d").date()):
                    continue
                await asyncio.to_thread(screener.precompute_daily, d)
        except Exception as e:
            logger.warning("[limitup_precompute] 竞价选股预计算失败: %s", e)

        try:
            reviewer = _dr.get_reviewer()
            for back in range(back_days):
                d = (datetime.now(_ls.BEIJING_TZ) - timedelta(days=back)).strftime("%Y-%m-%d")
                if not _is_trading_day(datetime.strptime(d, "%Y-%m-%d").date()):
                    continue
                await asyncio.to_thread(reviewer.precompute_daily, d)
        except Exception as e:
            logger.warning("[limitup_precompute] 复盘报告预计算失败: %s", e)

    try:
        asyncio.run(asyncio.wait_for(_precompute_async(), timeout=600))
        results["status"] = "ok"
    except Exception as e:
        logger.warning("[limitup_precompute] 预计算失败: %s", e)
        results["status"] = f"error: {e}"

    return results


def sti_post_market(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S063 T3：STI 盘后定时计算——交易日 15:30 触发。

    调 `market._emotion(T)` + `market._sentiment(T)` → `engine.compute()` →
    `save_result()` 持久化到 sti_timeline → 成为 T+1 的硬标准（SentimentContext
    读取 T-1 行的来源）。

    payload 可选 `date`（YYYY-MM-DD）用于补算历史日；缺省=今天。
    """
    import market as _market
    from limitup_sti.service import get_sti_engine
    from vr_paths import last_trading_date_str

    target = payload.get("date") or last_trading_date_str()
    results: Dict[str, Any] = {"date": target}

    try:
        emotion_data = _market._emotion(target)
        if not emotion_data:
            results["status"] = "no_emotion_data"
            logger.warning("[sti_post_market] %s 情绪数据未取得（非交易日或采集失败）", target)
            return results

        sentiment_data = _market._sentiment(target) or {}
        engine = get_sti_engine()
        sti_result = engine.compute(emotion_data, sentiment_data)

        results["status"] = "ok" if sti_result.source_ok else "source_fail"
        results["sti_score"] = sti_result.score
        results["sti_phase"] = sti_result.phase.value if sti_result.phase else None
        results["source_date"] = target
        logger.info(
            "[sti_post_market] %s STI 计算完成：score=%s phase=%s",
            target, sti_result.score,
            sti_result.phase.value if sti_result.phase else None,
        )
        # S065：STI 成功后落 weather_history 快照（失败不阻断主流程）
        try:
            from routers.sentiment_weather import compute_weather_snapshot
            from weather_history import save_weather_snapshot
            snapshot = compute_weather_snapshot(target)
            if snapshot.get("data_status") == "ok":
                save_weather_snapshot(snapshot)
                logger.info(
                    "[sti_post_market] %s weather_history 快照已落库：%s",
                    target, snapshot.get("weather_state"),
                )
        except Exception as we:
            logger.warning("[sti_post_market] weather_history 落库失败（不阻断）: %s", we)
    except Exception as e:
        logger.exception("[sti_post_market] STI 计算失败: %s", e)
        results["status"] = f"error: {e}"

    return results


def zt_history_snapshot(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S078 涨停历史 snapshot——盘后 snapshot 当日涨停池 → zt_history.db（不 prune 累积）。

    数据地基：涨停池历史 >1 月无源（em/ths/akshare 均 ~1 月），每日累积供长窗 §44 复验。
    失败 catch 不抛，返 error（采集是增强，不阻塞主流程）。

    **每日唯一 + final 标记（2026-08-23 落地）**：
    is_final 按采集时点（北京时间）判定——>= 17:15 → True（东财池已稳定终盘），
    < 17:15 → False（中间快照，可被后续 final 覆盖）。final 一旦落定不可被非 final 覆盖。
    """
    try:
        from data.zt_history_store import snapshot_zt_pool
        from vr_paths import last_trading_date_str
        target = payload.get("date") or last_trading_date_str()
        # 采集时点判定：北京时间 17:15 后视为终盘稳定版（东财涨停池盘后持续收缩，
        # 17:15 后已稳定）。dateutil 不可用则回退 zoneinfo（3.9+ stdlib）。
        import datetime as _dt
        try:
            from zoneinfo import ZoneInfo
            now_bj = _dt.datetime.now(ZoneInfo("Asia/Shanghai"))
        except Exception:  # noqa: BLE001
            now_bj = _dt.datetime.now()  # fallback：无 tz 信息，按本地（开发机通常 CST）
        is_final = now_bj.hour > 17 or (now_bj.hour == 17 and now_bj.minute >= 15)
        written = snapshot_zt_pool(target, is_final=is_final)
        logger.info("[zt_history_snapshot] %s 涨停池 snapshot 写入 %s 行 (is_final=%s)",
                    target, written, is_final)
        return {"date": target, "written": written, "is_final": is_final, "status": "ok"}
    except Exception as e:
        logger.warning("[zt_history_snapshot] 采集失败: %s", e)
        return {"status": f"error: {e}"}


def st_play_radar(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S148 R3：盘后 ST-play radar——扫 ST 股公告 → 摘帽/重组/扭亏 白名单 → st_play_radar.json。

    供 classify_tradability 做 ST carve-out（re-include + st_play 标）。失败 catch 不抛，
    返 error（radar 是增强；失败则 loader 返空→ST flat 排除，安全降级，不阻断主流程）。
    """
    try:
        from candidate_funnel.sources.st_play_radar import run_st_play_radar  # noqa: PLC0415
        radar = run_st_play_radar()
        logger.info("[st_play_radar] 白名单写入 %s 只（摘帽/重组/扭亏）", len(radar))
        return {"count": len(radar), "status": "ok"}
    except Exception as e:
        logger.warning("[st_play_radar] 采集失败: %s", e)
        return {"status": f"error: {e}"}


def derived_precompute(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S084 C2：17:00 盘后异步预采集——对昨日涨停股全量算 derived 落 seal_derived_features 表。

    取 yesterday（默认 last_trading_date(today-1)，与 funnel 的 yesterday_date 同口径）→
    zt_pool_source.fetch_zt_pool_map(yesterday) 取昨日涨停 codes → 对每只
    get_snapshots_by_code(code, yesterday) + compute_derived_features →
    persist_derived_features 写 seal_derived_features(date=yesterday)。选股池
    derived_source 后续读 seal_derived_features（不 per-code 实时算）。

    缺快照 / data_status='missing' → 跳过（不臆造）。单只失败不阻塞其余（catch 跳过）。
    整体失败 catch 不抛，返 status=error（预采集是增强，不阻塞主流程）。
    S084 follow-up：原 derived_results 表合并入 seal_derived_features（字段子集），
    复用 persist_derived_features 持久化（DRY，与盘中 collect 同写路径）。
    """
    from datetime import date as _date, timedelta as _td
    from vr_paths import last_trading_date as _last_td

    try:
        from candidate_funnel.sources import zt_pool_source
        from risk.seal_intraday_collector import (
            run_migrations, get_snapshots_by_code, _get_conn, _DB_LOCK,
        )
        from strategies.intraday_features import (
            compute_derived_features, persist_derived_features,
        )
    except Exception as e:
        logger.warning("[derived_precompute] 依赖导入失败: %s", e)
        return {"status": f"error: {e}"}

    # yesterday：与 funnel._run_funnel_impl 同口径（last_trading_date(today-1)），
    # payload.get("date") 允许指定回填昨日日期。
    yesterday = payload.get("date") or _last_td(_date.today() - _td(days=1)).isoformat()

    # 幂等建表（fresh env 自愈；已应用则 no-op），避免 seal_derived_features 缺表致写失败
    try:
        run_migrations()
    except Exception as e:
        logger.warning("[derived_precompute] 迁移失败（继续，首行写可能失败）: %s", e)

    try:
        zt_map = zt_pool_source.fetch_zt_pool_map(yesterday)
    except Exception as e:
        logger.warning("[derived_precompute] %s 涨停池取数失败: %s", yesterday, e)
        return {"date": yesterday, "status": f"error: {e}", "codes": 0, "written": 0}

    codes = list(zt_map.keys())
    if not codes:
        logger.info("[derived_precompute] %s 昨日涨停池为空（非交易日或采集失败）", yesterday)
        return {"date": yesterday, "status": "ok", "codes": 0, "written": 0, "skipped": 0}

    written = 0
    skipped = 0
    conn = _get_conn()
    try:
        with _DB_LOCK:
            for code in codes:
                try:
                    snaps = get_snapshots_by_code(code, yesterday)
                    if not snaps:
                        skipped += 1
                        continue  # 缺快照跳过，不臆造
                    derived = compute_derived_features(snaps)
                    if derived.get("data_status") == "missing":
                        skipped += 1
                        continue
                    # 复用 persist_derived_features 写 seal_derived_features
                    # （INSERT OR REPLACE 幂等，同 (date,code) 重跑覆盖；S084 follow-up：
                    #   合并自 derived_results，DRY 复用战法层持久化函数，与盘中 collect 同路径）
                    name = (zt_map.get(code) or {}).get("n")
                    persist_derived_features(yesterday, code, name, derived, conn)
                    written += 1
                except Exception as exc:
                    logger.warning(
                        "[derived_precompute] %s %s 派生落库失败（跳过）: %s",
                        yesterday, code, exc,
                    )
                    skipped += 1
            conn.commit()
    finally:
        conn.close()

    logger.info(
        "[derived_precompute] %s derived 预采集完成：涨停%s/写入%s/跳过%s",
        yesterday, len(codes), written, skipped,
    )
    return {"date": yesterday, "status": "ok", "codes": len(codes),
            "written": written, "skipped": skipped}
