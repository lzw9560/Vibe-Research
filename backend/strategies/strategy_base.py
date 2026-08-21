# -*- coding: utf-8 -*-
"""S086 涨停战法 pipeline 统一架构 —— Strategy 协议 + 调度器 + 上下文准备。

消灭 limitup_strategy.match_strategies 的 350 行 if/elif switch dispatch：
- 每战法一个 Strategy 类（impl/ 下按数据依赖维度分 4 文件）
- 调度器 dispatch_match 遍历单一注册表，各 Strategy.match → 组装 StrategySignal
- 旧 match_strategies(code, gene, ...) 保留为兼容包装（build ctx → dispatch_match）

向后兼容（spec 硬约束 #1，7+ 文件引用 STRATEGY_REGISTRY/match_strategies）：
- StrategyConfig 是 dataclass，同时支持属性访问与 dict 访问
  （__getitem__/get/__contains__/keys），令既有 s["code"]/s.get(...) 消费方零改动，
  含 test_advisory/test_s085 monkeypatch 的纯 dict mock 仍可用。
- match_strategies 签名不变（code, gene, pool_item, indicators, card）。
- ConditionMatch 沿用 pydantic BaseModel（与 limitup_strategy.StrategySignal.matches 同源），
  避免 StrategySignal 组装时的 pydantic 校验冲突。

工程底线（CLAUDE.md §1.2）：阈值/字符串严格按 limitup_strategy.py 既有分支迁移，不改阈值；
derived fallback 上提到调度器（_prepare_derived），Strategy 类不自己取数。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime as _dt
from typing import Any, Protocol

from pydantic import BaseModel


# ===========================================================================
# 数据结构
# ===========================================================================

class ConditionMatch(BaseModel):
    """单个条件匹配结果（教育性展示）。

    沿用 limitup_strategy.ConditionMatch 字段（condition/value/description），
    供 StrategySignal.matches 复用，避免 pydantic 校验冲突。
    """

    condition: str
    value: str
    description: str


@dataclass
class StrategyContext:
    """调度器统一准备的上下文容器，各 Strategy 按需读字段。"""

    code: str
    gene: Any                   # GeneScore（因子得分）
    pool_item: dict | None      # 涨停池原始 dict（lbc/zbc/fbt/zdp/hs/p/fund）
    indicators: Any | None      # candidate_funnel.IndicatorSet（K线派生）
    derived: dict | None        # S070 R7 分时派生（broken_duration_min/max_drop_pct/last_lock_time）
    weather_state: str | None   # 天气（软标注，不做硬开关）


class StrategyProtocol(Protocol):
    """战法协议：每个战法一个实现。"""

    @property
    def code(self) -> str: ...

    @property
    def name(self) -> str: ...

    def match(self, ctx: StrategyContext) -> list[ConditionMatch]: ...

    def compute_confidence(self, matches: list[ConditionMatch], ctx: StrategyContext) -> float: ...

    def compute_entry_price(self, ctx: StrategyContext) -> float:
        """默认返回 tick 对齐的 pool_item.p（R2 真实涨停价）；
        pool_item 缺失时 fallback gene.total_score（价格代理，调度器加标注）。"""
        ...


@dataclass(frozen=True)
class PositionParams:
    """止损/止盈/最大持有期（向后兼容 routers/strategy.py + test 的 .position_params 访问）。"""

    stop_loss_pct: float        # 负数（-3.0 = -3%）
    take_profit_pct: float       # 正数（+8.0 = +8%）
    max_hold_days: int
    position_scale: float = 1.0  # 仓位缩放（暴风暴 0.3，建议不强制）


@dataclass(frozen=True)
class QualityCheck:
    """策略特定质量标准项。"""

    name: str
    required: bool
    description: str = ""


@dataclass(frozen=True)
class StrategyConfig:
    """单一注册表项：参数 + 指向 Strategy 实现。

    合并旧 STRATEGY_REGISTRY（dict）+ STRATEGY_FUNNEL_REGISTRY（dataclass）的超集。
    向后兼容：同时支持属性访问（s.code / s.position_params.stop_loss_pct）
    与 dict 访问（s["code"] / s.get("note","")），令既有 dict 消费方与
    monkeypatch 的纯 dict mock 零改动。
    """

    code: str
    name: str
    strategy_impl: StrategyProtocol
    # 仓位参数
    stop_loss_pct: float
    take_profit_pct: float
    max_hold_days: int
    position_scale: float = 1.0           # 仓位缩放（建议，不强制）
    # 漏斗参数
    funnel_type: str = "limitup"
    weight_set: str = "limitup"
    weather_regimes: list[str] = field(default_factory=list)  # 软标注
    is_primary: bool = True
    fallback: bool = False
    activation_note: str | None = None     # 非空=当前不可用（清过时标注后置 None）
    # 文本
    entry_type: str = ""
    entry_condition: str = ""
    stop_loss_condition: str = ""
    take_profit_condition: str = ""
    exit_condition: str = ""
    note: str = ""
    aliases: list[str] = field(default_factory=list)
    quality_standards: list[QualityCheck] = field(default_factory=list)

    @property
    def position_params(self) -> PositionParams:
        """嵌套访问兼容（routers/strategy.py:156 / test:100 读 .position_params.*）。"""
        return PositionParams(
            self.stop_loss_pct, self.take_profit_pct, self.max_hold_days, self.position_scale,
        )

    # ---- dict 兼容：s["code"] / s.get(...) / "x" in s ----
    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError as exc:  # pragma: no cover - dict 语义
            raise KeyError(key) from exc

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def keys(self) -> list[str]:
        return [f.name for f in dataclasses.fields(self)]

    def values(self) -> list[Any]:
        return [getattr(self, f.name) for f in dataclasses.fields(self)]

    def items(self) -> list[tuple[str, Any]]:
        return [(f.name, getattr(self, f.name)) for f in dataclasses.fields(self)]


# ===========================================================================
# Strategy 基类（impl/ 各战法继承）
# ===========================================================================

def _round_to_tick_size(price: float, tick_size: float = 0.01) -> float:
    """A股 tick-size rounding（与 limitup_strategy._round_to_tick_size / limitup_screener.models 同款）。"""
    return round(round(price / tick_size) * tick_size, 2)


class BaseStrategy:
    """Strategy 基类：提供默认 compute_entry_price；子类实现 match + compute_confidence。

    子类以类属性声明 code/name（满足 StrategyProtocol 的属性访问）。
    """

    code: str = ""
    name: str = ""

    def match(self, ctx: StrategyContext) -> list[ConditionMatch]:  # pragma: no cover - abstract
        raise NotImplementedError

    def compute_confidence(self, matches: list[ConditionMatch], ctx: StrategyContext) -> float:
        return 0.0

    def compute_entry_price(self, ctx: StrategyContext) -> float:
        """默认入场价 = tick 对齐的 pool_item.p（R2 真实涨停价）；
        pool_item 缺失时 fallback gene.total_score（价格代理，调度器加标注）。"""
        if ctx.pool_item and ctx.pool_item.get("p"):
            return _round_to_tick_size(float(ctx.pool_item["p"]))
        return round(float(ctx.gene.total_score), 2)


# ===========================================================================
# 调度器
# ===========================================================================

def dispatch_match(ctx: StrategyContext, registry: list[StrategyConfig]) -> list:
    """调度器：遍历注册表，各 Strategy.match → 组装 StrategySignal。

    Strategy 类只返回 ConditionMatch + confidence + entry_price；
    止损/止盈/历史统计/disclaimer 由调度器统一组装（避免 12 份重复代码）。
    单战法异常不阻断其余（catch continue）。
    """
    # 延迟 import：limitup_strategy 顶层 import astock，避免本模块加载时强拉依赖链
    from limitup_strategy import StrategySignal

    signals: list = []
    for cfg in registry:
        impl = cfg.strategy_impl
        try:
            matches = impl.match(ctx)
        except Exception:  # noqa: BLE001 - 单战法异常不阻断其余
            continue
        if not matches:
            continue
        confidence = impl.compute_confidence(matches, ctx)
        if confidence == 0.0:
            continue

        entry_price = impl.compute_entry_price(ctx)
        # R2/A7：pool_item 缺失 → 入场价为基因得分代理，标注"价格代理"
        is_price_proxy = not (ctx.pool_item and ctx.pool_item.get("p"))

        stop_loss = round(entry_price * (1 + cfg.stop_loss_pct / 100), 2)
        take_profit = round(entry_price * (1 + cfg.take_profit_pct / 100), 2)
        historical_win_rate = min(confidence * 0.8 + 0.2, 0.95)
        historical_avg_return = round(
            (cfg.take_profit_pct - cfg.stop_loss_pct) / 2 * historical_win_rate, 2,
        )

        # S081 A8/B7：PRD 战法参数标注"参考值，非执行指令"
        prd_disclaimer = ""
        if cfg.code in ("weak_turn_strong", "pattern_reversal"):
            prd_disclaimer = "参数为参考值，非执行指令；历史统计特征不代表未来行为，市场有风险"

        risk_notes = [
            f"历史统计样本量：{ctx.gene.zt_count_250d}次",
            f"策略逻辑上，该战法历史平均收益：{historical_avg_return}%",
            "历史统计特征不代表未来行为，仅作研究参考",
        ]
        if prd_disclaimer:
            risk_notes.append(prd_disclaimer)
        if is_price_proxy:
            risk_notes.append("入场价为基因得分代理（价格代理），非真实涨停价")

        signals.append(StrategySignal(
            code=ctx.code,
            name=ctx.gene.name,
            strategy_name=cfg.name,
            strategy_code=cfg.code,
            score=ctx.gene.total_score,
            signal_strength=int(confidence * 100),
            confidence=round(confidence, 2),
            matches=matches,
            logic_description="；".join(m.description for m in matches) + "。",
            strategy_tags=[cfg.name],
            entry_price=entry_price,
            entry_condition=cfg.entry_condition,
            entry_type=cfg.entry_type,
            stop_loss=stop_loss,
            stop_loss_condition=cfg.stop_loss_condition,
            take_profit=take_profit,
            take_profit_condition=cfg.take_profit_condition,
            max_hold_days=cfg.max_hold_days,
            exit_condition=cfg.exit_condition,
            historical_win_rate=round(historical_win_rate, 2),
            historical_avg_return=historical_avg_return,
            sample_size=ctx.gene.zt_count_250d,
            risk_reward_ratio=round(abs(cfg.take_profit_pct / cfg.stop_loss_pct), 2),
            conditions={
                "entry_condition": cfg.entry_condition,
                "stop_loss_condition": cfg.stop_loss_condition,
                "take_profit_condition": cfg.take_profit_condition,
                "exit_condition": cfg.exit_condition,
            },
            reasoning=[m.description for m in matches],
            risk_notes=risk_notes,
        ))

    # 按风险收益比 × 历史胜率排序（与旧 match_strategies 一致）
    signals.sort(key=lambda s: s.risk_reward_ratio * s.historical_win_rate, reverse=True)
    return signals


# ===========================================================================
# 上下文准备（R8 derived fallback 上提 + R7 pool_item_map）
# ===========================================================================

def _prepare_derived(card_derived: dict | None, code: str) -> dict | None:
    """调度器统一准备 derived，T-1 vs 今日由调用方传参决定。

    card_derived 非空 → 直接返回（调用方传了 T-1 值，S084 R3 override）；
    None → fallback 取今日 snapshots（S070 R7 自补，与旧 weak_turn_strong 分支一致）；
    snapshots 缺失 / data_status=missing / 异常 → None（Strategy 层读 None 因子不命中）。
    """
    if card_derived is not None:
        return card_derived
    try:
        from risk.seal_intraday_collector import get_snapshots_by_code
        from strategies.intraday_features import compute_derived_features

        _snaps = get_snapshots_by_code(code, _dt.now().strftime("%Y-%m-%d"))
        if not _snaps:
            return None
        derived = compute_derived_features(_snaps)
        return None if derived.get("data_status") == "missing" else derived
    except Exception:  # noqa: BLE001 - 数据缺失降级 None，不阻断
        return None


def _prepare_pool_item(pool_item_map: dict[str, dict] | None, code: str) -> dict | None:
    """从 pool_item_map 取该 code 的涨停池原始 dict（R7）。"""
    if not pool_item_map:
        return None
    return pool_item_map.get(code)


# ===========================================================================
# 兼容包装：旧 match_strategies(code, gene, pool_item, indicators, card)
# ===========================================================================

def match_strategies(
    code: str,
    gene: Any,
    pool_item: dict | None = None,
    indicators: Any = None,
    card: Any = None,
    derived: dict | None = None,  # S081：显式 derived（pre_market_workflow 无 card 时直传 fetch_derived）
) -> list:
    """旧签名兼容包装：build StrategyContext → dispatch_match。

    保留原签名以兼容所有既有调用方（strategy_matcher / strategy_backtest /
    position_advisor_v2 / prediction_ingest / score_candidates + 测试）。
    card 非空时从 card 子对象 override 读 pool_item/indicators/derived（S084 R5）。
    S081：derived 参数优先（pre_market_workflow 无 card 时直传 fetch_derived 结果）。
    """
    if card is not None:
        if pool_item is None:
            pool_item = getattr(card, "pool_item", None)
        if indicators is None:
            indicators = getattr(card, "indicators", None)
        if derived is None:
            derived = getattr(card, "derived", None)

    derived = _prepare_derived(derived, code)
    ctx = StrategyContext(
        code=code,
        gene=gene,
        pool_item=pool_item,
        indicators=indicators,
        derived=derived,
        weather_state=None,
    )
    # 延迟 import 打破环：strategy_base ← strategy_funnel_registry ← impl ← strategy_base
    from strategies.strategy_funnel_registry import STRATEGY_REGISTRY
    return dispatch_match(ctx, STRATEGY_REGISTRY)
