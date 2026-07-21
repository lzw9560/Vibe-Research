# -*- coding: utf-8 -*-
"""每日复盘报告生成模块（盘后自动生成结构化摘要）。

定位：客观数据展示，非行动建议。所有文字使用「历史统计特征」「策略逻辑上」等中性表述。
数据源：东财涨停板四池 + STI 情绪引擎 + 竞价选股模块。
缓存：TTL 12 小时日频预计算 + 内存缓存，key="daily_review_{date}"。
"""

from __future__ import annotations

import os
import time
import threading as _threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

import astock

BEIJING_TZ = datetime.now().astimezone().tzinfo

# ---- 配置 ----
REVIEW_MAX_ZT_STOCKS = 100  # 涨停股展示上限
REVIEW_AUCTION_TOP_N = 20  # 竞价回顾 TOP N

# ---- 缓存 ----
_CACHE: dict = {}
_CACHE_TTL = 43200  # 12 小时

# ---- 免责声明 ----
REVIEW_DISCLAIMER = (
    "免责声明：本页面展示的复盘报告基于历史统计特征，不代表未来行为，不构成投资建议。"
    "股市有风险，投资需谨慎。所有分析由用户自己的 AI 给出，Vibe-Research 仅提供数据呈现工具。"
)


# ===========================================================================
# 1. 数据结构
# ===========================================================================

class ZTStockSummary(BaseModel):
    """涨停股统计摘要。"""
    code: str
    name: str
    lbc: int               # 连板数
    fbt: float             # 封板时间
    seal_rate: float       # 封板率
    zbc: int               # 炸板次数


class SectorHeatItem(BaseModel):
    """板块热度排行。"""
    sector: str            # 板块名称
    zt_count: int          # 涨停股数
    total_count: int       # 总股数
    zt_rate: float         # 涨停占比
    avg_change: float      # 平均涨跌幅


class ReviewReport(BaseModel):
    """每日复盘报告（客观数据展示）。"""
    
    date: str
    sti_score: float | None          # STI 情绪分数
    sti_phase: str | None            # STI 阶段
    sti_change: float | None         # STI 动量（较昨日变化）
    
    # 涨停统计
    zt_total: int                    # 今日涨停总数
    dt_total: int                    # 今日跌停总数
    zb_total: int                    # 今日炸板总数
    advance_count: int               # 上涨家数
    decline_count: int               # 下跌家数
    
    # 板块热度 TOP N
    sector_heat: list[SectorHeatItem] = field(default_factory=list)
    
    # 涨停股明细（按连板数降序）
    zt_stocks: list[ZTStockSummary] = field(default_factory=list)
    
    # 昨日涨停股今日表现
    prev_zt_stats: dict[str, float] = field(default_factory=dict)
    
    # 竞价回顾 TOP N
    auction_top: list[dict[str, Any]] = field(default_factory=list)
    
    updated: str                     # 更新时间
    disclaimer: str = REVIEW_DISCLAIMER


# ===========================================================================
# 2. 复盘报告生成引擎
# ===========================================================================

