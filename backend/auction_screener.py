# -*- coding: utf-8 -*-
"""竞价选股模块（盘后批量分析）—— 生成次日竞价预案 TOP N。

定位：客观数据展示，非行动建议。所有文字使用「历史统计特征」「策略逻辑上」等中性表述。
数据源：东财涨停板四池 + 涨停基因得分（复用 limitup_screener.py），非实时竞价扫描。
缓存：TTL 12 小时日频预计算 + 内存缓存，key="auction_screener_{date}"。
"""

from __future__ import annotations

import logging
import os
import time
import threading as _threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

import astock

BEIJING_TZ = datetime.now().astimezone().tzinfo

# ---- 配置（通过 .env 覆盖，开发者配置） ----
AUCTION_TOP_N = int(os.getenv("AUCTION_TOP_N", "50"))
AUCTION_MIN_GENE_SCORE = float(os.getenv("AUCTION_MIN_GENE_SCORE", "50"))
AUCTION_MIN_ZT_COUNT = int(os.getenv("AUCTION_MIN_ZT_COUNT", "2"))


def _round_to_tick_size(price: float, tick_size: float = 0.01) -> float:
    """A股 tick-size rounding（默认 0.01 元）。"""
    return round(round(price / tick_size) * tick_size, 2)


def _validate_limit_up_price(prev_close: float, code: str = "") -> tuple[float, float]:
    """计算A股涨跌停价（支持主板/创业板/科创板/ST股）。"""
    if not prev_close or prev_close <= 0:
        return 0.0, 0.0
    if code.startswith(("300", "301", "688", "689")):
        limit = 0.20
    elif "ST" in (code or ""):
        limit = 0.05
    else:
        limit = 0.10
    up = _round_to_tick_size(prev_close * (1 + limit))
    down = _round_to_tick_size(prev_close * (1 - limit))
    return up, down

# ---- 缓存 ----
_CACHE: dict = {}
_CACHE_TTL = 43200  # 12 小时
_COMPUTING: dict = {}

# ---- 免责声明 ----
AUCTION_DISCLAIMER = (
    "免责声明：本页面展示的竞价预案基于历史统计特征，不代表未来行为，不构成投资建议。"
    "股市有风险，投资需谨慎。所有分析由用户自己的 AI 给出，Vibe-Research 仅提供数据呈现工具。"
)


# ===========================================================================
# 1. 数据结构
# ===========================================================================

class AuctionCandidate(BaseModel):
    """竞价候选股（客观数据，非行动建议）。

    .. deprecated::
        优先使用 ``limitup_strategy.StrategySignal`` 统一信号结构。
    """

    code: str                          # 股票代码
    name: str                          # 股票名称
    score: float                       # 竞价综合得分 0-100
    gene_score: float                  # 涨停基因得分
    zt_count_30d: int                  # 近30日涨停次数
    seal_rate: float                   # 封板率
    avg_fbt: float                     # 平均封板时间
    promotion_rate: float              # 近期晋级率
    prev_zt_return: float              # 昨日涨停股今日平均收益率
    max_boards: int                    # 近期最高连板数
    strategy_tags: list[str] = field(default_factory=list)  # 战法标签
    signal_strength: int = 0           # 信号强度 1-5
    confidence: str = "medium"         # 置信度 high/medium/low
    seal_amount: float = 0.0           # 封单额（元）
    float_shares: float = 0.0          # 流通盘（股）
    seal_to_float_ratio: float = 0.0   # 封单/流通盘比

    model_config = {"arbitrary_types_allowed": True}


class AuctionScreenerResult(BaseModel):
    """竞价选股结果（客观数据展示）。"""

    date: str
    candidates: list[dict]  # TOP N 候选股，统一为通用字典结构
    sti_score: float | None            # 当日 STI 情绪分数
    sti_phase: str | None              # 当日 STI 阶段
    total_analyzed: int                # 分析的股票总数
    updated: str                       # 更新时间
    disclaimer: str = AUCTION_DISCLAIMER


# ===========================================================================
# 2. 竞价评分引擎
# ===========================================================================

