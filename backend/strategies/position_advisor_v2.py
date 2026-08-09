# -*- coding: utf-8 -*-
"""S042 统一持仓建议引擎 v2 — 推荐/自选/持仓三场景。

基于 90 天真实回测 win_rate（``strategy_backtest.run_strategy_backtest``）替代 v1
合成公式（``min(confidence*0.8+0.2, 0.95)``）。v1（``strategies/position_advisor.py``）
保持不动，v2 是新模块 + 新端点（spec D6）。

合规（CLAUDE.md §1.1 弱合规，私人投研助理）：建议属教育研究式口吻，不输出
"买入/卖出"指令，每条挂「历史统计特征，市场有风险，不构成投资建议」。
``win_rate_source`` 标注来源（backtest_90d / synthetic / none）透明可审计。
win_rate 来自客观回测统计，不臆造；无回测数据时标 synthetic 不编数值。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from limitup_screener.data import load_gene_scores
from limitup_strategy import match_strategies, STRATEGY_REGISTRY
from strategies.strategy_backtest import run_strategy_backtest

_DISCLAIMER = "历史统计特征，市场有风险，不构成投资建议"
_LOOKBACK_DAYS = 90
_DEFAULT_STOP_PCT = -3.0  # 持仓无战法命中时的默认止损线（spec D2 兜底）


@dataclass
class AdvisoryItem:
    """单标的建议（三场景通用 shape）。"""

    code: str
    name: str
    scene: str  # recommendation / watchlist / holding
    action: str  # enter / add / reduce / close / hold / no_signal
    win_rate: float | None  # 0-1；None=无回测数据
    win_rate_source: str  # backtest_90d / synthetic / none
    matched_strategy: str | None
    reasons: list[str]
    risk_notes: list[str]
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "scene": self.scene,
            "action": self.action,
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "win_rate_source": self.win_rate_source,
            "matched_strategy": self.matched_strategy,
            "reasons": self.reasons,
            "risk_notes": self.risk_notes,
            "disclaimer": _DISCLAIMER,
            **self.extra,
        }


def _win_rate_map() -> dict[str, tuple[float, int, str]]:
    """run_strategy_backtest(90) → {strategy_code: (win_rate, sample_size, strategy_name)}。

    异常/空 → {}（下游 _lookup_strategy 落到 synthetic）。
    """
    try:
        results = run_strategy_backtest(_LOOKBACK_DAYS)
    except Exception:  # noqa: BLE001 — 回测失败不阻断建议，落 synthetic
        return {}
    return {r.strategy_code: (r.win_rate, r.sample_size, r.strategy_name) for r in results}


def _latest_gene_map() -> dict[str, Any]:
    """今日 gene_scores（DB 读，不触发网络）；今日无则取 DB 最新日。→ {code: GeneScore}。"""
    today = datetime.now().strftime("%Y-%m-%d")
    scores = load_gene_scores(today)
    if not scores:
        from limitup_screener.data import get_db

        try:
            conn = get_db()
            try:
                row = conn.execute("SELECT MAX(date) AS d FROM gene_scores").fetchone()
                latest = row["d"] if row else None
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            latest = None
        if latest:
            scores = load_gene_scores(latest)
    return {g.code: g for g in (scores or [])}


def _lookup_strategy(
    code: str, gene: Any, wr_map: dict[str, tuple[float, int, str]]
) -> tuple[str | None, str, float | None, int, str]:
    """match_strategies → 选 sample_size 最大（最可信）战法。

    返回 ``(strategy_code, strategy_name, win_rate, sample_size, win_rate_source)``。
    无命中战法 → ``(None, "", None, 0, "none")``；命中但无回测样本 → synthetic。
    """
    try:
        signals = match_strategies(code, gene) or []
    except Exception:  # noqa: BLE001
        signals = []
    if not signals:
        return None, "", None, 0, "none"
    best: tuple | None = None
    for sig in signals:
        sc = getattr(sig, "strategy_code", "") or ""
        sn = getattr(sig, "strategy_name", "") or ""
        entry = wr_map.get(sc)
        if entry and entry[1] > 0:  # 有回测样本 → backtest_90d
            cand = (sc, entry[2] or sn, entry[0], entry[1], "backtest_90d")
        elif entry:  # 战法有但 sample_size=0 → synthetic
            cand = (sc, entry[2] or sn, None, 0, "synthetic")
        else:
            cand = (sc, sn, None, 0, "synthetic")
        if best is None or cand[3] > best[3]:
            best = cand
    return best if best else (None, "", None, 0, "none")


def _strat_params(strategy_code: str | None) -> dict:
    """从 STRATEGY_REGISTRY 取战法参数（stop_loss_pct/take_profit_pct/max_hold_days）。"""
    if not strategy_code:
        return {}
    for s in STRATEGY_REGISTRY:
        if s.get("code") == strategy_code:
            return s
    return {}


def _suggested_pct(win_rate: float | None) -> float:
    """win_rate → 建议仓位（研究参考）：>=0.6→15%, 0.4-0.6→10%, <0.4/无→5%。"""
    if win_rate is None:
        return 0.05
    if win_rate >= 0.6:
        return 0.15
    if win_rate >= 0.4:
        return 0.10
    return 0.05


def _holding_action(
    pnl_pct: float, win_rate: float | None, stop_pct: float
) -> tuple[str, str]:
    """持仓 add/reduce/close/hold 规则（spec D2）。

    wr 为 0-1 小数或 None。stop_pct 为止损线（%，负值，默认 -3 或战法 stop_loss_pct）。
    解读：硬止损 floor（触及 stop_pct）→ close，但 win_rate>=0.5 支撑时持有（D2
    "亏损>3% 且 win_rate>=50% → hold" 与 "止损线无条件 close" 的张力按 win_rate 优先解）。
    """
    at_stop = pnl_pct <= stop_pct
    if at_stop:
        if win_rate is not None and win_rate >= 0.5:
            return "hold", f"触及止损 {stop_pct}% 但回测胜率 {win_rate*100:.0f}% 支撑，持有观察"
        return "close", f"触及止损 {stop_pct}%，止损"
    if pnl_pct > 5:
        if win_rate is not None and win_rate < 0.4:
            return "reduce", "盈利但战法胜率偏弱，减仓锁利"
        return "hold", "盈利 + 战法胜率支撑，持有"
    if pnl_pct < -3:
        if win_rate is not None and win_rate < 0.4:
            return "close", "亏损 + 战法胜率差，止损"
        return "hold", "亏损但胜率中等以上，观察"
    # 浮动盈亏在 [-3, 5]
    if win_rate is not None and win_rate < 0.4:
        return "reduce", "信号偏弱，减仓降风险"
    return "hold", "信号不明，观察"


def advise_recommendations(limit: int = 20) -> list[AdvisoryItem]:
    """R2：推荐标的入场建议——top gene_scores + 战法 90 天回测 win_rate。

    取今日（或 DB 最新日）gene_scores 按 total_score 降序 top-N，逐个 match_strategies
    + run_strategy_backtest win_rate，输出入场建议（仓位/止损/止盈/理由）。
    win_rate 替代 v1 合成公式。
    """
    gene_map = _latest_gene_map()
    if not gene_map:
        return []
    wr_map = _win_rate_map()
    genes = sorted(gene_map.values(), key=lambda g: g.total_score, reverse=True)[:limit]
    items: list[AdvisoryItem] = []
    for g in genes:
        sc, sn, wr, ss, src = _lookup_strategy(g.code, g, wr_map)
        params = _strat_params(sc)
        stop = params.get("stop_loss_pct", -7)
        take = params.get("take_profit_pct", 15)
        pct = _suggested_pct(wr)
        wr_disp = f"{wr*100:.0f}%（样本 {ss}）" if wr is not None else "无回测数据"
        items.append(AdvisoryItem(
            code=g.code, name=g.name or g.code, scene="recommendation", action="enter",
            win_rate=wr, win_rate_source=src, matched_strategy=sn or None,
            reasons=[
                f"基因得分 {g.total_score}",
                f"战法「{sn or '未匹配'}」90 天回测胜率 {wr_disp}",
                f"建议仓位 {int(pct*100)}%（研究参考，非交易指令）",
            ],
            risk_notes=[f"止损 {stop}% / 止盈 {take}%", _DISCLAIMER],
            extra={
                "gene_score": g.total_score, "suggested_pct": pct,
                "stop_loss_pct": stop, "take_profit_pct": take,
            },
        ))
    return items


def advise_watchlist() -> list[AdvisoryItem]:
    """R3：自选股建议——有当日涨停信号→战法+win_rate 入场建议；无→no_signal（D5）。"""
    from routers.watchlist import watchlist_get

    try:
        wl = watchlist_get() or {}
        codes = wl.get("codes") or []
    except Exception:  # noqa: BLE001
        codes = []
    if not codes:
        return []
    gene_map = _latest_gene_map()
    wr_map = _win_rate_map()
    items: list[AdvisoryItem] = []
    for code in codes:
        g = gene_map.get(code)
        if g is None:
            items.append(AdvisoryItem(
                code=code, name=code, scene="watchlist", action="no_signal",
                win_rate=None, win_rate_source="none", matched_strategy=None,
                reasons=["该标的当日不在涨停池，无涨停信号"],
                risk_notes=[_DISCLAIMER], extra={"status": "no_signal"},
            ))
            continue
        sc, sn, wr, ss, src = _lookup_strategy(code, g, wr_map)
        params = _strat_params(sc)
        stop = params.get("stop_loss_pct", -7)
        take = params.get("take_profit_pct", 15)
        pct = _suggested_pct(wr)
        wr_disp = f"{wr*100:.0f}%（样本 {ss}）" if wr is not None else "无回测数据"
        items.append(AdvisoryItem(
            code=code, name=g.name or code, scene="watchlist", action="enter",
            win_rate=wr, win_rate_source=src, matched_strategy=sn or None,
            reasons=[
                f"基因得分 {g.total_score}",
                f"战法「{sn or '未匹配'}」90 天回测胜率 {wr_disp}",
                f"建议仓位 {int(pct*100)}%",
            ],
            risk_notes=[f"止损 {stop}% / 止盈 {take}%", _DISCLAIMER],
            extra={
                "gene_score": g.total_score, "suggested_pct": pct,
                "stop_loss_pct": stop, "take_profit_pct": take,
            },
        ))
    return items


async def advise_holdings() -> list[AdvisoryItem]:
    """R4：持仓 add/reduce/close/hold——浮动盈亏 + 战法 90 天 win_rate（D2 规则）。"""
    import portfolio as pf

    try:
        pf_data = await pf.get_portfolio()
    except Exception:  # noqa: BLE001
        return []
    holdings = pf_data.get("holdings") or []
    if not holdings:
        return []
    gene_map = _latest_gene_map()
    wr_map = _win_rate_map()
    items: list[AdvisoryItem] = []
    for h in holdings:
        code = h.get("code")
        pnl_pct = h.get("pnl_pct") or 0.0
        cost = h.get("cost") or 0.0
        price = h.get("price") or 0.0
        name = h.get("name") or code
        g = gene_map.get(code)
        if g is not None:
            sc, sn, wr, ss, src = _lookup_strategy(code, g, wr_map)
        else:
            sc, sn, wr, ss, src = None, "", None, 0, "none"
        params = _strat_params(sc)
        stop_pct = params.get("stop_loss_pct", _DEFAULT_STOP_PCT)
        action, reason = _holding_action(pnl_pct, wr, stop_pct)
        reasons = [f"浮动盈亏 {pnl_pct:+.2f}%"]
        if wr is not None:
            reasons.append(
                f"战法「{sn or '未匹配'}」90 天回测胜率 {wr*100:.0f}%（样本 {ss}）"
            )
        else:
            reasons.append("无对应战法回测数据（win_rate_source=synthetic/none）")
        reasons.append(reason)
        items.append(AdvisoryItem(
            code=code, name=name, scene="holding", action=action,
            win_rate=wr, win_rate_source=src, matched_strategy=sn or None,
            reasons=reasons, risk_notes=[_DISCLAIMER],
            extra={"pnl_pct": pnl_pct, "cost": cost, "price": price},
        ))
    return items


async def advisory_summary(limit: int = 20) -> dict[str, Any]:
    """R5：三场景建议汇总（recommendations + watchlist + holdings）。"""
    return {
        "recommendations": [i.to_dict() for i in advise_recommendations(limit)],
        "watchlist": [i.to_dict() for i in advise_watchlist()],
        "holdings": [i.to_dict() for i in await advise_holdings()],
        "disclaimer": _DISCLAIMER,
    }
