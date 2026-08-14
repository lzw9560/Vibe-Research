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

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import anyio
from limitup_screener.data import load_gene_scores
from limitup_strategy import match_strategies, STRATEGY_REGISTRY
from strategies.strategy_backtest import run_strategy_backtest

_DISCLAIMER = "历史统计特征，市场有风险，不构成投资建议"
_LOOKBACK_DAYS = 90
_DEFAULT_STOP_PCT = -3.0   # 层 1/2 无战法时的默认止损线
_HARD_STOP_PCT = -5.0      # 层 3 无战法支撑的硬止损
_ATR_PERIOD = 14
_ATR_MULT = 2.0            # trailing stop: 最高价 - N×ATR
_ATR_MULT_TIGHT = 1.5      # 浮盈>15% 时收紧 trailing
_HISTORY_LOOKBACK_DAYS = 30  # 层 2 查历史涨停的天数
_TIGHT_PROFIT_PCT = 15.0  # 浮盈超此值收紧 trailing
_kline_cache: dict[str, list[Any]] = {}  # code -> bars（复用 strategy_backtest 模式）
# S067 P0：winrate / kline TTL 缓存——advisory 端点避免每次重算回测
_WIN_RATE_CACHE: dict[str, tuple[float, int, str]] = {}  # _win_rate_map 结果
_WIN_RATE_CACHE_TS: float = 0.0
_WIN_RATE_CACHE_TTL: int = 300  # 5 分钟，90 天回测结果日内变化小
_KLINE_CACHE: dict[tuple, Any] = {}  # (code, category, offset) -> (raw, ts)；日内 kline TTL 缓存
_KLINE_CACHE_TTL: int = 3600  # 1 小时；日内 kline 到收盘不变


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
    TTL 缓存（``_WIN_RATE_CACHE_TTL``，默认 5 分钟）：90 天回测结果日内变化小，
    会话内复用避免每次请求重算。回测失败不缓存（下次自动重试）。
    """
    global _WIN_RATE_CACHE, _WIN_RATE_CACHE_TS
    now = time.time()
    if _WIN_RATE_CACHE and (now - _WIN_RATE_CACHE_TS) < _WIN_RATE_CACHE_TTL:
        return _WIN_RATE_CACHE
    try:
        results = run_strategy_backtest(_LOOKBACK_DAYS)
    except Exception:  # noqa: BLE001 — 回测失败不阻断建议，落 synthetic（不缓存失败结果）
        return {}
    m = {r.strategy_code: (r.win_rate, r.sample_size, r.strategy_name) for r in results}
    _WIN_RATE_CACHE = m
    _WIN_RATE_CACHE_TS = now
    return _WIN_RATE_CACHE


def clear_caches() -> None:
    """清空 winrate/kline 缓存（测试隔离 + 强制重算入口）。

    S067：模块级 TTL 缓存跨测试串数据，测试 autouse fixture 调本函数隔离。
    生产环境盘后可手动调强制重算（TTL 过期前）。
    """
    global _WIN_RATE_CACHE, _WIN_RATE_CACHE_TS
    _WIN_RATE_CACHE = {}
    _WIN_RATE_CACHE_TS = 0.0
    _kline_cache.clear()
    _KLINE_CACHE.clear()


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


def _atr_trailing_stop(code: str, cost: float, stop_floor_pct: float | None = None) -> tuple[float | None, float | None, bool]:
    """算 ATR trailing stop 价 + 持仓期最高价。

    返回 (trailing_stop_price, high_water_mark, atr_ok)。
    K 线 < _ATR_PERIOD+1 根 → atr_ok=False（调用方 fallback 到固定止损）。
    stop_floor_pct: 战法 stop_loss_pct（负值），trailing 不低于此线。None=不限。
    """
    bars = _kline_cache.get(code)
    if bars is None:
        # S067 P0：_KLINE_CACHE TTL 缓存（1h，日内 kline 不变）
        key = (code, 4, _ATR_PERIOD + 15)
        now = time.time()
        cached = _KLINE_CACHE.get(key)
        if cached and (now - cached[1]) < _KLINE_CACHE_TTL:
            raw = cached[0]
        else:
            try:
                import astock
                from data.mappers import kline_from_mootdx
                raw = astock.kline(code, category=4, offset=_ATR_PERIOD + 15)
                _KLINE_CACHE[key] = (raw, now)
            except Exception:  # noqa: BLE001
                raw = None
                _KLINE_CACHE[key] = (None, now)
        if raw is None:
            bars = []
        else:
            try:
                bars = list(kline_from_mootdx(code, raw).bars)
            except Exception:  # noqa: BLE001
                bars = []
        _kline_cache[code] = bars
    if len(bars) < _ATR_PERIOD + 1:
        return None, None, False
    # True Range
    trs = []
    for i in range(1, len(bars)):
        h = getattr(bars[i], "high", 0) or 0
        lo = getattr(bars[i], "low", 0) or 0
        pc = getattr(bars[i - 1], "close", 0) or 0
        if h and lo and pc:
            trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    if len(trs) < _ATR_PERIOD:
        return None, None, False
    atr = sum(trs[-_ATR_PERIOD:]) / _ATR_PERIOD
    high_water = max((getattr(b, "high", 0) or 0) for b in bars)
    if not atr or not high_water:
        return None, None, False
    mult = _ATR_MULT
    trailing = round(high_water - mult * atr, 2)
    if stop_floor_pct is not None:
        floor = round(cost * (1 + stop_floor_pct / 100), 2)
        trailing = max(trailing, floor)
    return trailing, round(high_water, 2), True


def _holding_action_layer1(
    pnl_pct: float, win_rate: float | None, stop_pct: float, take_profit_pct: float
) -> tuple[str, str]:
    """层 1：当日战法，窗口内——战法固定参数驱动。"""
    if pnl_pct <= stop_pct:
        if win_rate is not None and win_rate >= 0.5:
            return "hold", f"触及止损 {stop_pct}% 但回测胜率 {win_rate*100:.0f}% 支撑，持有观察"
        return "close", f"触及战法止损 {stop_pct}%，止损"
    if pnl_pct >= take_profit_pct:
        return "reduce", f"触及战法止盈 {take_profit_pct}%，锁利"
    if 0 < pnl_pct < take_profit_pct and win_rate is not None and win_rate < 0.4:
        return "reduce", "盈利但战法胜率偏弱，减仓锁利"
    return "hold", "当日战法信号有效，持有"


def _holding_action_layer2(
    pnl_pct: float, win_rate: float | None, stop_pct: float,
    price: float, cost: float, code: str
) -> tuple[str, str]:
    """层 2：历史战法已过期——ATR trailing 止盈。"""
    if pnl_pct <= stop_pct:
        return "close", f"触及战法止损 {stop_pct}%，止损"
    trailing, high_water, atr_ok = _atr_trailing_stop(code, cost, stop_pct)
    if atr_ok and trailing is not None and price <= trailing:
        return "reduce", f"ATR trailing 触发（止盈线 {trailing}），锁利"
    if pnl_pct > _TIGHT_PROFIT_PCT and atr_ok and trailing is not None:
        # 浮盈>15%，收紧 trailing
        tight_trailing = round(high_water - _ATR_MULT_TIGHT * (high_water - trailing) / _ATR_MULT, 2) if trailing and high_water else None
        # 直接重算收紧版
        bars = _kline_cache.get(code, [])
        if len(bars) >= _ATR_PERIOD + 1:
            trs = []
            for i in range(1, len(bars)):
                h = getattr(bars[i], "high", 0) or 0
                lo = getattr(bars[i], "low", 0) or 0
                pc = getattr(bars[i-1], "close", 0) or 0
                if h and lo and pc:
                    trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
            if len(trs) >= _ATR_PERIOD:
                atr = sum(trs[-_ATR_PERIOD:]) / _ATR_PERIOD
                tight_trailing = round(high_water - _ATR_MULT_TIGHT * atr, 2)
                floor = round(cost * (1 + stop_pct / 100), 2)
                tight_trailing = max(tight_trailing, floor)
                if price <= tight_trailing:
                    return "reduce", f"收紧 ATR trailing 触发（止盈线 {tight_trailing}），锁大部分利润"
    if pnl_pct > 0 and win_rate is not None and win_rate < 0.4:
        return "reduce", "历史战法胜率偏弱，主动锁利"
    return "hold", "历史战法信号已过期，ATR trailing 守利润"


def _holding_action_layer3(
    pnl_pct: float, price: float, cost: float, code: str
) -> tuple[str, str]:
    """层 3：无战法信号——纯盈亏 + ATR trailing 止损纪律。"""
    if pnl_pct <= _HARD_STOP_PCT:
        return "close", f"无战法支撑，浮亏 {pnl_pct:.1f}% 超硬止损 {_HARD_STOP_PCT}%，止损"
    trailing, high_water, atr_ok = _atr_trailing_stop(code, cost)
    if atr_ok and trailing is not None and price <= trailing:
        return "reduce", f"ATR trailing 触发（止盈线 {trailing}），锁利"
    if pnl_pct > _TIGHT_PROFIT_PCT and atr_ok and trailing is not None and high_water:
        bars = _kline_cache.get(code, [])
        if len(bars) >= _ATR_PERIOD + 1:
            trs = []
            for i in range(1, len(bars)):
                h = getattr(bars[i], "high", 0) or 0
                lo = getattr(bars[i], "low", 0) or 0
                pc = getattr(bars[i-1], "close", 0) or 0
                if h and lo and pc:
                    trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
            if len(trs) >= _ATR_PERIOD:
                atr = sum(trs[-_ATR_PERIOD:]) / _ATR_PERIOD
                tight_trailing = round(high_water - _ATR_MULT_TIGHT * atr, 2)
                if price <= tight_trailing:
                    return "reduce", f"收紧 ATR trailing 触发（止盈线 {tight_trailing}），锁大部分利润"
    if 0 < pnl_pct <= 5:
        return "hold", "刚启动盈利，观察"
    if 5 < pnl_pct <= 10:
        return "hold", "盈利中，止损线上移至成本价保本"
    return "hold", "无战法信号，基于盈亏状态持有"


def _lookup_holding_strategy(
    code: str, today_gene_map: dict[str, Any], wr_map: dict[str, tuple[float, int, str]]
) -> tuple[str | None, str, float | None, int, str, int]:
    """持仓战法三层匹配。返回 (strategy_code, strategy_name, win_rate, sample_size, win_rate_source, layer)。

    layer: 1=当日涨停, 2=历史涨停(30天内), 3=无涨停历史
    """
    # 层 1：当日 gene_scores 有此 code
    g = today_gene_map.get(code)
    if g is not None:
        sc, sn, wr, ss, src = _lookup_strategy(code, g, wr_map)
        if sc:
            return sc, sn, wr, ss, "backtest_90d", 1
    # 层 2：查 30 天内历史 gene_scores
    from limitup_screener.data import get_db

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT date FROM gene_scores WHERE code = ? AND date < ? "
                "AND date >= date(?, '-30 days') ORDER BY date DESC LIMIT 1",
                (code, today, today),
            ).fetchone()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        row = None
    if row:
        hist_date = row["date"]
        scores = load_gene_scores(hist_date) or []
        hist_gene = next((g for g in scores if g.code == code), None)
        if hist_gene:
            sc, sn, wr, ss, src = _lookup_strategy(code, hist_gene, wr_map)
            if sc:
                return sc, sn, wr, ss, "backtest_90d_historical", 2
    # 层 3
    return None, "", None, 0, "none", 3


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
    """R4：持仓 add/reduce/close/hold——三层降级 + ATR trailing（spec D2）。

    层 1 当日涨停 → 战法固定止盈止损 + win_rate。
    层 2 历史涨停(30天内) → ATR trailing 止盈 + 历史 win_rate 参考。
    层 3 无涨停历史 → 纯盈亏 + ATR trailing 止损纪律。
    """
    import portfolio as pf

    try:
        pf_data = await pf.get_portfolio()
    except Exception:  # noqa: BLE001
        return []
    holdings = pf_data.get("holdings") or []
    if not holdings:
        return []
    # S067 P1-2：移除 _kline_cache.clear()——自毁解析缓存导致 holdings 场景每次重解析。
    # kline 日内有效（_KLINE_CACHE TTL 1h + _kline_cache 复用），无需每次清。
    gene_map = _latest_gene_map()
    wr_map = _win_rate_map()
    items: list[AdvisoryItem] = []
    for h in holdings:
        code = h.get("code")
        pnl_pct = h.get("pnl_pct") or 0.0
        cost = h.get("cost") or 0.0
        price = h.get("price") or 0.0
        name = h.get("name") or code

        sc, sn, wr, ss, src, layer = _lookup_holding_strategy(code, gene_map, wr_map)
        params = _strat_params(sc)
        stop_pct = params.get("stop_loss_pct", _DEFAULT_STOP_PCT)
        take_profit_pct = params.get("take_profit_pct", 8.0)

        if layer == 1:
            action, reason = _holding_action_layer1(pnl_pct, wr, stop_pct, take_profit_pct)
        elif layer == 2:
            action, reason = _holding_action_layer2(pnl_pct, wr, stop_pct, price, cost, code)
        else:
            action, reason = _holding_action_layer3(pnl_pct, price, cost, code)

        reasons = [f"浮动盈亏 {pnl_pct:+.2f}%"]
        if layer <= 2 and wr is not None:
            tag = "当日" if layer == 1 else "历史"
            reasons.append(
                f"{tag}战法「{sn or '未匹配'}」90 天回测胜率 {wr*100:.0f}%（样本 {ss}）"
            )
        elif layer == 2:
            reasons.append("历史战法信号已过期，win_rate 仅供参考")
        else:
            reasons.append("无战法信号，建议基于盈亏状态 + ATR 止损纪律")
        reasons.append(reason)
        risk_notes = [_DISCLAIMER]
        if layer == 2:
            risk_notes.append("历史战法信号已超 max_hold_days 窗口")
        items.append(AdvisoryItem(
            code=code, name=name, scene="holding", action=action,
            win_rate=wr, win_rate_source=src, matched_strategy=sn or None,
            reasons=reasons, risk_notes=risk_notes,
            extra={"pnl_pct": pnl_pct, "cost": cost, "price": price, "layer": layer},
        ))
    return items


async def advisory_summary(limit: int = 20) -> dict[str, Any]:
    """R5：三场景建议汇总（recommendations + watchlist + holdings）。

    S067 P2-1：三场景 asyncio.gather 并行——recommendations/watchlist 是 sync CPU-bound，
    用 anyio.to_thread.run_sync offload 到线程池避免阻塞事件循环（消除死锁）。
    """
    recs, watch, hold = await asyncio.gather(
        anyio.to_thread.run_sync(lambda: advise_recommendations(limit)),
        anyio.to_thread.run_sync(advise_watchlist),
        advise_holdings(),
    )
    return {
        "recommendations": [i.to_dict() for i in recs],
        "watchlist": [i.to_dict() for i in watch],
        "holdings": [i.to_dict() for i in hold],
        "disclaimer": _DISCLAIMER,
    }
