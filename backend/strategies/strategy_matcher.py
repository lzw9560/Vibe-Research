"""
战法匹配引擎。

职责：
- 对候选池中的股票，逐只匹配 8 大战法
- 返回匹配结果、置信度、入场/止损/止盈建议
- 与现有 limitup_strategy.py 的 STRATEGY_REGISTRY / match_strategies 对齐
"""
from __future__ import annotations

from typing import Any

from limitup_strategy import (
    STRATEGY_REGISTRY,
    StrategySignal,
    match_strategies,
    get_strategy_registry,
)
from limitup_screener.models import GeneScore


class StrategyMatcher:
    """战法匹配引擎。"""

    def __init__(self) -> None:
        self._registry = STRATEGY_REGISTRY
        self._registry_cache: list[dict] | None = None

    @property
    def registry(self) -> list[dict]:
        """获取战法注册表（带缓存）。"""
        if self._registry_cache is None:
            self._registry_cache = get_strategy_registry()
        return self._registry_cache

    def match(
        self,
        gene: GeneScore,
        weather_state: str | None = None,
        pool_item: dict | None = None,
        indicators: Any = None,
        card: Any = None,  # S084 R6：DiagnosisCard
        derived: dict | None = None,  # S081：显式 derived（pre_market_workflow 无 card 时传）
    ) -> list[StrategySignal]:
        """
        对单只股票匹配所有适用战法。

        直接复用 limitup_strategy.match_strategies，保持策略逻辑单一事实来源。
        S063 T7：传 weather_state 时，为每条 signal 调 calc_weather_fit 标注适配度。

        S081 C2 修复：pool_item 是涨停池原始 dict（含 lbc/hs/zdp/p 等字段），
        供 PRD 2 战法（weak_turn_strong/pattern_reversal）取因子。
        - pool_item=None（默认）：既有 9 战法不依赖 pool_item，行为不变；
          PRD 2 战法因子取 None 不命中（降级，不报错）
        - pool_item 非空：PRD 2 战法正常取 lbc/hs/zdp/p 做判定

        S081 重构：indicators 是 candidate_funnel.IndicatorSet（漏斗 R2 输出），
        含 max_high_pct/shadow_length_pct/ma_5_status/prev_turnover_pct（activity.py 从 K线扩展算）。
        PRD 2 战法从 indicators 读这些字段，消除 match_strategies 各自调 astock/kline 重复取数。
        - indicators=None（默认）：PRD 战法降级标"数据缺失"不命中（既有 9 战法不受影响）

        pool_item 来源（路径 A）：pre_market_workflow 从 astock.em_zt_topic_pool
        取涨停池，按 code 匹配出原始 dict 传入。em_zt_topic_pool 走 em_get
        限流（防封底线不可绕过）+ 24h 缓存。
        indicators 来源：pre_market_workflow 从候选池漏斗 FunnelResult.final_candidates
        取该 code 的 DiagnosisCard.indicators，建 {code: IndicatorSet} 映射传入。
        run_funnel 有缓存兜底，同日多次调不重复取数。
        """
        signals = match_strategies(gene.code, gene, pool_item, indicators, card=card, derived=derived)
        if weather_state is not None:
            from limitup_strategy import calc_weather_fit  # noqa: PLC0415
            for s in signals:
                s.weather_fit = calc_weather_fit(s.strategy_code, weather_state)
        return signals

    def match_batch(
        self,
        genes: list[GeneScore],
        weather_state: str | None = None,
        pool_items: dict[str, dict] | None = None,
        indicators_map: dict[str, Any] | None = None,
        cards_map: dict[str, Any] | None = None,  # S084 R6：{code: DiagnosisCard}
    ) -> dict[str, list[StrategySignal]]:
        """
        批量匹配，返回 {code: signals}。

        S081 C2 修复：pool_items 是 {code: pool_item_dict} 映射，
        供 PRD 2 战法取因子。pool_items=None 时降级（既有 9 战法不受影响）。
        S081 重构：indicators_map 是 {code: IndicatorSet} 映射，供 PRD 2 战法取 K线派生因子。
        """
        results: dict[str, list[StrategySignal]] = {}
        for gene in genes:
            pool_item = pool_items.get(gene.code) if pool_items else None
            indicators = indicators_map.get(gene.code) if indicators_map else None
            card = cards_map.get(gene.code) if cards_map else None
            results[gene.code] = self.match(gene, weather_state, pool_item, indicators, card=card)
        return results

    def get_best_strategy(self, gene: GeneScore) -> StrategySignal | None:
        """获取匹配度最高的战法信号（按 risk_reward_ratio * confidence_mapped_winrate 排序，合成 heuristic）。"""
        signals = self.match(gene)
        if not signals:
            return None
        return signals[0]

    def get_strategy_by_code(self, code: str) -> dict | None:
        """按 code 获取战法定义。"""
        for s in self.registry:
            if s["code"] == code:
                return s
        return None

    def list_strategies(self) -> list[dict]:
        """列出所有可用战法。"""
        return self.registry

    def clear_cache(self) -> None:
        """清除注册表缓存（战法定义更新后调用）。"""
        self._registry_cache = None


# 全局单例
matcher = StrategyMatcher()
