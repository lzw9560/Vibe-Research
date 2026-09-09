# -*- coding: utf-8 -*-
"""first_board executors——首板筛选/T+1 复盘/行情探查。"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger("vibe-research")


def first_board_filter(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S075 盘后首板流筛选——首板过滤+三层剔除+9维度评分+落盘。

    取 date（默认最近交易日）→ run_first_board_filter → 候选池+评分存快照。
    失败 catch 不抛，返 status=error（筛选是增强，不阻塞主流程）。
    """
    try:
        from strategies.first_board_filter import run_first_board_filter
        from vr_paths import last_trading_date_str
        target = payload.get("date") or last_trading_date_str()
        result = run_first_board_filter(target)
        logger.info("[first_board_filter] %s 首板流筛选完成：涨停%s/首板%s/候选%s",
                    target, result["zt_pool_count"], result["first_board_count"],
                    len(result["candidates"]))
        return {
            "date": target,
            "status": "ok",
            "zt_pool_count": result["zt_pool_count"],
            "first_board_count": result["first_board_count"],
            "candidate_count": len(result["candidates"]),
        }
    except Exception as e:
        logger.warning("[first_board_filter] 筛选失败: %s", e)
        return {"status": f"error: {e}"}


def first_board_t1_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S075 T+1 溢价评分 + 复盘报告 + 飞书通知（盘后对 T-1 候选做收益评价）。

    流程：
    1. 取 T-1（最近有快照的交易日）候选
    2. 跑 run_t1_premium_review：baostock T 日 K 线算标的收益 + lift 四态判定
    3. build_review_report 构造 Markdown 复盘报告
    4. 飞书推送（NotificationService，route_type=alert/severity=info）

    无快照 / 无 T+1 数据 / 通道未配 → 不崩，返对应状态。
    失败 catch 不抛，返 status=error（评价是增强，不阻塞主流程）。
    """
    try:
        from strategies.first_board_settlement import (
            run_t1_premium_review,
            build_review_report,
        )
        from strategies.first_board_filter import list_score_dates
        from notification.notification_service import NotificationService

        # 取 T-1：优先用 payload.date，否则取最近的快照日
        signal_date = payload.get("date") if payload else None
        if not signal_date:
            dates = list_score_dates()
            if not dates:
                return {"status": "error", "msg": "无历史快照"}
            signal_date = dates[0]  # 最近的快照日

        # 跑 T+1 评价
        review = run_t1_premium_review(signal_date)
        report = build_review_report(review)

        # 飞书推送
        ns = NotificationService()
        notified = False
        if ns.is_available():
            notified = ns.send(report, route_type="alert", severity="info")

        stats = review.get("stats", {}) if not review.get("error") else {}
        logger.info(
            "[first_board_t1_review] %s 候选%d 只 mean=%s%% notified=%s verdict=%s",
            signal_date,
            stats.get("n", 0),
            stats.get("mean_return_pct", 0),
            notified,
            review.get("verdict", review.get("error", "")),
        )
        return {
            "signal_date": signal_date,
            "status": "ok",
            "candidates": stats.get("n", 0),
            "mean_return": stats.get("mean_return_pct", 0),
            "verdict": review.get("verdict", ""),
            "error": review.get("error"),
            "notified": notified,
        }
    except Exception as e:
        logger.warning("[first_board_t1_review] 失败: %s", e)
        return {"status": f"error: {e}"}


def first_board_quote_probe(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S076 盘中多源行情探查——9:20-9:36 每分钟探 tencent/mootdx/东财 push2。

    临时研究任务：产出 .scratch/s076-quote-probe/matrix_{date}.json，收 3-5 个交易日稳定
    结论后 disable。东财 push2 ≥10min 状态文件门控（R6 限流，per-minute cron 跨进程用文件持久化）。
    需 app 进程在 9:20-9:36 运行（无 catch-up，错过即缺）。失败 catch 不抛，返 error。
    """
    try:
        from tools.first_board_quote_source_probe import (
            probe_once, _append_row, OUT_DIR, EM_PUSH2_MIN_INTERVAL_S, DEFAULT_CODES,
        )
        import time as _time
        import json as _json

        codes = [c for c in (payload.get("codes") or DEFAULT_CODES) if c]

        # 东财 push2 ≥10min 状态文件门控（per-minute cron 跨进程，用文件持久化上次时间）
        state_path = OUT_DIR / "push2_state.json"
        last_push2 = 0.0
        try:
            if state_path.exists():
                last_push2 = float(
                    _json.loads(state_path.read_text(encoding="utf-8")).get("last_push2_ts", 0.0)
                )
        except Exception:
            last_push2 = 0.0

        srcs = ["tencent", "mootdx"]
        if _time.time() - last_push2 >= EM_PUSH2_MIN_INTERVAL_S:
            srcs.append("em_push2")

        row = probe_once(codes, sources=srcs)
        path = _append_row(row)

        if "em_push2" in srcs:
            try:
                OUT_DIR.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    _json.dumps({"last_push2_ts": _time.time()}), encoding="utf-8"
                )
            except Exception as e:
                logger.warning("[first_board_quote_probe] push2 状态写失败: %s", e)

        return {
            "time": row.get("time"),
            "sources": srcs,
            "codes": codes,
            "matrix_path": str(path),
            "tencent_ok": row.get("tencent", {}).get("ok"),
            "mootdx_ok": row.get("mootdx", {}).get("ok"),
            "em_push2_ok": row.get("em_push2", {}).get("ok") if "em_push2" in row else None,
        }
    except Exception as e:
        logger.warning("[first_board_quote_probe] 探查失败: %s", e)
        return {"status": f"error: {e}"}
