# -*- coding: utf-8 -*-
"""premarket executors——9:25 竞价通知 / 9:35 开盘通知 / T+1 复盘通知。

依赖 scheduler.notifications 模块的函数——通过模块对象引用（非直接 import 函数名），
以便测试 monkeypatch ``scheduler.notifications._load_final_cards`` 等能生效。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from scheduler import notifications as _notif

logger = logging.getLogger("vibe-research")


def premarket_auction_notify(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S101：9:25 竞价确认——P1 降噪(2026-11-05)：常态日竞价表现合并到 09:35 open_notify（同标的 10 分钟 2 推→1）。

    常态日：不推竞价表现（open_notify 09:35 推开盘表现更全，gap 用户可查）。
    kill_switch triggered：仍推含竞价+警告（保护钱信号不降噪）。

    读 F 日 funnel_cache final_candidates → tencent_quote → gap_pct。
    S136：开盘后实时核 kill_switch——triggered 时「不开新仓」熔断警告。
    """
    try:
        from vr_paths import prev_trading_date_str

        f_date = payload.get("date") or prev_trading_date_str()
        final_cards = _notif._load_final_cards(f_date)
        if not final_cards:
            logger.info("[premarket_auction_notify] %s 无 final_candidates，跳过", f_date)
            return {"date": f_date, "status": "ok", "notified": False, "reason": "no_candidates"}

        ks = _notif._check_premarket_kill_switch()  # S136：开盘后实时核
        if not ks["triggered"]:
            # P1 降噪：常态日竞价表现合并到 09:35 open_notify，不推
            logger.info(
                "[premarket_auction_notify] %s 候选%d 常态不推（合并到 open_notify 09:35）kill_switch=%s",
                f_date,
                len(final_cards),
                ks["triggered"],
            )
            return {
                "date": f_date,
                "status": "ok",
                "candidates": len(final_cards),
                "notified": False,
                "kill_switch": ks,
                "note": "P1降噪: 竞价表现合并到09:35 open_notify，仅 kill_switch 触发时推",
            }

        # kill_switch triggered：推含竞价表现 + 警告（保护钱信号不降噪）
        codes = [c.get("code") for c in final_cards if c.get("code")]
        quotes = _notif._fetch_quotes(codes)
        content = _notif._build_auction_notify_content(f_date, final_cards, quotes)
        content = _notif._prepend_kill_switch_warning(content, ks)
        notified = _notif._send_notify(content)
        logger.info(
            "[premarket_auction_notify] %s 候选%d notified=%s kill_switch=%s (触发推警告)",
            f_date,
            len(final_cards),
            notified,
            ks["triggered"],
        )
        return {"date": f_date, "status": "ok", "candidates": len(final_cards), "notified": notified, "kill_switch": ks}
    except Exception as e:
        logger.warning("[premarket_auction_notify] 失败: %s", e)
        return {"status": f"error: {e}"}


def premarket_open_notify(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S101：9:35 开盘 5min 后推送前瞻标的开盘表现（现价/涨跌幅/封板）。

    S136：开盘后实时核 kill_switch（market_note 承诺落地）——triggered 时通知前置
    「不开新仓」熔断警告。
    """
    try:
        from vr_paths import prev_trading_date_str

        f_date = payload.get("date") or prev_trading_date_str()
        final_cards = _notif._load_final_cards(f_date)
        if not final_cards:
            logger.info("[premarket_open_notify] %s 无 final_candidates，跳过", f_date)
            return {"date": f_date, "status": "ok", "notified": False, "reason": "no_candidates"}

        codes = [c.get("code") for c in final_cards if c.get("code")]
        quotes = _notif._fetch_quotes(codes)
        content = _notif._build_open_notify_content(f_date, final_cards, quotes)
        ks = _notif._check_premarket_kill_switch()  # S136：开盘后实时核
        if ks["triggered"]:
            content = _notif._prepend_kill_switch_warning(content, ks)
        notified = _notif._send_notify(content)
        logger.info(
            "[premarket_open_notify] %s 候选%d notified=%s kill_switch=%s",
            f_date,
            len(final_cards),
            notified,
            ks["triggered"],
        )
        return {"date": f_date, "status": "ok", "candidates": len(final_cards), "notified": notified, "kill_switch": ks}
    except Exception as e:
        logger.warning("[premarket_open_notify] 失败: %s", e)
        return {"status": f"error: {e}"}


def premarket_t1_review(payload: Dict[str, Any]) -> Dict[str, Any]:
    """S101：T+1 复盘——前瞻标的（F 日 final_candidates）在 T 日（F 下一交易日）收益。

    baostock_kline_cache 取 T 日 close vs F 日 close（close2close 口径，简化；open2close
    见 first_board_settlement 但需 T 日 open，baostock 当日 bar 16:35 可能未更新，故用 close2close）。
    §44 口径：n<30 标样本不足 / 不宣称 alpha / lift<2x 标无 validated edge。
    """
    try:
        from vr_paths import prev_trading_date_str, next_trading_date
        from datetime import date as _date

        f_date = payload.get("date") or prev_trading_date_str()
        final_cards = _notif._load_final_cards(f_date)
        if not final_cards:
            logger.info("[premarket_t1_review] %s 无 final_candidates，跳过", f_date)
            return {"date": f_date, "status": "ok", "notified": False, "reason": "no_candidates"}

        t_date = next_trading_date(_date.fromisoformat(f_date)).isoformat()
        returns = _notif._compute_t1_returns(final_cards, f_date, t_date)
        content = _notif._build_t1_review_content(f_date, t_date, returns)
        notified = _notif._send_notify(content)
        n = len(returns)
        logger.info("[premarket_t1_review] %s→%s n=%d notified=%s", f_date, t_date, n, notified)
        return {
            "f_date": f_date,
            "t_date": t_date,
            "status": "ok",
            "candidates": n,
            "notified": notified,
        }
    except Exception as e:
        logger.warning("[premarket_t1_review] 失败: %s", e)
        return {"status": f"error: {e}"}
