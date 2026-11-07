# -*- coding: utf-8 -*-
"""sentiment_commander executor——情绪指挥官 cron 任务（S234 Phase 3）。

morning (09:15): 情绪诊断+仓位+飞书推送（开盘前）
close (14:50): 尾盘排雷+飞书推送（沸点期 score>70 才触发 filter）

复用 commander_runner.run()（不重造），executor 是 cron 适配层。
§44 v3 R26：情绪得分透明（fetcher 脚本化非黑箱）
§44 v3 R30：仓位附 verdict 诚实标注
"""

from __future__ import annotations
import logging
import sys
from pathlib import Path
from typing import Any, Dict

# 加 tools 到 path（commander_runner 在 backend/tools/）
_TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

logger = logging.getLogger("vibe-research")


def _run_commander(payload: Dict[str, Any]) -> Dict[str, Any]:
    """跑 commander_runner.run() + format + push_feishu，返回 status dict。

    commander_runner 已含：情绪诊断 + 仓位分配 + 沸点期排雷(score>70) + 飞书推送。
    executor 只做 cron 适配 + status 映射。
    """
    try:
        from commander_runner import run as commander_run, format_text, push_feishu

        r = commander_run()
        text = format_text(r)
        push_feishu(text)
        n_tactics = len(r.get("tactics_filter_results", []))
        result: Dict[str, Any] = {
            "status": "ok",
            "score": r.get("score"),
            "state": r.get("state"),
            "trade_date": r.get("trade_date"),
            "tactics_filter_count": n_tactics,
        }
        if r.get("tactics_filter_error"):
            result["tactics_filter_error"] = r["tactics_filter_error"]
            # 沸点期排雷失败但主流程成功 → degraded 非failed
            result["status"] = "degraded"
        return result
    except Exception as e:
        logger.exception("[sentiment_commander] 执行失败")
        return {"status": "error", "error": str(e)}


def sentiment_commander_morning(payload: Dict[str, Any]) -> Dict[str, Any]:
    """09:15 开盘前情绪诊断 + 仓位 + 飞书推送。

    早于 premarket_auction_notify(9:25)，给用户开盘前情绪+仓位+verdict。
    """
    logger.info("[sentiment_commander] morning 09:15 触发（开盘前诊断）")
    return _run_commander(payload)


def sentiment_commander_close(payload: Dict[str, Any]) -> Dict[str, Any]:
    """14:50 尾盘——仅沸点期(score>70)推飞书，常态日 close 与 morning 内容重复不推（P1 降噪 2026-11-05）。

    尾盘 14:50 比 9:25 sound（避 9:15-9:20 虚假封单 + 9:25-9:30 量化反向收割）。
    commander_runner 内部已判断 score>70 才调 filter（排雷）。
    通知层 P1 降噪：常态日 close 情绪复盘与 morning 几乎一样→不推；沸点期(score>70)排雷+情绪更新才推。
    """
    logger.info("[sentiment_commander] close 14:50 触发（仅沸点期推，常态降噪）")
    try:
        from commander_runner import run as commander_run, format_text, push_feishu

        r = commander_run()
        score = r.get("score", 0)
        n_tactics = len(r.get("tactics_filter_results", []))
        result: Dict[str, Any] = {
            "status": "ok",
            "score": score,
            "state": r.get("state"),
            "trade_date": r.get("trade_date"),
            "tactics_filter_count": n_tactics,
            "pushed": False,
        }
        if r.get("tactics_filter_error"):
            result["tactics_filter_error"] = r["tactics_filter_error"]
            result["status"] = "degraded"
        if score and score > 70:
            text = format_text(r)
            push_feishu(text)
            result["pushed"] = True
            logger.info("[sentiment_commander] close 推送（沸点期 score=%s）", score)
        else:
            logger.info("[sentiment_commander] close 跳过推送（常态 score=%s≤70，与 morning 重复）", score)
        return result
    except Exception as e:
        logger.exception("[sentiment_commander] close 执行失败")
        return {"status": "error", "error": str(e)}
