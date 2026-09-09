# -*- coding: utf-8 -*-
"""仓位建议引擎 — 统一实现（原 v1 workflow 集成 + v2 advisory 独立，合一）。

两部分共居一文件，互不依赖，各自服务不同消费者：

- **workflow 仓位建议**（原 v1）：基于战法匹配结果 + 账户风险参数，给出建议仓位
  比例、入场价区间、止损、止盈。供 pre_market_workflow / workflow /
  dragon_tiger_seat_filter 使用。含 cap_by_market_phase 仓位闸后处理（S079 R7）。

- **advisory 三场景建议**（原 v2）：推荐/自选/持仓三场景，基于 90 天真实回测
  win_rate 替代合成公式。供 routers/advisory API 使用。含 ATR trailing +
  三层持仓决策 + gene_scores 新鲜度标注。

合规（CLAUDE.md §1.1 弱合规，私人投研助理）：建议属教育研究式口吻，不输出
"买入/卖出"指令，每条挂「历史统计特征，市场有风险，不构成投资建议」。
win_rate_source 标注来源（backtest_90d / synthetic / none）透明可审计。
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
from limitup_strategy import StrategySignal, STRATEGY_REGISTRY, match_strategies
from strategies.first_board_filter import PHASE_TO_CAP_TIER
from strategies.strategy_backtest import run_strategy_backtest
from strategies.strategy_matcher import StrategyMatcher


# ===========================================================================
# Part 1: workflow 仓位建议（原 v1）
# ===========================================================================

class PositionSuggestion:
    """单只股票的仓位建议。"""

    def __init__(
        self,
        code: str,
        name: str,
        suggested_pct: float,
        confidence: str,
        entry_price_range: tuple[float, float],
        stop_loss: float,
        take_profit: float,
        matched_strategy: str,
        reasons: list[str],
    ) -> None:
        self.code = code
        self.name = name
        self.suggested_pct = suggested_pct
        self.confidence = confidence
        self.entry_price_range = entry_price_range
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.matched_strategy = matched_strategy
        self.reasons = reasons
        # S079 R7：仓位闸后处理标记（cap_by_market_phase 填充，默认空）
        self.market_phase: str | None = None
        self.market_phase_cap: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "suggested_pct": self.suggested_pct,
            "confidence": self.confidence,
            "entry_price_range": list(self.entry_price_range),
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "matched_strategy": self.matched_strategy,
            "reasons": self.reasons,
            "market_phase": self.market_phase,
            "market_phase_cap": self.market_phase_cap,
        }


class PositionAdvisor:
    """仓位建议引擎。"""

    def __init__(
        self,
        max_single_position: float = 0.3,
        max_total_position: float = 0.8,
        base_unit: float = 0.1,
    ) -> None:
        """
        Args:
            max_single_position: 单票最大仓位上限（默认 30%）
            max_total_position: 总仓位上限（默认 80%）
            base_unit: 仓位基础单位（默认 10%）
        """
        self.max_single_position = max_single_position
        self.max_total_position = max_total_position
        self.base_unit = base_unit
        self._matcher = StrategyMatcher()

    def advise(
        self, signal: StrategySignal, weather_state: str | None = None
    ) -> PositionSuggestion | None:
        """
        基于单条策略信号生成仓位建议。

        S086 R4：天气仓位软标注（不硬阻断）：
        - 暴风雨 → 仓位×0.3 建议（非强制，advice_note；不 return None 强制空仓）
        - 极端反弹 → 仓位上限降至 50%（半仓）
        - 晴天/阴天/未知 → 正常计算
        """
        if not signal or signal.confidence <= 0:
            return None

        # S086 R4：天气仓位软标注（不硬阻断）。暴风暴仓位×0.3 降为建议提示（非强制）。
        weather_cap = 1.0  # 默认不限制
        if weather_state == "暴风雨":
            weather_cap = 0.3  # 建议仓位×0.3（环境极端），不 return None 强制空仓
        if weather_state == "极端反弹":
            weather_cap = 0.5  # 仓位上限降至 50%

        # 置信度映射：high / medium / low
        if signal.confidence >= 0.7:
            confidence = "high"
            suggested_pct = min(self.base_unit * 2, self.max_single_position)
        elif signal.confidence >= 0.5:
            confidence = "medium"
            suggested_pct = self.base_unit
        else:
            confidence = "low"
            suggested_pct = self.base_unit * 0.5

        # 应用天气仓位上限
        suggested_pct = min(suggested_pct, self.max_single_position * weather_cap)

        # 入场价区间：以 entry_price 为中心 ±1%
        entry_low = round(signal.entry_price * 0.99, 2)
        entry_high = round(signal.entry_price * 1.01, 2)

        reasons = [
            f"战法「{signal.strategy_name}」匹配",
            f"信号强度 {signal.signal_strength}%",
            f"置信度映射 {signal.confidence_mapped_winrate:.0%}（非实测）",
        ]
        if weather_state and weather_state != "晴天":
            reasons.append(f"天气={weather_state}，仓位上限调整为 {int(weather_cap * 100)}%")
        if signal.matches:
            reasons.extend([m.description for m in signal.matches[:3]])

        return PositionSuggestion(
            code=signal.code,
            name=signal.name,
            suggested_pct=round(suggested_pct, 2),
            confidence=confidence,
            entry_price_range=(entry_low, entry_high),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            matched_strategy=signal.strategy_name,
            reasons=reasons,
        )

    def advise_batch(
        self, signals: list[StrategySignal], weather_state: str | None = None
    ) -> list[PositionSuggestion]:
        """
        批量生成仓位建议，并按 suggested_pct 降序排列。
        """
        suggestions: list[PositionSuggestion] = []
        for signal in signals:
            suggestion = self.advise(signal, weather_state)
            if suggestion:
                suggestions.append(suggestion)
        suggestions.sort(key=lambda s: s.suggested_pct, reverse=True)
        return suggestions

    def summarize(self, suggestions: list[PositionSuggestion]) -> dict[str, Any]:
        """
        汇总仓位建议，返回总建议仓位、风险提示等。
        """
        total_pct = sum(s.suggested_pct for s in suggestions)
        return {
            "count": len(suggestions),
            "total_suggested_pct": round(total_pct, 2),
            "exceeds_limit": total_pct > self.max_total_position,
            "max_single_position": self.max_single_position,
            "max_total_position": self.max_total_position,
            "suggestions": [s.to_dict() for s in suggestions],
        }


# 全局单例
advisor = PositionAdvisor()


# ---------------------------------------------------------------------------
# S079 R7：仓位闸后处理（cap_by_market_phase）
# ---------------------------------------------------------------------------

# R7.1 三状态 cap 映射
# 绿（活跃/亢奋）= 1.0  → 不放宽，只收紧（不顶掉 weather_cap 或 max_total_position）
# 黄（普通）   = 0.5
# 红（冰点/红期）= 0.2
MARKET_PHASE_CAP: dict[str, float] = {
    "green": 1.0,
    "yellow": 0.5,
    "red": 0.2,
}


def cap_by_market_phase(
    positions: list[PositionSuggestion],
    phase: str,
    max_single_position: float = 0.3,
    max_total_position: float = 0.8,
) -> list[PositionSuggestion]:
    """S079 R7 仓位闸后处理。

    叠加在 PositionAdvisor.advise_batch 输出之上。每个 position.suggested_pct 已
    经过 weather_cap 处理（advise_batch 内部 advise 的 weather 熔断）。

    叠加代数（spec R7.1）：
        final_cap = min(weather_cap, market_phase_cap, max_total_position)

    其中：
      - weather_cap：既有，advise_batch 输出的 suggested_pct 已应用 weather_cap
      - market_phase_cap：新增，绿=1.0（不放宽）/黄=0.5/红=0.2
      - max_total_position：既有 0.8 硬上限

    绿档不放宽原则（R7.2）：market_phase_cap 绿档=1.0，
        market_phase_cap_result = min(suggested_pct, max_single_position * 1.0)
        = min(suggested_pct, max_single_position)
      不会超过既有单票上限，只收紧不放宽。

    互斥说明（R7.3）：同一情绪现象（大面股爆炸≈暴风雨）可能同时触发
      weather 熔断和 market_phase 熔断，取 min() 不冲突（取最严）。

    时序用途（R8，文档层声明）：
      STI 是 T-1 盘后总结（limitup_sti 8 维度加权 → 4 天气），用于 advise 的
      weather_state 参数；_market_phase 是 T+1 盘前仓位闸因子，用于本函数的
      phase 参数。两者时序用途不同，不引入新概念，不替代 STI。

    Args:
        positions: advise_batch 返回的 PositionSuggestion 列表
        phase: _market_phase 返回的字符串（冰点/普通/活跃/亢奋/红期）
        max_single_position: 单票仓位上限（默认 0.3，与 PositionAdvisor 默认一致）
        max_total_position: 总仓位硬上限（默认 0.8，与 PositionAdvisor 默认一致）

    Returns:
        仓位上限叠加处理后的 PositionSuggestion 列表（原地修改 + 返回）
    """
    # R7.1 三状态映射 + 未知 phase 降级 yellow（保守）
    tier = PHASE_TO_CAP_TIER.get(phase, "yellow")
    market_phase_cap = MARKET_PHASE_CAP[tier]

    for pos in positions:
        # pos.suggested_pct 已经过 weather_cap 处理（advise_batch 输出）
        weather_cap_result = pos.suggested_pct

        # market_phase_cap 叠加：min(suggested_pct, max_single_position * market_phase_cap)
        market_phase_cap_result = min(
            pos.suggested_pct,
            max_single_position * market_phase_cap,
        )

        # R7.1 叠加代数：final_cap = min(weather_cap, market_phase_cap, max_total_position)
        final_pct = min(
            weather_cap_result,
            market_phase_cap_result,
            max_total_position,
        )
        pos.suggested_pct = round(final_pct, 2)

        # R7 标记仓位闸信息（供前端展示）
        pos.market_phase = phase
        pos.market_phase_cap = market_phase_cap

    return positions


# ===========================================================================
# Part 2: advisory 三场景建议（原 v2）
# ===========================================================================

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


def _prefetch_klines_concurrent(codes: list[str], max_workers: int = 5) -> None:
    """S067 P1-1：并发预取多持仓 kline——消除 holdings 循环串行 mootdx 网络。

    ThreadPoolExecutor max_workers=5 限流（mootdx 并发承载有限）。
    预填 _kline_cache + _KLINE_CACHE，循环内 _atr_trailing_stop 全命中缓存。
    任一 code 拉取失败不影响其他（catch 单条）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 只预取缓存未命中的
    need = [c for c in codes if c and c not in _kline_cache]
    if not need:
        return

    def _fetch_one(code: str) -> str:
        # 复用 _atr_trailing_stop 的拉取逻辑（填 _kline_cache + _KLINE_CACHE）
        try:
            _atr_trailing_stop(code, 0.0)  # cost=0 触发拉取但不影响 trailing 计算
        except Exception:  # noqa: BLE001
            pass
        return code

    with ThreadPoolExecutor(max_workers=min(max_workers, len(need))) as ex:
        futures = [ex.submit(_fetch_one, c) for c in need]
        for fu in as_completed(futures):
            try:
                fu.result()
            except Exception:  # noqa: BLE001
                continue


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


