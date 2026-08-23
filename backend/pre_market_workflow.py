"""
盘前工作流（08:00-09:30）。

职责：
1. 获取昨日涨停板数据 + 龙虎榜
2. 资金流向分析
3. 情绪周期计算
4. 候选池筛选（八项标准过滤）
5. 战法匹配（8大战法自动匹配）
6. 仓位建议
7. 生成盘前报告

S079 R9 仓位闸 + 龙虎榜黑名单两层后处理（在 advise_batch 输出之后、return 之前）：
  Layer 1：DragonTigerSeatFilter.filter —— 龙虎榜席位三分级风控（硬剔除黑名单 + 软标记）
  Layer 2：cap_by_market_phase —— 按 _market_phase 三状态裁剪仓位上限
  叠加代数：final_cap = min(weather_cap, market_phase_cap, max_total_position)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from limitup_screener.models import (
    GENE_HIGH_THRESHOLD,
    GENE_QUALIFY_THRESHOLD,
    GeneScore,
    ScreenerResult,
    compute_gene_score,
)
from limitup_screener.service import get_screener_result
from limitup_strategy import StrategySignal
from strategies.strategy_matcher import StrategyMatcher
from strategies.position_advisor import PositionAdvisor
from vr_paths import last_trading_date_str

logger = logging.getLogger(__name__)

# S079 R9 参数标注（合规：CLAUDE.md §1.1 弱合规，参考值非执行指令）
PARAM_DISCLAIMER = "仓位参数参考值，非执行指令 | 历史统计特征，市场有风险"


@dataclass
class CandidatePool:
    """候选池。"""
    date: str
    candidates: list[GeneScore]
    strong_candidates: list[GeneScore]
    filtered_out: list[dict]
    sector_distribution: dict[str, int]


@dataclass
class StrategyMatch:
    """战法匹配结果。"""
    code: str
    name: str
    matched_strategies: list[StrategySignal]
    best_strategy: str
    confidence: str
    entry_price: float
    stop_loss: float
    take_profit: float
    position_pct: float
    reasons: list[str]


@dataclass
class PositionSuggestion:
    """仓位建议。"""
    code: str
    name: str
    suggested_pct: float
    confidence: str
    entry_price_range: tuple[float, float]
    stop_loss: float
    take_profit: float
    matched_strategy: str
    reasons: list[str]


@dataclass
class PreMarketReport:
    """盘前报告。"""
    date: str
    generated_at: str
    sentiment_index: float | None = None
    sentiment_phase: str | None = None
    candidates: list[GeneScore] = field(default_factory=list)
    strong_candidates: list[GeneScore] = field(default_factory=list)
    filtered_out: list[dict] = field(default_factory=list)
    strategy_matches: list[StrategyMatch] = field(default_factory=list)
    position_suggestions: list[Any] = field(default_factory=list)  # position_advisor.PositionSuggestion（鸭子类型）
    total_suggested_position: float = 0.0
    warnings: list[str] = field(default_factory=list)
    # S079 R9-R10 P2 扩展字段（仓位闸 + 龙虎榜风控 + checklist）
    market_phase: str | None = None           # _market_phase 返回值（冰点/普通/活跃/亢奋/红期）
    market_phase_cap: float | None = None     # 绿1.0/黄0.5/红0.2
    position_cap_tier: str | None = None      # green/yellow/red
    # S096：P2 现象判据（fired_rule + factors，P2RiskPanel 显"为何此 tier"）
    p2_factors: dict | None = None            # {zt_count/big_loss/floor/ladder_success/ladder_height}
    p2_fired_rule: str | None = None          # fired_rule（完整链+红期override+数据降级）
    seat_risk_flags: dict[str, list[str]] = field(default_factory=dict)  # {code: [【拒绝介入】/独食独大/散户霸榜]}
    data_missing_flags: dict[str, str] = field(default_factory=dict)     # {code: 警示字符串}
    execution_checklist: list[str] = field(default_factory=list)
    param_disclaimer: str | None = None        # "仓位参数参考值，非执行指令..."


class PreMarketWorkflow:
    """盘前工作流引擎。"""

    def __init__(self, date: str | None = None):
        self.date = date or last_trading_date_str()
        self._strategy_matcher = StrategyMatcher()
        self._position_advisor = PositionAdvisor()

    async def run(self) -> PreMarketReport:
        """执行盘前工作流。"""
        report = PreMarketReport(date=self.date, generated_at=datetime.now().isoformat())

        # 1. 获取涨停池数据
        try:
            screener_result = await get_screener_result(self.date)
            report.candidates = screener_result.qualified
            report.strong_candidates = screener_result.high_gene
        except Exception as e:
            logger.exception("获取涨停池失败: date=%s", self.date)
            report.warnings.append(f"获取涨停池失败: {e}")
            return report

        # 2. 候选池筛选
        pool = self._build_candidate_pool(screener_result)
        report.candidates = pool.candidates
        report.strong_candidates = pool.strong_candidates
        report.filtered_out = pool.filtered_out

        # 2.5 状态落库（S032 R10）：qualified→candidate、filtered_out→filtered。
        # insert-if-absent：同日重跑不回退用户已推进的状态（watching/holding/…）。
        # 落库是增强不是正确性依赖——失败只 warning，不阻塞盘前主流程。
        self._persist_workflow_states(pool)

        # 3. 战法匹配（使用 StrategyMatcher）——匹配全部 qualified（S031 R15 去 [:20] 上限）
        # S063 T2/T7：管线头部 SentimentContext 一次采集，下传 weather_state
        # S081 C2 修复：从涨停池补取 pool_item 传给 match()，供 PRD 2 战法取 lbc/hs/zdp/p
        #   路径 A：复用 first_board_filter.fetch_zt_pool(date) 取涨停池原始 dict（走 em_get 限流 + 24h 缓存）
        #   按 code 匹配出 pool_item，传给 StrategyMatcher.match(gene, weather_state, pool_item)
        #   缺涨停池数据时 pool_item=None 降级，PRD 战法标"数据缺失"不命中（既有 9 战法不受影响）
        from sentiment_context import build_context  # noqa: PLC0415
        from strategies.first_board_filter import fetch_zt_pool  # noqa: PLC0415
        # S081：PRD2 战法 derived 接线——fetch_derived(code, T-1) 传 match
        from candidate_funnel.sources import derived_source as _derived_src  # noqa: PLC0415
        from vr_paths import prev_trading_date as _prev_td  # noqa: PLC0415
        from datetime import datetime as _dt, timedelta as _td

        ctx = build_context(self.date)
        # T-1（前交易日）供 derived 取数（PRD2 战法 last_lock/broken_duration/max_drop 是 T-1 派生）
        _t1 = _prev_td(_dt.strptime(self.date, "%Y-%m-%d") - _td(days=1)).strftime("%Y-%m-%d") if self.date else None

        # 取涨停池原始 dict，建 code→pool_item 映射（一次取数，循环内复用）
        pool_item_map: dict[str, dict] = {}
        try:
            zt_pool = fetch_zt_pool(self.date)
            # 涨停池 dict 字段：c(代码)/n(名)/lbc(连板)/zbc(炸板)/fbt(首封)/zdp(涨幅)/hs(换手)/p(价)等
            for p in zt_pool or []:
                code = str(p.get("c", "") or "").strip()
                if code:
                    pool_item_map[code] = p
        except Exception as e:
            logger.warning("取涨停池补 pool_item 失败 date=%s err=%s（PRD 战法降级）", self.date, e)

        for stock in pool.candidates:
            try:
                pool_item = pool_item_map.get(stock.code)
                # S081：PRD2 战法 derived（last_lock/broken_duration/max_drop）从 T-1 派生表取
                _derived = _derived_src.fetch_derived(stock.code, _t1) if _t1 else None
                signals = self._strategy_matcher.match(
                    stock, ctx.weather_state, pool_item=pool_item, derived=_derived,
                )
                if signals:
                    best = signals[0]
                    match = StrategyMatch(
                        code=stock.code,
                        name=stock.name,
                        matched_strategies=signals,
                        best_strategy=best.strategy_name,
                        confidence="高" if best.confidence >= 0.7 else "中" if best.confidence >= 0.5 else "低",
                        entry_price=best.entry_price,
                        stop_loss=best.stop_loss,
                        take_profit=best.take_profit,
                        position_pct=0.0,
                        reasons=[m.description for m in best.matches[:3]],
                    )
                    report.strategy_matches.append(match)
            except Exception as e:
                logger.debug("个股策略分析跳过: %s %s", stock.code, e)

        # 4. 仓位建议（使用 PositionAdvisor）—— S063 T8：传 weather_state
        suggestions = self._position_advisor.advise_batch(
            [s for m in report.strategy_matches for s in m.matched_strategies],
            ctx.weather_state,
        )

        # S079 R9：P2 仓位闸 + 龙虎榜黑名单两层后处理（在 return 之前）
        #   Layer 1：DragonTigerSeatFilter.filter —— 龙虎榜席位三分级风控
        #   Layer 2：cap_by_market_phase —— 按 _market_phase 三状态裁剪仓位上限
        p2_result = self._apply_p2_post_filters(suggestions, ctx)
        suggestions = p2_result["position_suggestions"]
        report.position_suggestions = suggestions
        report.total_suggested_position = sum(p.suggested_pct for p in suggestions)

        # S079 R9 P2 扩展字段（仓位闸 + 龙虎榜风控标记，供前端/飞书展示）
        report.market_phase = p2_result.get("market_phase")
        report.market_phase_cap = p2_result.get("market_phase_cap")
        report.position_cap_tier = p2_result.get("position_cap_tier")
        # S096：P2 现象判据 propagate——_apply_p2_post_filters 算了 p2_factors/p2_fired_rule，
        # 此处必须 set 到 report，否则 config_out→briefing→P2RiskPanel 拿不到（CRITICAL：原实现漏这步致 fired_rule 永不显）
        report.p2_factors = p2_result.get("p2_factors")
        report.p2_fired_rule = p2_result.get("p2_fired_rule")
        report.seat_risk_flags = p2_result.get("seat_risk_flags", {})
        report.data_missing_flags = p2_result.get("data_missing_flags", {})
        report.execution_checklist = p2_result.get("execution_checklist", [])
        report.param_disclaimer = PARAM_DISCLAIMER

        # 5. 情绪周期（复用现有 STI）
        try:
            from limitup_sti.service import get_sti_latest
            sti = await get_sti_latest()
            if sti:
                report.sentiment_index = sti.get("score")
                report.sentiment_phase = sti.get("phase")
        except Exception as e:
            logger.debug("获取 STI 失败: %s", e)

        return report

    def _apply_p2_post_filters(
        self,
        suggestions: list,
        ctx,
    ) -> dict[str, Any]:
        """S079 R9 P2 仓位闸 + 龙虎榜黑名单两层后处理。

        串行链（spec §5.1）：
          Layer 1：DragonTigerSeatFilter.filter —— 龙虎榜席位三分级风控
                   输入：suggestions + T-1 龙虎榜（复用 seat_engine）
                   输出：硬剔除后标的 + seat_risk_flags + data_missing_flags
          Layer 2：cap_by_market_phase —— 按 _market_phase 三状态裁剪仓位上限
                   输入：Layer 1 输出 + T+1 _market_phase（从 market._emotion 取 4 因子）
                   叠加：min(weather_cap, market_phase_cap, max_total_position)
                   输出：标的 + 仓位上限

        Args:
            suggestions: PositionAdvisor.advise_batch 输出（position_advisor.PositionSuggestion 列表）
            ctx: SentimentContext（含 weather_state / source_date）

        Returns:
            dict 含：
              position_suggestions: 两层后处理后的标的列表
              market_phase / market_phase_cap / position_cap_tier
              seat_risk_flags / data_missing_flags
              execution_checklist
        """
        from dragon_tiger_seat_filter import DragonTigerSeatFilter  # noqa: PLC0415
        from strategies.first_board_filter import _market_phase, PHASE_TO_CAP_TIER  # noqa: PLC0415
        from strategies.position_advisor import cap_by_market_phase, MARKET_PHASE_CAP  # noqa: PLC0415

        # ---------------------------------------------------------------
        # Layer 1：DragonTigerSeatFilter 龙虎榜席位三分级风控（R1-R5）
        # ---------------------------------------------------------------
        # T-1 交易日（龙虎榜为盘后数据，T+1 盘前使用）
        # ctx.source_date 是 T-1（sentiment_context build_context 取 T-1 STI）
        trade_date = getattr(ctx, "source_date", None) or self.date

        seat_filter = DragonTigerSeatFilter()
        filtered_suggestions, seat_risk_flags, data_missing_flags = seat_filter.filter(
            suggestions=suggestions,
            trade_date=trade_date,
        )

        # ---------------------------------------------------------------
        # Layer 2：cap_by_market_phase 仓位闸后处理（R6-R7）
        # ---------------------------------------------------------------
        # R6.4 从 T-1 盘后市场数据计算 4 因子（复用 market._emotion）
        factors = self._compute_market_phase_factors(trade_date)
        phase = _market_phase(
            zt_count=factors["zt_count"],
            big_loss=factors.get("big_loss"),       # _emotion 无此字段 → None → 降级
            floor=factors.get("floor"),
            ladder_success=factors.get("ladder_success"),
            ladder_height=factors.get("ladder_height"),
        )

        # cap_by_market_phase 叠加代数 min(weather_cap, market_phase_cap, max_total_position)
        # 注：suggestions 已经过 advise_batch 内部 weather_cap 处理，cap_by_market_phase 在此之上叠加
        capped_suggestions = cap_by_market_phase(
            positions=filtered_suggestions,
            phase=phase,
            max_single_position=self._position_advisor.max_single_position,
            max_total_position=self._position_advisor.max_total_position,
        )

        # 三状态展示字段
        tier = PHASE_TO_CAP_TIER.get(phase, "yellow")
        market_phase_cap = MARKET_PHASE_CAP[tier]

        # S096：P2 现象判据——fired_rule（完整链 + 红期 override 显覆盖 + 数据降级标注）
        # would_be_phase = 纯四档（big_loss/floor=None 跳过硬熔断），看硬熔断覆盖了什么
        would_be_phase = _market_phase(
            zt_count=factors["zt_count"],
            big_loss=None, floor=None,
            ladder_success=factors.get("ladder_success"),
            ladder_height=factors.get("ladder_height"),
        )
        p2_fired_rule = self._format_p2_fired_rule(factors, phase, would_be_phase)

        # ---------------------------------------------------------------
        # R9.1 仓位参数 + R10 execution_checklist
        # ---------------------------------------------------------------
        total_cap = sum(p.suggested_pct for p in capped_suggestions)
        n_stocks = len(capped_suggestions)
        # 单笔委托金额 = 总仓位上限 × 个股仓位分配 ÷ 标的数
        # 注：个股仓位分配 = capped_suggestions[i].suggested_pct，总仓位上限 = total_cap
        #   单笔委托金额比例 = suggested_pct（已是总仓位分配，黄色期已在 cap_by_market_phase 砍半）
        checklist = self._build_execution_checklist(
            phase, tier, total_cap, n_stocks, data_missing_flags,
        )

        return {
            "position_suggestions": capped_suggestions,
            "market_phase": phase,
            "market_phase_cap": market_phase_cap,
            "position_cap_tier": tier,
            "p2_factors": factors,  # S096：5 因子值（zt_count/big_loss/floor/ladder_success/ladder_height）
            "p2_fired_rule": p2_fired_rule,  # S096：fired_rule（完整链+override+降级）
            "seat_risk_flags": seat_risk_flags,
            "data_missing_flags": data_missing_flags,
            "execution_checklist": checklist,
        }

    def _format_p2_fired_rule(self, factors: dict, phase: str, would_be_phase: str) -> str:
        """S096：P2 fired_rule 字符串（完整链 + 红期 override 显覆盖 + 数据降级标注）。

        - 红期硬熔断 fired（phase==红期，floor≥20；big_loss 恒 None 不可能 fired）→ 显触发 + 覆盖了什么四档。
        - floor 缺（big_loss 恒缺）→ 红期硬熔断未检，仅四档。
        - 正常四档（floor checked 未 fired）→ 四档 zt→phase。
        big_loss 恒 None（_emotion 无大面股字段）→ big_loss≥8 硬熔断永不 fired，P2RiskPanel 静态标注。
        """
        zt = factors.get("zt_count")
        floor = factors.get("floor")
        if phase == "红期":
            trigger = f"floor={floor}≥20" if floor is not None else "触发因子缺（异常）"
            return f"红期硬熔断 {trigger}（覆盖：四档 zt={zt}→{would_be_phase}）"
        if floor is None:
            return f"红期硬熔断未检（floor 数据缺），仅四档 zt={zt}→{phase}"
        return f"四档 zt={zt}→{phase}"

    def _compute_market_phase_factors(self, trade_date: str) -> dict[str, Any]:
        """S079 R6.4 从 T-1 盘后市场数据计算 _market_phase 4 因子。

        复用 market._emotion() 既有端点（涨停池/跌停池/连板梯队）：
          zt_count       ← _emotion["zt_count"]（涨停家数，既有）
          floor          ← _emotion["dt_count"]（跌停家数 = len(跌停池)）
          ladder_success ← _emotion["promotion_rate"]（连板晋级率 = len(lianban)/yzt_count）
          ladder_height  ← _emotion["max_boards"]（连板最高高度）
          big_loss       ← None（_emotion 无"大面股≥10%家数"字段，取不到标 None 降级）

        取数失败 → 全部 None，_market_phase 降级为只按 zt_count 四档判定（R6.5 兼容）。

        Args:
            trade_date: T-1 交易日（YYYY-MM-DD）

        Returns:
            dict 含 zt_count/big_loss/floor/ladder_success/ladder_height，取不到的字段为 None
        """
        try:
            import market as market_mod  # noqa: PLC0415
            emotion = market_mod._emotion(trade_date) or {}
            return {
                "zt_count": emotion.get("zt_count"),
                "big_loss": None,  # _emotion 无大面股字段，降级（R6.5 兼容）
                "floor": emotion.get("dt_count"),
                "ladder_success": emotion.get("promotion_rate"),
                "ladder_height": emotion.get("max_boards"),
            }
        except Exception as e:
            logger.debug("取 _market_phase 4 因子失败 date=%s err=%s", trade_date, e)
            return {
                "zt_count": None,
                "big_loss": None,
                "floor": None,
                "ladder_success": None,
                "ladder_height": None,
            }

    def _build_execution_checklist(
        self,
        phase: str,
        tier: str,
        total_cap: float,
        n_stocks: int,
        data_missing_flags: dict[str, str],
    ) -> list[str]:
        """S079 R10 人工执行 checklist（参数标注"参考值，非执行指令"）。

        Args:
            phase: _market_phase 返回值（冰点/普通/活跃/亢奋/红期）
            tier: green/yellow/red
            total_cap: 总仓位上限（叠加后）
            n_stocks: 标的数
            data_missing_flags: 数据缺失标记

        Returns:
            checklist 字符串列表
        """
        checklist: list[str] = [
            PARAM_DISCLAIMER,
            f"市场档位：{phase}（{tier}），总仓位上限 {total_cap:.1%}，标的数 {n_stocks}",
        ]
        # 黄色期砍半提示
        if tier == "yellow":
            checklist.append("黄色期仓位砍半：单笔委托金额 = 总仓位上限 × 个股仓位分配 ÷ 标的数")
        # 红期强制熔断提示
        if tier == "red":
            checklist.append("红期强制熔断：仓位上限收紧至 20%，谨慎介入")
        # 龙虎榜【拒绝介入】标的提示
        checklist.append("【拒绝介入】标的（黑名单占比>15%）不可开仓")
        # 数据缺失提示
        if data_missing_flags:
            missing_codes = ", ".join(data_missing_flags.keys())
            checklist.append(f"席位风控数据未取得标的需人工核实龙虎榜：{missing_codes}")
        # 风险提醒
        checklist.append("历史统计特征，市场有风险（CLAUDE.md §1.1 弱合规）")
        return checklist

    def _persist_workflow_states(self, pool: CandidatePool) -> None:
        """S032 R10：候选池状态落库（candidate/filtered）。

        数据全部来自 pool 实际字段（禁臆造）；任何异常就地吞掉并 warning——
        状态记录是增强，不得阻塞盘前报告主流程。
        """
        try:
            import workflow_state_repo as wsr

            for stock in pool.candidates:
                wsr.ensure_candidate(stock.code, stock.name, pool.date, "涨停基因得分达标")
            for item in pool.filtered_out:
                wsr.ensure_filtered(item["code"], item["name"], pool.date, item.get("reason", ""))
        except Exception as e:
            logger.warning("工作流状态落库失败（不影响盘前报告）: %s", e)

    def _build_candidate_pool(self, screener_result: ScreenerResult) -> CandidatePool:
        """构建候选池。"""
        candidates = screener_result.qualified
        strong_candidates = screener_result.high_gene
        filtered_out: list[dict] = []

        # 八项标准过滤（简化版）
        for stock in screener_result.gene_scores:
            if stock not in candidates and stock not in strong_candidates:
                filtered_out.append({
                    "code": stock.code,
                    "name": stock.name,
                    "reason": "基因得分未达标",
                })

        sector_distribution: dict[str, int] = {}
        for stock in candidates:
            # TODO: 从数据中提取板块信息
            sector = "未知"
            sector_distribution[sector] = sector_distribution.get(sector, 0) + 1

        return CandidatePool(
            date=screener_result.date,
            candidates=candidates,
            strong_candidates=strong_candidates,
            filtered_out=filtered_out,
            sector_distribution=sector_distribution,
        )
