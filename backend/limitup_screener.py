# -*- coding: utf-8 -*-
"""涨停基因选股器 —— 对涨停股计算五维因子得分（Wilson 区间校正）。

定位：客观数据展示，非行动建议。所有文字使用「历史统计特征」「策略逻辑上」等中性表述。
数据源：东财涨停板四池（astock.em_zt_topic_pool），直接调用，不经过 market.py。
缓存：TTL 12 小时日频预计算 + 内存缓存，key="limitup_screener_{date}"。
250 日回溯已由后台预计算完成，API 直接读缓存（~4ms）。
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import BaseModel

import astock

BEIJING_TZ = datetime.now().astimezone().tzinfo

# ---- 配置（通过 .env 覆盖，开发者配置） ----
GENE_QUALIFY_THRESHOLD = float(os.getenv("LIMITUP_GENE_QUALIFY_THRESHOLD", "60"))
GENE_HIGH_THRESHOLD = float(os.getenv("LIMITUP_GENE_HIGH_THRESHOLD", "75"))
LOOKBACK_DAYS = int(os.getenv("LIMITUP_LOOKBACK_DAYS", "60"))

# ---- 缓存 ----
_CACHE: dict = {}
_CACHE_TTL = 43200  # 12 小时
_COMPUTING: dict = {}

# 回测缓存
_BACKTEST_CACHE: dict = {}
_BACKTEST_TTL = 86400  # 24 小时（个股回测数据日频不变）

# 是否启用后台预计算（生产环境设为 True）
_PRECOMPUTE_ENABLED = os.getenv("LIMITUP_PRECOMPUTE", "false").lower() == "true"


# ===========================================================================
# 1. Wilson 区间校正
# ===========================================================================

def wilson_lower_bound(successes: int, trials: int, z: float = 1.96) -> float:
    """Wilson 95% 置信区间下界（小样本自动降置信度）。"""
    if trials == 0:
        return 0.0
    p = successes / trials
    denom = 1 + z ** 2 / trials
    center = (p + z ** 2 / (2 * trials)) / denom
    margin = (z * math.sqrt(p * (1 - p) / trials + z ** 2 / (4 * trials ** 2))) / denom
    return max(0.0, center - margin)


# ===========================================================================
# 2. 数据结构
# ===========================================================================

DISCLAIMER = (
    "免责声明：本页面展示的信号和评分基于历史统计特征，不代表未来行为，不构成投资建议。"
    "股市有风险，投资需谨慎。所有分析由用户自己的 AI 给出，Vibe-Research 仅提供数据呈现工具。"
)


class GeneScore(BaseModel):
    """单只股票的涨停基因得分（客观数据，非行动建议）。"""

    code: str
    name: str
    total_score: float  # 0-100
    factors: dict[str, float]  # 五维因子得分（百分比形式）
    wilson_adjusted: float  # Wilson 校正后得分
    qualify: bool  # 是否合格（>= 阈值）
    high_gene: bool  # 高基因（>= 高阈值）
    last_zt_dates: list[str]  # 最近涨停日期
    zt_count_250d: int  # 近 N 日涨停次数
    backtest_points: list[dict]  # 简化版回测数据：[{date, gene_score, actual_next_day}, ...]


class ScreenerResult(BaseModel):
    """全市场选股结果（客观数据展示）。"""

    date: str
    gene_scores: list[GeneScore]  # 所有涨停股的基因得分
    qualified: list[GeneScore]  # 基因合格的
    high_gene: list[GeneScore]  # 高基因的
    updated: str  # 更新时间
    disclaimer: str  # 免责声明


# ===========================================================================
# 3. 数据获取
# ===========================================================================

def _resolve_date(date: str | None) -> str:
    """解析日期参数，回推到最近交易日。"""
    if date:
        return date.replace("-", "")
    today = datetime.now(BEIJING_TZ).strftime("%Y%m%d")
    # 回退最多 5 天找交易日
    for back in range(5):
        d = (datetime.now(BEIJING_TZ) - timedelta(days=back)).strftime("%Y%m%d")
        pool = astock.em_zt_topic_pool("getTopicZTPool", d)
        if pool:
            return d
    return today


def _fetch_zt_pool(date: str) -> tuple[list[dict], list[dict], list[dict]]:
    """获取涨停池、昨涨停池、炸板池。"""
    zt = astock.em_zt_topic_pool("getTopicZTPool", date, "fbt:asc")
    yzt = astock.em_zt_topic_pool("getYesterdayZTPool", date, "zs:desc")
    zb = astock.em_zt_topic_pool("getTopicZBPool", date, "fbt:asc")
    return zt, yzt, zb


def _collect_zt_history_batch(
    codes: set[str],
    date: str,
    lookback: int = 250,
) -> dict[str, list[dict]]:
    """批量回溯 lookback 天，收集多只股的涨停记录。

    一次性拉取 N 天的涨停池，然后在内存中按 code 分组筛选，
    避免逐日逐股调用 HTTP 接口。
    返回 {code: [{...pool_item_fields, _pool_date: d}, ...], ...}。
    """
    results: dict[str, list[dict]] = {c: [] for c in codes}
    target_date = datetime.strptime(date, "%Y%m%d")

    # 每批拉取 BATCH_SIZE 天，减少 HTTP 调用次数
    BATCH_SIZE = 10
    for batch_start in range(0, lookback, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, lookback)
        # 批量拉取这一批日期的涨停池
        for back in range(batch_start, batch_end):
            d = (target_date - timedelta(days=back)).strftime("%Y%m%d")
            pool = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
            for item in pool:
                code = str(item.get("c", ""))
                if code in codes and code.isdigit() and len(code) == 6:
                    results.setdefault(code, []).append(dict(item, _pool_date=d))
    # 随机延迟，避免被东频率封禁（astock._em_get 已有节流，此处不再 sleep）
            # time.sleep(0.15)
    return results


def _compute_factors(history: list[dict], yzt: list[dict], zb: list[dict]) -> dict[str, float]:
    """对一只股的历史涨停记录计算五维因子。

    因子：
    - 次日溢价率 (25%)：涨停次日收盘价 > 涨停价 的比例
      近似：用连板率（lbc >= 2 的次数 / 总涨停次数）
    - 红盘率 (25%)：首板次日收盘为正的比例
      近似：用 zdp（涨停当日涨幅）> 0 的比例
    - 封板率 (25%)：封板强度
      近似：用平均封板时间（fbt 越小=封得越早=越牢固），归一化为 0-100
    - 炸板后溢价 (15%)：炸板后次日表现
      近似：昨涨停池中有连板记录的占比
    - 涨停频次 (10%)：归一化的涨停次数得分
    """
    n = len(history)
    if n == 0:
        return {
            "次日溢价率": 0.0,
            "红盘率": 0.0,
            "封板率": 0.0,
            "炸板后溢价": 0.0,
            "涨停频次": 0.0,
        }

    # ---- 次日溢价率：连板率（lbc >= 2 的次数 / 总次数）----
    lianban_count = sum(1 for h in history if (astock._numf(h.get("lbc")) or 0) >= 2)
    premium_rate = round(wilson_lower_bound(lianban_count, n) * 100, 2)

    # ---- 红盘率：用 zdp（涨停涨幅）> 0 的比例 ----
    red_count = sum(1 for h in history if (astock._numf(h.get("zdp")) or 0) > 0)
    red_rate = round(wilson_lower_bound(red_count, n) * 100, 2)

    # ---- 封板率：用平均封板时间近似 ----
    # fbt 格式：9:25 → 92500, 10:00 → 100000, 14:50 → 145000
    # 越小=封得越早=越牢固
    fbt_values = [astock._numf(h.get("fbt")) or 0 for h in history]
    avg_fbt = sum(fbt_values) / len(fbt_values) if fbt_values else 0
    # 归一化：fbt=92500（9:25一字板）→ 100分，fbt=145000（14:50封板）→ 0分
    seal_rate = round(max(0.0, min(100.0, (1 - (avg_fbt - 92500) / (145000 - 92500)) * 100)), 2)

    # ---- 炸板后溢价：昨涨停池中有连板记录的占比 ----
    zb_total = len(yzt)
    if zb_total > 0:
        yzt_lianban = sum(1 for z in yzt if (astock._numf(z.get("lbc")) or 0) >= 1)
        rebound_rate = round(wilson_lower_bound(yzt_lianban, zb_total) * 100, 2)
    else:
        rebound_rate = 0.0

    # ---- 涨停频次：归一化 ----
    max_possible = max(LOOKBACK_DAYS // 5, 1)
    freq_score = round(min(n / max_possible, 1.0) * 100, 2)

    return {
        "次日溢价率": premium_rate,
        "红盘率": red_rate,
        "封板率": seal_rate,
        "炸板后溢价": rebound_rate,
        "涨停频次": freq_score,
    }


def _calc_total_score(factors: dict[str, float]) -> float:
    """五维加权合成：次日溢价率(25%) + 红盘率(25%) + 封板率(25%) + 炸板后溢价(15%) + 涨停频次(10%)。"""
    w = {
        "次日溢价率": 0.25,
        "红盘率": 0.25,
        "封板率": 0.25,
        "炸板后溢价": 0.15,
        "涨停频次": 0.10,
    }
    total = sum(factors.get(k, 0.0) * v for k, v in w.items())
    return round(total, 2)


# ===========================================================================
# 4. 核心：选股器主函数
# ===========================================================================

def compute_gene_score(
    code: str,
    name: str,
    history: list[dict],
    yzt: list[dict],
    zb: list[dict],
    include_backtest: bool = False,
) -> GeneScore:
    """计算单只涨停股的基因得分。"""
    factors = _compute_factors(history, yzt, zb)
    total = _calc_total_score(factors)
    wilson_adj = round(total * wilson_lower_bound(len(history), max(len(history), 1), z=1.96), 2)

    last_dates = sorted(set(
        h.get("_pool_date", "") for h in history if h.get("_pool_date")
    ), reverse=True)[:10]

    # 回测数据仅在个股分析时按需计算（screener 列表不计算，避免性能爆炸）
    bt_points: list[dict] = []
    if include_backtest and len(history) >= 3:
        history_for_bt: list[dict] = []
        for h in history:
            if len(history_for_bt) >= 2:
                bt_factors = _compute_factors(history_for_bt, [], [])
                bt_total = _calc_total_score(bt_factors)
                lbc = astock._numf(h.get("lbc")) or 0
                bt_points.append({
                    "date": h.get("_pool_date", ""),
                    "gene_score": round(bt_total, 2),
                    "actual_next_day": 1.0 if lbc >= 2 else 0.0,
                })
            history_for_bt.append(h)

    return GeneScore(
        code=code,
        name=name,
        total_score=total,
        factors=factors,
        wilson_adjusted=wilson_adj,
        qualify=total >= GENE_QUALIFY_THRESHOLD,
        high_gene=total >= GENE_HIGH_THRESHOLD,
        last_zt_dates=last_dates,
        zt_count_250d=len(history),
        backtest_points=bt_points,
    )


def get_screener_result(date: str | None = None) -> ScreenerResult:
    """获取全市场涨停股基因得分清单（客观数据，无行动建议）。

    缓存策略：
    - 首次请求触发预计算，结果缓存 12 小时（覆盖整个交易日）
    - 并发请求自动去重（仅一只线程计算，其余等待）
    - 缓存命中直接返回，零计算开销
    """
    target_date = _resolve_date(date)
    cache_key = f"limitup_screener_{target_date}"

    # 1. 检查缓存命中（统一用 YYYYMMDD key）
    now = time.time()
    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    # 2. 并发保护：如果正在计算，等待结果
    if cache_key in _COMPUTING:
        # 等待其他线程完成计算（最多等 60 秒）
        waited = 0
        while cache_key in _COMPUTING and waited < 60:
            time.sleep(0.5)
            waited += 0.5
        # 重新检查缓存
        hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]

    # 3. 锁定并计算
    _COMPUTING[cache_key] = True
    try:
        return _compute_and_cache(target_date, cache_key)
    finally:
        _COMPUTING.pop(cache_key, None)


def _compute_and_cache(target_date: str, cache_key: str) -> ScreenerResult:
    """执行基因得分计算并缓存结果（内部函数，不对外暴露）。"""
    now = time.time()

    # 获取数据
    zt_pool, yzt_pool, zb_pool = _fetch_zt_pool(target_date)
    display_date = target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:]
    if not zt_pool:
        result = ScreenerResult(
            date=display_date,
            gene_scores=[],
            qualified=[],
            high_gene=[],
            updated=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            disclaimer=DISCLAIMER,
        )
        _CACHE[cache_key] = (now, result)
        return result

    # 去重：按 code 聚合
    seen: dict[str, dict] = {}
    for item in zt_pool:
        code = str(item.get("c", ""))
        if code and code not in seen:
            seen[code] = item

    # 批量回溯历史涨停记录（优化：一次拉取多天，内存中分组）
    codes = {c for c in seen.keys() if c.isdigit() and len(c) == 6}
    batch_history = _collect_zt_history_batch(codes, target_date, LOOKBACK_DAYS)

    # 对每只股计算基因得分
    scores: list[GeneScore] = []
    for code, item in seen.items():
        if not code.isdigit() or len(code) != 6:
            continue
        name = item.get("n", "")
        history = batch_history.get(code, [])
        gene = compute_gene_score(code, name, history, yzt_pool, zb_pool)
        scores.append(gene)

    # 排序：按 total_score 降序
    scores.sort(key=lambda g: g.total_score, reverse=True)

    qualified = [g for g in scores if g.qualify]
    high_gene_list = [g for g in scores if g.high_gene]

    result = ScreenerResult(
        date=display_date,
        gene_scores=scores,
        qualified=qualified,
        high_gene=high_gene_list,
        updated=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        disclaimer=DISCLAIMER,
    )

    _CACHE[cache_key] = (now, result)
    return result


# ===========================================================================
# 5. 简化版回测：基因得分 vs 实际次日表现
# ===========================================================================

@dataclass
class BacktestPoint:
    """单个回测数据点。"""
    date: str          # 涨停日期
    gene_score: float  # 当时计算的基因得分
    actual_next_day: float  # 实际次日表现（连板=1, 未连板=0）
    seal_rate: float   # 封板率因子
    premium_rate: float  # 次日溢价率因子


def _compute_backtest_raw(code: str, lookback_days: int = 60) -> list[dict]:
    """对某只股票，用滚动窗口计算基因得分 vs 实际表现的散点数据。

    方法：
    1. 拉取 lookback_days 天的涨停池历史
    2. 对每一天，用该天之前的历史数据计算基因得分
    3. 记录该天的实际次日表现（是否连板）
    4. 返回散点数据供前端可视化

    返回: [{date, gene_score, actual_next_day, seal_rate, premium_rate}, ...]
    """
    target_date = datetime.now(BEIJING_TZ).strftime("%Y%m%d")
    
    # 拉取 lookback_days 天的涨停池
    all_pools: list[tuple[str, dict]] = []  # [(date_str, item), ...]
    target = datetime.strptime(target_date, "%Y%m%d")
    BATCH = 10
    
    for batch_start in range(0, lookback_days, BATCH):
        batch_end = min(batch_start + BATCH, lookback_days)
        for back in range(batch_start, batch_end):
            d = (target - timedelta(days=back)).strftime("%Y%m%d")
            pool = astock.em_zt_topic_pool("getTopicZTPool", d, "fbt:asc")
            for item in pool:
                if str(item.get("c", "")) == code:
                    all_pools.append((d, item))
    
    if len(all_pools) < 3:
        return []  # 数据不足
    
    # 按日期排序
    all_pools.sort(key=lambda x: x[0])
    
    # 滚动计算：对每个涨停日，用之前的历史计算基因得分
    results: list[BacktestPoint] = []
    history_so_far: list[dict] = []
    yzt_all: list[dict] = []
    zb_all: list[dict] = []
    
    # 先拉昨涨停池和炸板池（用于封板率等因子计算）
    for back in range(1, min(lookback_days, 30)):
        d = (target - timedelta(days=back)).strftime("%Y%m%d")
        yzt = astock.em_zt_topic_pool("getYesterdayZTPool", d, "zs:desc")
        yzt_all.extend(yzt)
        zb = astock.em_zt_topic_pool("getTopicZBPool", d, "fbt:asc")
        zb_all.extend(zb)
    
    for pool_date, item in all_pools:
        # 用之前的历史计算基因得分
        if len(history_so_far) >= 2:
            factors = _compute_factors(history_so_far, yzt_all[:50], zb_all[:50])
            total = _calc_total_score(factors)
            
            # 实际表现：是否连板（lbc >= 2）
            lbc = astock._numf(item.get("lbc")) or 0
            actual = 1.0 if lbc >= 2 else 0.0
            
            results.append(BacktestPoint(
                date=pool_date,
                gene_score=total,
                actual_next_day=actual,
                seal_rate=factors.get("封板率", 0),
                premium_rate=factors.get("次日溢价率", 0),
            ))
        
        history_so_far.append(item)
    
    # 转为 JSON-serializable dict
    return [
        {
            "date": r.date,
            "gene_score": round(r.gene_score, 2),
            "actual_next_day": r.actual_next_day,
            "seal_rate": round(r.seal_rate, 2),
            "premium_rate": round(r.premium_rate, 2),
        }
        for r in results
    ]