class DailyReviewer:
    """
    每日收盘后自动生成复盘报告。
    
    MVP 阶段：规则引擎生成结构化摘要（无 AI Agent）。
    Phase 3+：接入 AI 复盘 Agent（结构化反思）。
    """

    def __init__(self):
        self._db = None

    def generate_review(self, trade_date: str) -> ReviewReport:
        """
        输入：交易日 YYYY-MM-DD
        输出：每日复盘报告
        
        步骤：
        1. 获取 STI 情绪分数
        2. 获取涨停池 + 跌停池 + 炸板池
        3. 获取市场广度数据（涨跌家数）
        4. 计算板块热度排行
        5. 获取昨日涨停股今日表现
        6. 获取竞价回顾
        7. 组装报告
        """
        date_fmt = trade_date.replace("-", "") if "-" in trade_date else trade_date
        
        # 1. 获取 STI 情绪分数
        sti_data = self._get_sti_data(trade_date)
        
        # 2. 获取涨停池 + 跌停池 + 炸板池
        zt_pool = astock.em_zt_topic_pool("getTopicZTPool", date_fmt, "fbt:asc")
        dt_pool = astock.em_zt_topic_pool("getTopicDTPool", date_fmt)
        zb_pool = astock.em_zt_topic_pool("getTopicZBPool", date_fmt, "fbt:asc")
        yzt_pool = astock.em_zt_topic_pool("getYesterdayZTPool", date_fmt, "zs:desc")
        
        # 3. 获取市场广度（涨跌家数）
        try:
            import market as _market_module
            sentiment = _market_module._sentiment(date_fmt)
            advance_count = sentiment.get("up", 0)
            decline_count = sentiment.get("down", 0)
        except Exception:
            advance_count = 0
            decline_count = 0
        
        # 4. 计算板块热度
        sector_heat = self._calculate_sector_heat(zt_pool)
        
        # 5. 涨停股统计
        zt_stocks = self._summarize_zt_stocks(zt_pool)
        
        # 6. 昨日涨停股今日表现
        prev_zt_stats = self._calculate_prev_zt_performance(yzt_pool, zt_pool)
        
        # 7. 竞价回顾（复用 auction_screener）
        auction_top = self._get_auction_review(trade_date)
        
        # 8. 组装报告
        return ReviewReport(
            date=trade_date,
            sti_score=sti_data.get("score"),
            sti_phase=sti_data.get("phase"),
            sti_change=sti_data.get("change"),
            zt_total=len(zt_pool),
            dt_total=len(dt_pool),
            zb_total=len(zb_pool),
            advance_count=advance_count,
            decline_count=decline_count,
            sector_heat=sector_heat,
            zt_stocks=zt_stocks,
            prev_zt_stats=prev_zt_stats,
            auction_top=auction_top,
            updated=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        )
    
    def _get_sti_data(self, trade_date: str) -> dict[str, Any]:
        """获取 STI 情绪数据。"""
        try:
            from backend.limitup_sti import STIEngine
            engine = STIEngine()
            result = engine.get_latest(trade_date)
            if result and result.source_ok:
                # 获取昨日 STI 计算动量
                yesterday = (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
                try:
                    prev_result = engine.get_latest(yesterday)
                    change = (result.score - prev_result.score) if prev_result and prev_result.source_ok and result.score is not None else None
                except Exception:
                    change = None
                return {
                    "score": result.score,
                    "phase": result.phase.value if result.phase else None,
                    "change": round(change, 2) if change is not None else None,
                }
        except Exception:
            pass
        return {"score": None, "phase": None, "change": None}
    
    def _calculate_sector_heat(self, zt_pool: list[dict]) -> list[SectorHeatItem]:
        """
        计算板块热度排行。
        
        按行业板块（hybk）分组统计涨停股数，返回 TOP 10。
        """
        sector_stats: dict[str, dict] = {}
        
        for item in zt_pool:
            sector = item.get("hybk", "未知板块") or "未知板块"
            if sector not in sector_stats:
                sector_stats[sector] = {"zt_count": 0, "total_count": 0, "sum_change": 0.0}
            sector_stats[sector]["zt_count"] += 1
        
        # 获取全市场数据计算总股数和平均涨跌幅
        # MVP 简化：仅基于涨停池数据计算板块热度
        items = []
        for sector, stats in sector_stats.items():
            items.append(SectorHeatItem(
                sector=sector,
                zt_count=stats["zt_count"],
                total_count=stats["zt_count"],  # MVP 简化
                zt_rate=100.0,  # MVP 简化
                avg_change=0.0,  # MVP 简化
            ))
        
        # 按涨停数降序
        items.sort(key=lambda x: x.zt_count, reverse=True)
        return items[:10]
    
    def _summarize_zt_stocks(self, zt_pool: list[dict]) -> list[ZTStockSummary]:
        """涨停股明细摘要（按连板数降序）。"""
        stocks = []
        for item in zt_pool[:REVIEW_MAX_ZT_STOCKS]:
            code = str(item.get("c", ""))
            if not code.isdigit() or len(code) != 6:
                continue
            
            lbc = astock._numf(item.get("lbc", 0)) or 0
            fbt = astock._numf(item.get("fbt", 0)) or 0
            zbc = astock._numf(item.get("zbc", 0)) or 0
            seal_rate = self._fbt_to_seal_rate(fbt)
            
            stocks.append(ZTStockSummary(
                code=code,
                name=item.get("n", ""),
                lbc=int(lbc),
                fbt=fbt,
                seal_rate=round(seal_rate, 2),
                zbc=int(zbc),
            ))
        
        # 按连板数降序
        stocks.sort(key=lambda s: s.lbc, reverse=True)
        return stocks
    
    def _fbt_to_seal_rate(self, fbt: float) -> float:
        """封板时间 → 封板率（0-100）。"""
        if fbt <= 92500:
            return 100.0
        elif fbt >= 145000:
            return 0.0
        else:
            return max(0.0, min(100.0, (1 - (fbt - 92500) / (145000 - 92500)) * 100))
    
    def _calculate_prev_zt_performance(self, yzt_pool: list[dict], zt_pool: list[dict]) -> dict[str, float]:
        """
        昨日涨停股今日表现。
        
        MVP 使用 zt_count / yzt_count * 100 作为代理指标。
        Phase 3+ 升级为真实涨跌幅计算。
        """
        yzt_count = len(yzt_pool)
        zt_count = len(zt_pool)
        
        if yzt_count == 0:
            return {"prev_zt_count": 0, "retention_rate": 0.0, "proxy_indicator": 100.0}
        
        # 计算昨日涨停股中今日仍在涨停池的数量（Retention Rate）
        yzt_codes = {str(item.get("c", "")) for item in yzt_pool}
        retained = sum(1 for item in zt_pool if str(item.get("c", "")) in yzt_codes)
        retention_rate = (retained / yzt_count) * 100 if yzt_count > 0 else 0.0
        
        return {
            "prev_zt_count": yzt_count,
            "retention_rate": round(retention_rate, 2),
            "proxy_indicator": round((zt_count / yzt_count) * 100, 2),
        }
    
    def _get_auction_review(self, trade_date: str) -> list[dict[str, Any]]:
        """获取竞价回顾 TOP N。"""
        try:
            import auction_screener as asc
            screener = asc.get_screener()
            result = screener.analyze(trade_date)
            return [c.model_dump() for c in result.candidates[:REVIEW_AUCTION_TOP_N]]
        except Exception:
            return []
    
    def precompute_daily(self, date: str) -> ReviewReport:
        """每日预计算入口 — 由 app.py 15:35 调度器触发。"""
        result = self.generate_review(date)
        
        # 写入缓存
        cache_key = f"daily_review_{date}"
        _CACHE[cache_key] = (time.time(), result)
        
        return result
    
    def backfill(self, start_date: str, end_date: str | None = None) -> list[ReviewReport]:
        """
        历史回填 — 分批执行，节流 time.sleep(0.5)。
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
                print(f"[{date_str}] 复盘报告生成失败: {e}")
            
            current_dt += timedelta(days=1)
            time.sleep(0.5)  # 节流
        
        return results


# ===========================================================================
# 3. 全局实例
# ===========================================================================

_reviewer_instance: DailyReviewer | None = None


def get_reviewer() -> DailyReviewer:
    """获取全局 DailyReviewer 实例（单例）。"""
    global _reviewer_instance
    if _reviewer_instance is None:
        _reviewer_instance = DailyReviewer()
    return _reviewer_instance