def _latest_gene_map() -> tuple[dict[str, Any], str, bool]:
    """今日 gene_scores（DB 读，不触发网络）；今日无则取 DB 最新日。

    → ``( {code: GeneScore}, data_date, data_stale )``。
    data_date：今日有 scores → today；回退 DB 最新日 → latest；无任何数据 → ""。
    data_stale：binary 标注 data_date 非空且 != today（周末/节假日回退属正常，
    如实标注「非今日」不阻塞，不降级仓位/win_rate——阈值留待回溯数据后定）。
    不臆造：data_date==""（无 date）→ not stale（无 date 不标）。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    scores = load_gene_scores(today)
    data_date = today if scores else ""
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
            data_date = latest
    data_stale = bool(data_date) and data_date != today
    return {g.code: g for g in (scores or [])}, data_date, data_stale


def _gene_stale_note(data_date: str) -> str:
    """stale risk_note：如实呈现数据日非今日（不标「异常」，周末/节假日属正常）。"""
    return f"数据日={data_date}，非今日（盘后预计算可能未跑），建议盘后重算"


def _with_gene_freshness(
    extra: dict[str, Any], risk_notes: list[str], data_date: str, data_stale: bool
) -> tuple[dict[str, Any], list[str]]:
    """把 gene 数据日/stale 标注并入 AdvisoryItem.extra + risk_notes（immutable：返回新副本）。"""
    new_extra = {**extra, "gene_data_date": data_date, "data_stale": data_stale}
    new_notes = [*risk_notes]
    if data_stale:
        new_notes.append(_gene_stale_note(data_date))
    return new_extra, new_notes


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


def _strat_params(strategy_code: str | None) -> Any:
    """从 STRATEGY_REGISTRY 取战法参数（stop_loss_pct/take_profit_pct/max_hold_days）。

    返回 StrategyConfig（dict-compat：.get/__getitem__ 可用）或 {}；调用方一律 .get() 取字段。
    """
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


def _lookup_holding_strategies_batch(
    codes: list[str], today_gene_map: dict[str, Any], wr_map: dict[str, tuple[float, int, str]]
) -> dict[str, tuple[str | None, str, float | None, int, str, int]]:
    """S067 P2-2：批量持仓战法匹配——消除 layer2 N+1 DB 查询。

    一次 IN 查询取所有持仓的 30 天内历史涨停日，再按 distinct date 批量 load_gene_scores。
    返回 {code: (sc, sn, wr, ss, src, layer)}。
    """
    result: dict[str, tuple[str | None, str, float | None, int, str, int]] = {}
    if not codes:
        return result

    today = datetime.now().strftime("%Y-%m-%d")

    # 层 1：当日 gene_scores（内存 map，无 DB）
    need_hist: list[str] = []
    for code in codes:
        g = today_gene_map.get(code)
        if g is not None:
            sc, sn, wr, ss, src = _lookup_strategy(code, g, wr_map)
            if sc:
                result[code] = (sc, sn, wr, ss, "backtest_90d", 1)
                continue
        need_hist.append(code)

    if not need_hist:
        # 全在层 1 命中或落层 3
        for code in codes:
            if code not in result:
                result[code] = (None, "", None, 0, "none", 3)
        return result

    # 层 2：一次 IN 查询所有 need_hist 的历史涨停日（消除 N+1）
    placeholders = ",".join("?" * len(need_hist))
    code_to_hist_date: dict[str, str] = {}
    try:
        from limitup_screener.data import get_db

        conn = get_db()
        try:
            rows = conn.execute(
                f"SELECT code, MAX(date) AS d FROM gene_scores "
                f"WHERE code IN ({placeholders}) AND date < ? AND date >= date(?, '-30 days') "
                f"GROUP BY code",
                (*need_hist, today, today),
            ).fetchall()
            for r in rows:
                code_to_hist_date[r["code"]] = r["d"]
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        code_to_hist_date = {}

    # 按 distinct 历史日批量 load_gene_scores（同日多股复用）
    hist_gene_cache: dict[str, dict[str, Any]] = {}
    for code in need_hist:
        hist_date = code_to_hist_date.get(code)
        if not hist_date:
            result[code] = (None, "", None, 0, "none", 3)
            continue
        if hist_date not in hist_gene_cache:
            scores = load_gene_scores(hist_date) or []
            hist_gene_cache[hist_date] = {g.code: g for g in scores}
        hist_gene = hist_gene_cache[hist_date].get(code)
        if hist_gene:
            sc, sn, wr, ss, src = _lookup_strategy(code, hist_gene, wr_map)
            if sc:
                result[code] = (sc, sn, wr, ss, "backtest_90d_historical", 2)
                continue
        result[code] = (None, "", None, 0, "none", 3)

    return result


def advise_recommendations(limit: int = 20) -> list[AdvisoryItem]:
    """R2：推荐标的入场建议——top gene_scores + 战法 90 天回测 win_rate。

    取今日（或 DB 最新日）gene_scores 按 total_score 降序 top-N，逐个 match_strategies
    + run_strategy_backtest win_rate，输出入场建议（仓位/止损/止盈/理由）。
    win_rate 替代 v1 合成公式。
    """
    gene_map, data_date, data_stale = _latest_gene_map()
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
        extra, risk_notes = _with_gene_freshness(
            {
                "gene_score": g.total_score, "suggested_pct": pct,
                "stop_loss_pct": stop, "take_profit_pct": take,
            },
            [f"止损 {stop}% / 止盈 {take}%", _DISCLAIMER],
            data_date, data_stale,
        )
        items.append(AdvisoryItem(
            code=g.code, name=g.name or g.code, scene="recommendation", action="enter",
            win_rate=wr, win_rate_source=src, matched_strategy=sn or None,
            reasons=[
                f"基因得分 {g.total_score}",
                f"战法「{sn or '未匹配'}」90 天回测胜率 {wr_disp}",
                f"建议仓位 {int(pct*100)}%（研究参考，非交易指令）",
            ],
            risk_notes=risk_notes,
            extra=extra,
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
    gene_map, data_date, data_stale = _latest_gene_map()
    wr_map = _win_rate_map()
    items: list[AdvisoryItem] = []
    for code in codes:
        g = gene_map.get(code)
        if g is None:
            extra, risk_notes = _with_gene_freshness(
                {"status": "no_signal"}, [_DISCLAIMER], data_date, data_stale,
            )
            items.append(AdvisoryItem(
                code=code, name=code, scene="watchlist", action="no_signal",
                win_rate=None, win_rate_source="none", matched_strategy=None,
                reasons=["该标的当日不在涨停池，无涨停信号"],
                risk_notes=risk_notes, extra=extra,
            ))
            continue
        sc, sn, wr, ss, src = _lookup_strategy(code, g, wr_map)
        params = _strat_params(sc)
        stop = params.get("stop_loss_pct", -7)
        take = params.get("take_profit_pct", 15)
        pct = _suggested_pct(wr)
        wr_disp = f"{wr*100:.0f}%（样本 {ss}）" if wr is not None else "无回测数据"
        extra, risk_notes = _with_gene_freshness(
            {
                "gene_score": g.total_score, "suggested_pct": pct,
                "stop_loss_pct": stop, "take_profit_pct": take,
            },
            [f"止损 {stop}% / 止盈 {take}%", _DISCLAIMER],
            data_date, data_stale,
        )
        items.append(AdvisoryItem(
            code=code, name=g.name or code, scene="watchlist", action="enter",
            win_rate=wr, win_rate_source=src, matched_strategy=sn or None,
            reasons=[
                f"基因得分 {g.total_score}",
                f"战法「{sn or '未匹配'}」90 天回测胜率 {wr_disp}",
                f"建议仓位 {int(pct*100)}%",
            ],
            risk_notes=risk_notes,
            extra=extra,
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
    gene_map, data_date, data_stale = _latest_gene_map()
    wr_map = _win_rate_map()
    # S067 P2-2：批量持仓战法匹配——一次 IN 查询消除 N+1 DB
    holding_codes = [h.get("code") for h in holdings if h.get("code")]
    strat_map = _lookup_holding_strategies_batch(holding_codes, gene_map, wr_map)
    # S067 P1-1：并发预取 kline（layer2/3 需 ATR trailing，预取让循环全命中缓存）
    _prefetch_klines_concurrent(holding_codes)
    items: list[AdvisoryItem] = []
    for h in holdings:
        code = h.get("code")
        name = h.get("name") or code
        # R1.3（S125）：行情取数失败（data_status=degraded，portfolio.py 已把
        # price/pnl_pct 诚实化为 None）→ 跳过止损层判定，不喂伪 -100% 给
        # layer1/2/3 触发 false close。对齐 S111 R4 _empty_capital_flow 范式。
        if h.get("data_status") == "degraded":
            items.append(AdvisoryItem(
                code=code, name=name, scene="holding", action="hold",
                win_rate=None, win_rate_source="none", matched_strategy=None,
                reasons=["行情取数失败，数据缺失不判止损"],
                risk_notes=[_DISCLAIMER, "行情取数失败，持仓盈亏无法核算"],
                extra={"data_status": "degraded", "pnl_pct": None,
                       "cost": h.get("cost"), "price": None, "layer": None},
            ))
            continue
        pnl_pct = h.get("pnl_pct") or 0.0
        cost = h.get("cost") or 0.0
        price = h.get("price") or 0.0

        sc, sn, wr, ss, src, layer = strat_map.get(code, (None, "", None, 0, "none", 3))
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
        extra, risk_notes = _with_gene_freshness(
            {"pnl_pct": pnl_pct, "cost": cost, "price": price, "layer": layer},
            risk_notes, data_date, data_stale,
        )
        items.append(AdvisoryItem(
            code=code, name=name, scene="holding", action=action,
            win_rate=wr, win_rate_source=src, matched_strategy=sn or None,
            reasons=reasons, risk_notes=risk_notes,
            extra=extra,
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
