# -*- coding: utf-8 -*-
"""通知内容构建 + generate_daily_summary。

S093 R10/R12 + S101 飞书多点通知（9:25 竞价 / 9:35 开盘 / T+1 复盘）。
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("vibe-research")


def _compute_dual_confirmation(target: str, final_cards: list[dict]) -> int:
    """计算双重确认数（漏斗 final_candidates ∩ breakout candidates，spec R10）。

    调 ``select_premarket_with_risk(forward)`` 读本地 kline 算交集，成本低。
    forward = F 的下一交易日（vr_paths.next_trading_date）。失败返 0（不臆造）。
    """
    try:
        from datetime import date as _date
        from vr_paths import next_trading_date
        from strategies.premarket_selection import select_premarket_with_risk

        forward = next_trading_date(_date.fromisoformat(target)).isoformat()
        selection = select_premarket_with_risk(forward)
        breakout_codes = {c.code for c in selection.candidates}
        funnel_codes = {c.get("code", "") for c in final_cards if c.get("code")}
        return len(funnel_codes & breakout_codes)
    except Exception as e:
        logger.warning("[candidate_funnel_precompute] 双重确认计算失败: %s", e)
        return 0


def _compute_strategy_map(target: str) -> dict[str, list[str]]:
    """从 scored_candidates 构建 code→[strategy_name] 映射（通知 top5 命中战法用）。

    轻量：load_gene_scores(DB 读) + score_candidates(CPU)，skip fetch_zt_pool
    （pool_item_map=None 降级——storm_reversal/PRD 不命中，既有战法不受影响）。
    失败返空 dict（不臆造战法命中）。
    """
    try:
        from limitup_screener.data import load_gene_scores
        from strategies.strategy_funnel_registry import score_candidates
        from sentiment_context import build_context

        genes = load_gene_scores(target)
        if not genes:
            return {}
        weather = build_context(target).weather_state
        cand_input = [
            {
                "code": g.code,
                "name": getattr(g, "name", ""),
                "factors": getattr(g, "factors", {}) or {},
                "total_score": getattr(g, "total_score", 0) or 0,
                "zt_count_250d": getattr(g, "zt_count_250d", 0) or 0,
            }
            for g in genes
        ]
        scored = score_candidates(cand_input, weather, "limitup", target, None)
        scored = [s for s in scored if s.get("strategy_code") != "none"]
        out: dict[str, list[str]] = {}
        for s in scored:
            code = s.get("code", "")
            sn = s.get("strategy_name", "")
            if code and sn:
                out.setdefault(code, []).append(sn)
        return out
    except Exception as e:
        logger.warning("[candidate_funnel_precompute] 战法映射计算失败: %s", e)
        return {}


def _build_premarket_notification_content(
    f_date: str,
    final_cards: list[dict],
    dual_count: int,
    strategy_map: dict[str, list[str]],
) -> str:
    """构建前瞻选股通知内容（spec R10 富内容卡片 Markdown）。

    内容：F 日期 + final_candidates 数 + 双重确认数 + top5 标的（code/name/基因分/命中战法）。
    标注历史统计特征风险提醒（CLAUDE.md §1.2 工程底线 + §7 合规自查）。
    """
    lines: list[str] = [
        f"📊 前瞻选股结果 {f_date}",
        "",
        f"漏斗最终候选: {len(final_cards)} 只",
        f"交集计数（§44 未 validated，排序参考非 edge）: {dual_count} 只",
        "",
    ]
    top5 = final_cards[:5]
    if top5:
        lines.append("Top 5 标的:")
        for c in top5:
            code = c.get("code", "")
            name = c.get("name", "")
            gs = c.get("gene_score") or {}
            gene_score = gs.get("total_score", "—")
            strategies = strategy_map.get(code, [])
            strat_str = "、".join(strategies) if strategies else "—"
            lines.append(f"  - {name}({code}) 基因分:{gene_score} 战法:{strat_str}")
        lines.append("")
    lines.append("历史统计特征，参考值，非执行指令；市场有风险")
    return "\n".join(lines)


# ============================================================================
# S101 飞书多点通知：辅助函数 + 3 个时点通知内容构建
# ============================================================================

# §44 raw-shadow 口径风险提醒（所有 S101 通知尾挂）
_S101_DISCLAIMER = "参考值，非执行指令；§44 未验证，市场有风险"


def _load_final_cards(f_date: str) -> list[dict]:
    """读 F 日 funnel_cache final_candidates（model_dump 列表）。无缓存返空。"""
    try:
        from candidate_funnel.funnel_cache import load_funnel_result

        result = load_funnel_result(f_date, "all")
        if result is None:
            return []
        return [c.model_dump(mode="json") for c in result.final_candidates]
    except Exception as e:  # noqa: BLE001
        logger.warning("[S101] load_final_cards %s 失败: %s", f_date, e)
        return []


def _fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """批量 tencent_quote 取实时行情。失败返空 dict（不臆造）。"""
    if not codes:
        return {}
    try:
        import astock

        raw = astock.tencent_quote(codes) or {}
        # raw[code] = dict with price/change_pct/last_close/open/limit_up 等
        return {c: raw.get(c, {}) for c in codes if raw.get(c)}
    except Exception as e:  # noqa: BLE001
        logger.warning("[S101] fetch_quotes 失败: %s", e)
        return {}


def _send_notify(content: str) -> bool:
    """发飞书通知。不可用/失败返 False（不崩）。"""
    try:
        from notification.notification_service import NotificationService

        ns = NotificationService()
        if not ns.is_available():
            return False
        return bool(ns.send(content, route_type="alert", severity="info"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[S101] send_notify 失败: %s", e)
        return False


def _fmt_pct(v) -> str:
    """格式化百分比，None/非数 → '—'。"""
    try:
        return f"{float(v):+.2f}%"
    except (TypeError, ValueError):
        return "—"


def _check_premarket_kill_switch() -> dict:
    """S136：盘前通知开盘后实时核市场熔断（market_note 承诺落地）。

    check_market_kill_switch 查上证<-3%/创业板<-4%→triggered 不开新仓。
    astock.index_quote() 不可达/空 → check_market_kill_switch 返 not_triggered
    （不臆造熔断）。检查本身抛 → 降级 not_triggered（不阻断通知，诚实标降级）。
    """
    try:
        from strategies.execution_model import check_market_kill_switch
        import astock  # noqa: PLC0415
        ks = check_market_kill_switch(astock.index_quote())
        return {
            "triggered": ks.triggered,
            "reason": ks.reason,
            "sh_change_pct": ks.sh_change_pct,
            "gem_change_pct": ks.gem_change_pct,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("[S136] kill_switch 检查失败，降级 not_triggered: %s", e)
        return {"triggered": False, "reason": f"检查失败（降级不触发）: {e}",
                "sh_change_pct": None, "gem_change_pct": None}


def _prepend_kill_switch_warning(content: str, ks: dict) -> str:
    """S136：熔断触发时通知 content 前置警告块。

    honest 标注非屏蔽——候选仍列（用户需知熔断+候选），前置块明确 gate 状态
    「不开新仓」。对齐 S126 诚实范式（标注非屏蔽）。
    """
    pct = ""
    if ks.get("sh_change_pct") is not None:
        pct += f"上证 {ks['sh_change_pct']:.2f}%"
    if ks.get("gem_change_pct") is not None:
        pct += f"{' / ' if pct else ''}创业板 {ks['gem_change_pct']:.2f}%"
    pct_str = f"（{pct}）" if pct else ""
    return (
        f"⚠️ 市场熔断：{ks.get('reason', '')}{pct_str}\n"
        f"不开新仓。premarket 候选风控价仅供参考，熔断中不入场。\n"
        f"---\n"
        f"{content}"
    )


def _build_auction_notify_content(
    f_date: str, final_cards: list[dict], quotes: dict[str, dict],
) -> str:
    """9:25 竞价确认通知：逐只高开/低开/平开（open vs last_close）。"""
    lines = [f"🔔 9:25 竞价确认 {f_date}", "", f"竞价标的 {len(final_cards)} 只:"]
    for c in final_cards:
        code = c.get("code", "")
        name = c.get("name", "") or code
        q = quotes.get(code, {})
        open_p = q.get("open")
        last_close = q.get("last_close")
        if open_p and last_close and last_close > 0:
            gap = (open_p - last_close) / last_close * 100
            tag = "高开" if gap > 0.1 else ("低开" if gap < -0.1 else "平开")
            lines.append(f"  - {name}({code}) {tag} {_fmt_pct(gap)}")
        else:
            lines.append(f"  - {name}({code}) 竞价数据待接入")
    lines.append("")
    lines.append(_S101_DISCLAIMER)
    return "\n".join(lines)


def _build_open_notify_content(
    f_date: str, final_cards: list[dict], quotes: dict[str, dict],
) -> str:
    """9:35 开盘表现通知：逐只现价/涨跌幅/封板状态。"""
    lines = [f"📈 9:35 开盘表现 {f_date}", "", f"开盘标的 {len(final_cards)} 只:"]
    for c in final_cards:
        code = c.get("code", "")
        name = c.get("name", "") or code
        q = quotes.get(code, {})
        price = q.get("price")
        change = q.get("change_pct")
        limit_up = q.get("limit_up_price") or q.get("limit_up")
        if price and limit_up and float(price) >= float(limit_up):
            tag = "封板"
        elif price:
            tag = "未封板"
        else:
            tag = "行情待接入"
        price_str = f"{float(price):.2f}" if price else "—"
        lines.append(f"  - {name}({code}) {price_str} {_fmt_pct(change)} {tag}")
    lines.append("")
    lines.append(_S101_DISCLAIMER)
    return "\n".join(lines)


def _compute_t1_returns(
    final_cards: list[dict], f_date: str, t_date: str,
) -> list[dict]:
    """算 final_candidates 在 T 日的 close2close 收益（F close → T close）。

    从 baostock_kline_cache 读 F 日 close + T 日 close。缺数据跳过（不臆造收益）。
    """
    try:
        from strategies.premarket_selection import KLINE_CACHE
        import json

        cache = json.loads(KLINE_CACHE.read_bytes())
    except Exception as e:  # noqa: BLE001
        logger.warning("[S101] t1 读 kline cache 失败: %s", e)
        return []

    out: list[dict] = []
    for c in final_cards:
        code = c.get("code", "")
        name = c.get("name", "") or code
        bars = cache.get(code, [])
        f_close = _bar_close(bars, f_date)
        t_close = _bar_close(bars, t_date)
        if f_close and t_close and f_close > 0:
            ret = (t_close - f_close) / f_close * 100
            out.append({
                "code": code, "name": name,
                "f_close": round(f_close, 2), "t_close": round(t_close, 2),
                "return_pct": round(ret, 2),
            })
    return out


def _bar_close(bars: list[dict], target_date: str) -> float | None:
    """从 baostock bars 找 target_date 的 close。"""
    for b in bars:
        if b.get("date") == target_date:
            close = b.get("close")
            try:
                return float(close) if close else None
            except (TypeError, ValueError):
                return None
    return None


def _build_t1_review_content(
    f_date: str, t_date: str, returns: list[dict],
) -> str:
    """T+1 复盘通知：均值/胜率/逐只 + §44 诚实口径。"""
    n = len(returns)
    if n == 0:
        lines = [
            f"📋 T+1 复盘 {f_date}→{t_date}",
            "",
            "无 T+1 收益数据（baostock kline 待更新或无候选）",
            "",
            _S101_DISCLAIMER,
        ]
        return "\n".join(lines)

    rets = [r["return_pct"] for r in returns]
    mean_ret = sum(rets) / n
    wins = sum(1 for r in rets if r > 0)
    win_rate = wins / n * 100
    # §44 口径：n<30 标样本不足；不宣称 alpha（lift<2x=噪声）
    sample_note = "样本不足(n<30)，不下结论" if n < 30 else f"n={n}"

    lines = [
        f"📋 T+1 复盘 {f_date}→{t_date}",
        "",
        f"标的 {n} 只 · 均值收益 {_fmt_pct(mean_ret)} · 红盘 {wins}/{n}（{win_rate:.0f}%）",
        f"§44 口径：{sample_note}，未 validated，不宣称 alpha",
        "",
        "逐只收益:",
    ]
    for r in returns:
        lines.append(f"  - {r['name']}({r['code']}) {_fmt_pct(r['return_pct'])} ({r['f_close']}→{r['t_close']})")
    lines.append("")
    lines.append(_S101_DISCLAIMER)
    return "\n".join(lines)


def generate_daily_summary(date: str) -> str:
    """S093 R12 AI 盘后总结 stub — 返空串 + 落存储位。

    S094 完整实现：LLM 汇总当日信号 + 持仓表现 + 市场数据，生成
    "今日操作回顾 + 明日建议"自然语言总结。本 stub 只返空串 + 创建存储位文件
    （接口最小定义，spec R12 / Oracle 非阻断 #14）。
    """
    summary = ""  # stub：空串，S094 完整实现
    try:
        from vr_paths import resolve_data_dir

        d = Path(resolve_data_dir()) / "daily_summaries"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{date}.txt").write_text(summary, encoding="utf-8")
    except Exception as e:
        logger.warning("[daily_ai_summary] 存储位写入失败: %s", e)
    return summary
