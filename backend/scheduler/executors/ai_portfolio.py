# -*- coding: utf-8 -*-
"""ai_portfolio executors——AI 总结/持仓刷新/漏斗预计算/复盘通知。

依赖 scheduler.notifications 模块的函数——通过模块对象引用（非直接 import 函数名），
以便测试 monkeypatch ``scheduler.notifications._compute_*`` 等能生效。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict

from scheduler import notifications as _notif

logger = logging.getLogger("vibe-research")


def daily_ai_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S093 R12：AI 盘后总结 stub（cron 15:30，与 stage 推进点 15:30 对齐）。

    S094 完整实现：LLM 汇总当日信号 + 持仓表现 + 市场数据，生成
    "今日操作回顾 + 明日建议"自然语言总结。本 stub 调 generate_daily_summary
    返空串 + 落存储位（.vibe-research/daily_summaries/{date}.txt）。
    """
    from vr_paths import last_trading_date_str

    target = payload.get("date") or last_trading_date_str()
    summary = _notif.generate_daily_summary(target)
    return {
        "date": target,
        "status": "ok",
        "summary_length": len(summary),
        "note": "S094 TODO：AI 盘后总结 stub，返空串",
    }


def portfolio_refresh(payload: Dict[str, Any]) -> Dict[str, Any]:
    """刷新持仓数据。"""
    import portfolio as pf

    results: Dict[str, Any] = {}
    try:
        pf.refresh_all()
        results["portfolio"] = "ok"
    except Exception as e:
        logger.warning("[portfolio_refresh] 持仓刷新失败: %s", e)
        results["portfolio"] = f"error: {e}"

    return results


def candidate_funnel_precompute(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S004 R5：盘后漏斗预计算——预热 _FUNNEL_CACHE，盘后复盘页即时读缓存。

    取 date（默认最近交易日）→ run_funnel("all", date, live_config) →
    结果落 _FUNNEL_CACHE（TTL 由 config.CANDIDATE_FUNNEL_CACHE_TTL 控制，默认 3600s）。
    失败 catch 不抛，返 status=error（预计算是增强，不阻塞主流程）。

    S093 R10：success 后调 NotificationService.send() 发富内容卡片
    （F 日期 + final_candidates 数 + 双重确认数 + top5 标的），扩返候选统计。
    通知失败不阻断预计算（增强，catch 不抛）。
    """
    try:
        from candidate_funnel import funnel as funnel_mod
        from candidate_funnel.models import ThresholdConfig
        from vr_paths import last_trading_date_str
        target = payload.get("date") or last_trading_date_str()
        # 复用 candidates 路由的 live config（用户调参后一致）
        try:
            from routers.candidates import _store
            cfg = _store["config"]
            if not isinstance(cfg, ThresholdConfig):
                cfg = ThresholdConfig(**cfg) if isinstance(cfg, dict) else ThresholdConfig()
        except Exception:
            cfg = ThresholdConfig()
        result = funnel_mod.run_funnel("all", target, cfg)
        # S087 R10：落库 funnel_cache（前端 tab 读缓存秒开，进程重启不丢）
        from candidate_funnel.funnel_cache import save_funnel_result
        save_funnel_result(target, "all", result)

        # S093 R10：final_candidates 诊断卡 + 双重确认 + 战法映射
        final_cards: list[dict] = []
        try:
            final_cards = [c.model_dump(mode="json") for c in result.final_candidates]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[candidate_funnel_precompute] final_cards 构建失败: %s", exc)

        dual_count = _notif._compute_dual_confirmation(target, final_cards)
        strategy_map = _notif._compute_strategy_map(target)

        # S093 R10：发飞书富内容卡片（直接调 NotificationService.send()，
        # 不走 _send_notification——后者只产固定格式任务状态文本，不支持富内容）
        # final_candidates=0 时不发通知（数据未就绪时漏斗空，推"0 只"误导用户；
        # 根因：cron 若抢在 gene_scores 写入前跑则 R1 宽源输入 0，见 cron 17:15 修订）
        if final_cards:
            try:
                from notification.notification_service import NotificationService
                content = _notif._build_premarket_notification_content(
                    target, final_cards, dual_count, strategy_map,
                )
                ns = NotificationService()
                if ns.is_available():
                    ns.send(content, route_type="alert", severity="info")
                    logger.info("[candidate_funnel_precompute] 飞书通知已发送（%d 候选）", len(final_cards))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[candidate_funnel_precompute] 飞书通知发送失败: %s", exc)
        else:
            logger.warning(
                "[candidate_funnel_precompute] final_candidates=0，跳过飞书通知"
                "（数据未就绪或漏斗空；cron 17:15 应在 gene_scores 写入后）"
            )

        logger.info("[candidate_funnel_precompute] %s 漏斗预计算完成（缓存已预热+落库）", target)
        # S148：顺手触发 briefing _collect——precompute 写 funnel_cache 但 briefing 端点不读它，
        # 须 _collect 采集才让选股页显数据（fire-and-forget，主 loop 后台跑，不阻塞 executor）。
        try:
            from routers.workflow import trigger_collect  # noqa: PLC0415
            triggered = trigger_collect(target)
            logger.info(
                "[candidate_funnel_precompute] briefing _collect %s（target=%s；实际采集由 dedup status=running 决定）",
                "已调度到主 loop" if triggered else "跳过（主 loop 未设/已关）", target,
            )
        except Exception as exc:  # noqa: BLE001 — briefing 触发失败不阻断 precompute 主流程
            logger.warning("[candidate_funnel_precompute] briefing _collect 触发失败: %s", exc)
        return {
            "date": target,
            "status": "ok",
            "final_candidates_count": len(final_cards),
            "dual_confirmation_count": dual_count,
        }
    except Exception as e:
        logger.warning("[candidate_funnel_precompute] 预计算失败: %s", e)
        return {"status": f"error: {e}"}


def daily_review_notify(payload: Dict[str, Any]) -> Dict[str, Any]:
    """每日复盘通知：生成报告并推送。"""
    import daily_review as dr
    from notification.notification_service import get_notification_service, send_daily_report

    today = datetime.now().strftime("%Y-%m-%d")
    reviewer = dr.get_reviewer()
    report = reviewer.generate_review(today)

    results: Dict[str, Any] = {}
    try:
        service = get_notification_service()
        md = service.generate_daily_report([report.model_dump()])
        service.save_report_to_file(md)
        sent = service.send(md)
        results["sent"] = sent
        results["channels"] = len(service._available_channels) if hasattr(service, "_available_channels") else 0
    except Exception as e:
        logger.warning("[daily_review_notify] 通知发送失败: %s", e)
        results["error"] = str(e)

    return results