class AuctionScreener:
    """
    每日 15:30 后批量分析当日涨停池数据，生成次日竞价预案 TOP N。
    
    非实时扫描，而是历史竞价模式回放 + 次日预案生成。
    复用涨停基因得分、封板率、晋级率等客观数据作为竞价强度代理指标。
    """

    def __init__(self):
        self._db = None  # 复用现有 SQLite 连接（预留）

    def analyze(self, trade_date: str) -> AuctionScreenerResult:
        """
        输入：交易日 YYYY-MM-DD
        输出：按竞价综合得分排序的候选股列表（TOP N）
        
        步骤：
        1. 获取当日涨停池 + 昨涨停池 + 炸板池
        2. 获取基因得分缓存
        3. 获取 STI 情绪分数
        4. 计算每只候选股的竞价综合得分
        5. 生成战法标签
        6. 排序取 TOP N
        """
        # 转换日期格式
        date_fmt = trade_date.replace("-", "") if "-" in trade_date else trade_date
        
        # 1. 获取涨停池数据
        zt_pool = astock.em_zt_topic_pool("getTopicZTPool", date_fmt, "fbt:asc")
        yzt_pool = astock.em_zt_topic_pool("getYesterdayZTPool", date_fmt, "zs:desc")
        zb_pool = astock.em_zt_topic_pool("getTopicZBPool", date_fmt, "fbt:asc")
        
        if not zt_pool:
            return AuctionScreenerResult(
                date=trade_date,
                candidates=[],
                sti_score=None,
                sti_phase=None,
                total_analyzed=0,
                updated=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            )
        
        # 2. 获取基因得分缓存
        gene_scores_map = self._get_gene_scores_cache()
        
        # 3. 获取 STI 情绪分数
        sti_result = self._get_sti_result(trade_date)
        
        # 4. 计算每只候选股的竞价综合得分
        candidates = []
        for item in zt_pool:
            code = str(item.get("c", ""))
            name = item.get("n", "")
            
            if not code.isdigit() or len(code) != 6:
                continue
            
            # 提取池字段
            lbc = astock._numf(item.get("lbc", 0)) or 0           # 连板数
            fbt = astock._numf(item.get("fbt", 0)) or 0           # 封板时间
            zbc = astock._numf(item.get("zbc", 0)) or 0           # 炸板次数
            zje = astock._numf(item.get("zje", 0)) or 0           # 涨停价
            open_price = astock._numf(item.get("open", 0)) or 0   # 开盘价
            seal_amount = astock._numf(item.get("seal_amount")) or 0.0  # 封单额（元）
            float_shares = astock._numf(item.get("float_shares")) or 0.0  # 流通盘（股）
            prev_close = astock._numf(item.get("prev_close")) or 0.0  # 昨收价

            # A股涨跌停价校验 + tick-size rounding
            if prev_close > 0 and zje > 0:
                limit_up, limit_down = _validate_limit_up_price(prev_close, code)
                if zje > limit_up * 1.01 or zje < limit_down * 0.99:
                    _logger.warning("价格异常: code=%s, zje=%s, prev_close=%s, limit_up=%s, limit_down=%s", code, zje, prev_close, limit_up, limit_down)

            # 封单/流通盘比
            seal_to_float_ratio = (seal_amount / float_shares) if float_shares > 0 else 0.0
            
            # 基因得分
            gene_score = gene_scores_map.get(code, {}).get("total_score", 0)
            
            # 封板率（基于 fbt 归一化）
            seal_rate = self._calculate_seal_rate(fbt)
            
            # 炸板率（zbc 越多封板质量越差）
            break_rate = min(zbc / 5.0, 1.0) if zbc > 0 else 0.0
            
            # 晋级率（今日涨停 / 昨日涨停）
            promotion_rate = self._calculate_promotion_rate(zt_pool, yzt_pool)
            
            # 昨日涨停股今日平均收益率
            prev_zt_return = self._calculate_prev_zt_return(zt_pool, yzt_pool)
            
            # 连板高度
            max_boards = max((astock._numf(i.get("lbc", 0)) or 0) for i in zt_pool)
            
            # 近30日涨停次数（从基因得分缓存中提取）
            zt_count_30d = gene_scores_map.get(code, {}).get("zt_count_30d", 0)
            
            # 计算竞价综合得分
            auction_score = self._calculate_auction_score(
                lbc=lbc,
                seal_rate=seal_rate,
                break_rate=break_rate,
                gene_score=gene_score,
                promotion_rate=promotion_rate,
                prev_zt_return=prev_zt_return,
                max_boards=max_boards,
                zt_count_30d=zt_count_30d,
            )
            
            # 生成战法标签
            strategy_tags = self._generate_strategy_tags(
                lbc=lbc,
                seal_rate=seal_rate,
                gene_score=gene_score,
                promotion_rate=promotion_rate,
            )
            
            # 信号强度
            signal_strength = min(5, max(1, int(auction_score / 20)))
            
            # 置信度
            confidence = self._calculate_confidence(
                zt_count_30d=zt_count_30d,
                gene_score=gene_score,
                seal_rate=seal_rate,
            )
            
            candidates.append({
                "code": code,
                "name": name,
                "score": round(auction_score, 2),
                "gene_score": round(gene_score, 2),
                "zt_count_30d": zt_count_30d,
                "seal_rate": round(seal_rate, 2),
                "avg_fbt": round(fbt, 0),
                "promotion_rate": round(promotion_rate, 2),
                "prev_zt_return": round(prev_zt_return, 2),
                "max_boards": int(max_boards),
                "strategy_tags": strategy_tags,
                "signal_strength": signal_strength,
                "confidence": confidence,
                "seal_amount": round(seal_amount, 2),
                "float_shares": round(float_shares, 2),
                "seal_to_float_ratio": round(seal_to_float_ratio, 6),
            })
        
        # 5. 排序取 TOP N
        candidates.sort(key=lambda c: c["score"], reverse=True)
        top_candidates = candidates[:AUCTION_TOP_N]
        
        # 6. 返回结果
        return AuctionScreenerResult(
            date=trade_date,
            candidates=top_candidates,
            sti_score=sti_result.get("score") if sti_result else None,
            sti_phase=sti_result.get("phase") if sti_result else None,
            total_analyzed=len(candidates),
            updated=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        )
    
    def _calculate_seal_rate(self, fbt: float) -> float:
        """
        基于封板时间归一化封板率。
        
        fbt=92500（9:25 一字板）→ 100 分
        fbt=145000（14:50 封板）→ 0 分
        线性插值
        """
        if fbt <= 92500:
            return 100.0
        elif fbt >= 145000:
            return 0.0
        else:
            return max(0.0, min(100.0, (1 - (fbt - 92500) / (145000 - 92500)) * 100))
    
    def _calculate_promotion_rate(self, zt_pool: list[dict], yzt_pool: list[dict]) -> float:
        """
        晋级率 = 今日涨停数 / 昨日涨停数。
        
        > 1.0 表示情绪延续，< 1.0 表示情绪减弱。
        """
        zt_count = len(zt_pool)
        yzt_count = len(yzt_pool)
        if yzt_count == 0:
            return 100.0
        return (zt_count / yzt_count) * 100.0
    
    def _calculate_prev_zt_return(self, zt_pool: list[dict], yzt_pool: list[dict]) -> float:
        """
        昨日涨停股今日平均收益率代理指标。
        
        MVP 使用 zt_count / yzt_count * 100（情绪惯性核心指标）。
        Phase 3+ 可升级为真实涨跌幅计算。
        """
        return self._calculate_promotion_rate(zt_pool, yzt_pool)
    
    def _calculate_auction_score(
        self,
        lbc: int,
        seal_rate: float,
        break_rate: float,
        gene_score: float,
        promotion_rate: float,
        prev_zt_return: float,
        max_boards: int,
        zt_count_30d: int,
    ) -> float:
        """
        竞价综合得分 = f(连板数, 封板率, 基因得分, 晋级率, 连板高度, 涨停频次)
        
        权重分配：
        - 封板质量（seal_rate × (1-break_rate)）: 0.25
        - 连板高度（lbc）: 0.20
        - 涨停基因得分: 0.20
        - 情绪惯性（prev_zt_return）: 0.15
        - 晋级率: 0.10
        - 涨停频次（zt_count_30d 归一化）: 0.10
        """
        # 封板质量分
        seal_quality = seal_rate * (1 - break_rate)
        
        # 连板高度分（0-3 板映射 0-100）
        lbc_score = min(lbc / 3.0, 1.0) * 100
        
        # 涨停频次分（0-10 次映射 0-100）
        zt_count_score = min(zt_count_30d / 10.0, 1.0) * 100
        
        # 加权合成
        score = (
            seal_quality * 0.25 +
            lbc_score * 0.20 +
            gene_score * 0.20 +
            min(prev_zt_return, 150) / 150 * 100 * 0.15 +
            min(promotion_rate, 150) / 150 * 100 * 0.10 +
            zt_count_score * 0.10
        )
        
        return min(score, 100.0)
    
    def _generate_strategy_tags(
        self,
        lbc: int,
        seal_rate: float,
        gene_score: float,
        promotion_rate: float,
    ) -> list[str]:
        """
        生成战法标签。
        
        三种战法：
        - 一进二：昨日首板 + 今日高开 + 竞价量>昨日全天 3%
        - 首板低开：昨日涨停但今日低开 + 近2月相对位置<50%
        - 弱转强：昨日摸涨停未封住 + 今日平开/高开 + 竞价放量
        """
        tags = []
        
        # 一进二候选
        if lbc == 1 and gene_score >= AUCTION_MIN_GENE_SCORE:
            tags.append("一进二")
        
        # 连板候选
        if lbc >= 2:
            tags.append(f"{lbc}连板")
        
        # 高封板率
        if seal_rate >= 80:
            tags.append("高封板率")
        
        # 基因高分
        if gene_score >= AUCTION_MIN_GENE_SCORE:
            tags.append("基因高分")
        
        # 情绪延续
        if promotion_rate >= 100:
            tags.append("情绪延续")
        
        return tags
    
    def _calculate_confidence(
        self,
        zt_count_30d: int,
        gene_score: float,
        seal_rate: float,
    ) -> str:
        """
        置信度计算。
        
        high: zt_count_30d >= 3 AND gene_score >= 60 AND seal_rate >= 70
        medium: 其他情况
        low: gene_score < 40 OR seal_rate < 30
        """
        if gene_score < 40 or seal_rate < 30:
            return "low"
        if zt_count_30d >= 3 and gene_score >= 60 and seal_rate >= 70:
            return "high"
        return "medium"
    
    def _get_gene_scores_cache(self) -> dict[str, dict]:
        """
        获取基因得分缓存。

        从 limitup_screener 的缓存中提取近30日数据。
        如果缓存不存在，则返回空映射，避免写入无效缓存。
        """
        cache_key = "limitup_screener"
        cached = _CACHE.get(cache_key)
        
        if cached and time.time() - cached[0] < _CACHE_TTL:
            return cached[1]
        
        return {}
    
    def _get_sti_result(self, trade_date: str) -> dict[str, Any] | None:
        """
        获取 STI 情绪分数。

        从 sti_timeline 表中查询当日数据。
        """
        try:
            from limitup_sti import STIEngine
            engine = STIEngine()
            result = engine.get_latest(trade_date)
            if result and result.source_ok:
                return {
                    "score": result.score,
                    "phase": result.phase.value if result.phase else None,
                }
        except Exception:
            pass
        return None
    
    def precompute_daily(self, date: str) -> AuctionScreenerResult:
        """每日预计算入口 — 由 app.py 15:35 调度器触发。"""
        result = self.analyze(date)
        
        # 写入缓存
        cache_key = f"auction_screener_{date}"
        _CACHE[cache_key] = (time.time(), result)
        
        return result
    
    def backfill(self, start_date: str, end_date: str | None = None) -> list[AuctionScreenerResult]:
        """
        历史回填 — 分批执行（每批 30 天），节流 time.sleep(1.2)。
        
        注意：竞价选股模块主要依赖涨停池数据，不需要大量 HTTP 请求，
        回填速度较快。
        """
        if end_date is None:
            end_date = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
        
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        
        results = []
        current_dt = start_dt
        
        while current_dt <= end_dt:
            date_str = current_dt.strftime("%Y-%m-%d")
            try:
                result = self.precompute_daily(date_str)
                results.append(result)
            except Exception as e:
                logging.getLogger("vibe-research").warning("[%s] 预计算失败: %s", date_str, e)
            
            current_dt += timedelta(days=1)
            time.sleep(0.5)  # 节流（竞价模块不大量请求 HTTP，降低间隔）
        
        return results


# ===========================================================================
# 3. 全局实例
# ===========================================================================

_screener_instance: AuctionScreener | None = None


def get_screener() -> AuctionScreener:
    """获取全局 AuctionScreener 实例（单例）。"""
    global _screener_instance
    if _screener_instance is None:
        _screener_instance = AuctionScreener()
    return _screener_instance
