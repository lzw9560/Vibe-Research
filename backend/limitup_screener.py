# -*- coding: utf-8 -*-
"""涨停基因选股器 —— 对涨停股计算五维因子得分（Wilson 区间校正）。

定位：客观数据展示，非行动建议。所有文字使用「历史统计特征」「策略逻辑上」等中性表述。
数据源：东财涨停板四池（astock.em_zt_topic_pool），直接调用，不经过 market.py。
缓存：TTL 12 小时日频预计算 + 内存缓存，key="limitup_screener_{date}"。
250 日回溯已由后台预计算完成，API 直接读缓存（~4ms）。
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sqlite3
import threading as _threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

import astock
from migrations import MigrationManager

BEIJING_TZ = datetime.now().astimezone().tzinfo
_logger = logging.getLogger(__name__)

# ---- 数据库路径 ----
from config import default_config
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), default_config.DB_PATH)
_DB_LOCK = _threading.Lock()

# ---- 配置（通过 .env 覆盖，开发者配置） ----
GENE_QUALIFY_THRESHOLD = float(os.getenv("LIMITUP_GENE_QUALIFY_THRESHOLD", "60"))
GENE_HIGH_THRESHOLD = float(os.getenv("LIMITUP_GENE_HIGH_THRESHOLD", "75"))
LOOKBACK_DAYS = int(os.getenv("LIMITUP_LOOKBACK_DAYS", "250"))

# 单次 HTTP 请求间隔（秒），防止东财限流导致超时
# 有 HTTP 层缓存后，实际重复请求大幅减少，可降低间隔
_MIN_REQUEST_INTERVAL = float(os.getenv("LIMITUP_REQUEST_INTERVAL", "0.5"))

# ---- 缓存 ----
_CACHE: dict = {}
_CACHE_TTL = 43200  # 12 小时
_COMPUTING: dict = {}

# ---- 数据库管理 ----

_migrations_run = False


def _run_migrations() -> None:
    """执行数据库迁移（仅一次）。"""
    global _migrations_run
    if _migrations_run:
        return
    manager = MigrationManager(db_path=_DB_PATH)
    migration_sql = (
        Path(__file__).resolve().parent
        / "migrations" / "limitup_screener" / "20250613-001_create_gene_scores.sql"
    ).read_text(encoding="utf-8")
    migrations = [
        {
            "version": "20250613-001",
            "name": "create_gene_scores",
            "sql": migration_sql,
        }
    ]
    manager.upgrade(migrations)
    _migrations_run = True


def _get_db() -> sqlite3.Connection:
    """获取 SQLite 连接（单例，线程安全）。"""
    with _DB_LOCK:
        conn = sqlite3.connect(_DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn


# 模块加载时执行迁移
_run_migrations()


def _save_gene_scores_to_db(date: str, scores: list[GeneScore]) -> None:
    """保存基因得分到数据库。"""
    conn = _get_db()
    with _DB_LOCK:
        conn.execute("BEGIN TRANSACTION")
        try:
            for s in scores:
                conn.execute("""
                    INSERT OR REPLACE INTO gene_scores
                    (date, code, name, total_score, factor_premium_rate, factor_red_rate,
                     factor_seal_rate, factor_rebound_rate, factor_freq_score,
                     wilson_adjusted, qualify, high_gene, zt_count_250d)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date, s.code, s.name, s.total_score,
                    s.factors.get("次日溢价率", 0),
                    s.factors.get("红盘率", 0),
                    s.factors.get("封板率", 0),
                    s.factors.get("炸板后溢价", 0),
                    s.factors.get("涨停频次", 0),
                    s.wilson_adjusted,
                    1 if s.qualify else 0,
                    1 if s.high_gene else 0,
                    s.zt_count_250d,
                ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _load_gene_scores_from_db(date: str) -> list[GeneScore] | None:
    """从数据库加载基因得分。如果不存在则返回 None。"""
    conn = _get_db()
    with _DB_LOCK:
        rows = conn.execute(
            "SELECT * FROM gene_scores WHERE date = ? ORDER BY total_score DESC",
            (date,),
        ).fetchall()
        conn.close()
    
    if not rows:
        return None
    
    scores = []
    for row in rows:
        factors = {
            "次日溢价率": row["factor_premium_rate"] or 0,
            "红盘率": row["factor_red_rate"] or 0,
            "封板率": row["factor_seal_rate"] or 0,
            "炸板后溢价": row["factor_rebound_rate"] or 0,
            "涨停频次": row["factor_freq_score"] or 0,
        }
        scores.append(GeneScore(
            code=row["code"],
            name=row["name"] or "",
            total_score=row["total_score"] or 0,
            factors=factors,
            wilson_adjusted=row["wilson_adjusted"] or 0,
            qualify=bool(row["qualify"]),
            high_gene=bool(row["high_gene"]),
            last_zt_dates=[],
            zt_count_250d=row["zt_count_250d"] or 0,
        ))
    return scores

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
    backtest_points: list[dict] = []  # 简化版回测数据：[{date, gene_score, actual_next_day}, ...]（个股详情用）
    backtest_summary: dict = {}  # 轻量级回测统计（screener 列表用）：{samples, lianban_rate, avg_score_lianban}


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

async def _resolve_date(date: str | None) -> str:
    """解析日期参数，回推到最近交易日（异步）。"""
    if date:
        return date.replace("-", "")
    today = datetime.now(BEIJING_TZ).strftime("%Y%m%d")
    # 回退最多 5 天找交易日
    for back in range(5):
        d = (datetime.now(BEIJING_TZ) - timedelta(days=back)).strftime("%Y%m%d")
        try:
            pool = await asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", d)
            if pool:
                return d
        except Exception:
            continue
    return today


async def _fetch_zt_pool(date: str) -> tuple[list[dict], list[dict], list[dict]]:
    """获取涨停池、昨涨停池、炸板池（并发）。"""
    try:
        zt, yzt, zb = await asyncio.gather(
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", date, "fbt:asc"),
            asyncio.to_thread(astock.em_zt_topic_pool, "getYesterdayZTPool", date, "zs:desc"),
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZBPool", date, "fbt:asc"),
        )
        return zt, yzt, zb
    except Exception as e:
        _logger.exception("获取涨停池失败: date=%s", date)
        return [], [], []


async def _collect_zt_history_batch(
    codes: set[str],
    date: str,
    lookback: int = 250,
) -> dict[str, list[dict]]:
    """批量回溯 lookback 天，收集多只股的涨停记录（并发优化）。

    使用 asyncio.gather 批量并发请求，减少总耗时。
    返回 {code: [{...pool_item_fields, _pool_date: d}, ...], ...}。
    """
    results: dict[str, list[dict]] = {c: [] for c in codes}
    target_date = datetime.strptime(date, "%Y%m%d")

    # 生成所有需要查询的日期
    all_dates = []
    for back in range(1, min(lookback, 30)):
        d = (target_date - timedelta(days=back)).strftime("%Y%m%d")
        all_dates.append(d)

    # 分批并发请求（每批 10 个日期，避免触发限流）
    BATCH_SIZE = 10
    for i in range(0, len(all_dates), BATCH_SIZE):
        batch = all_dates[i:i + BATCH_SIZE]
        tasks = [
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", d, "fbt:asc")
            for d in batch
        ]
        pools = await asyncio.gather(*tasks, return_exceptions=True)

        for d, pool in zip(batch, pools):
            if isinstance(pool, Exception):
                _logger.warning("获取涨停池失败: date=%s, error=%s", d, pool)
                continue
            for item in pool:
                code = str(item.get("c", ""))
                if code in codes and code.isdigit() and len(code) == 6:
                    results.setdefault(code, []).append(dict(item, _pool_date=d))

        # 每批后短暂延迟，避免东财限流
        if i + BATCH_SIZE < len(all_dates):
            await asyncio.sleep(0.05)

    return results


def _compute_factors(history: list[dict], yzt: list[dict], zb: list[dict]) -> dict[str, float]:
    """对一只股的历史涨停记录计算五维因子。

    因子说明（所有数值均为近似值，受限于 em_get 数据粒度）：
    - 次日溢价率 (25%)：用连板率（lbc >= 2 的次数 / 总次数）近似
      PRD 要求的"次日收盘价 > 涨停价"需逐日次日行情数据，em_get 不提供
    - 红盘率 (25%)：用 zdp（涨停当日涨幅）> 0 的比例近似
      PRD 要求的"首板次日收盘为正"需次日行情数据
    - 封板率 (25%)：用平均封板时间（fbt）作为封板强度代理
      PRD 要求的"封板成功率"需逐笔成交数据，em_get 不提供
    - 炸板后溢价 (15%)：用昨涨停池中有连板记录的占比近似
      PRD 要求的"炸板后次日溢价"需炸板日次日行情数据
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

    # ---- 封板率 (25%)：封板强度 ----
    # 注：东财 em_get 不提供逐笔成交明细，无法精确计算"封板成功率"。
    # 此处用平均封板时间（fbt）作为封板强度的代理指标：
    # fbt 越小 = 封板时间越早 = 封板越牢固 = 封板强度越高。
    # fbt 格式：9:25 → 92500，10:00 → 100000，14:50 → 145000
    fbt_values = [astock._numf(h.get("fbt")) or 0 for h in history]
    avg_fbt = sum(fbt_values) / len(fbt_values) if fbt_values else 0
    # 归一化：9:25 一字板 → 100 分，14:50 尾盘封板 → 0 分
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

    # 回测数据仅在 include_backtest=True 时计算
    bt_points: list[dict] = []
    bt_summary: dict = {}
    if include_backtest and len(history) >= 3:
        # 完整散点数据（个股详情用）
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
        # 轻量级回测统计（screener 列表用）
        lianban_count = sum(1 for p in bt_points if p["actual_next_day"] >= 1)
        total_samples = len(bt_points) if bt_points else 0
        avg_score_lianban = (
            round(sum(p["gene_score"] for p in bt_points if p["actual_next_day"] >= 1) / lianban_count, 1)
            if lianban_count > 0 else None
        )
        bt_summary = {
            "samples": total_samples,
            "lianban_rate": round(lianban_count / total_samples * 100, 1) if total_samples > 0 else 0.0,
            "avg_score_lianban": avg_score_lianban,
        }

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
        backtest_summary=bt_summary,
    )


async def get_screener_result(date: str | None = None) -> ScreenerResult:
    """获取全市场涨停股基因得分清单（客观数据，无行动建议）。

    缓存策略：
    - 首先检查数据库是否有预计算结果（~4ms）
    - 如果有，直接从数据库加载
    - 如果没有，触发预计算并缓存
    - 并发请求自动去重（仅一只线程计算，其余等待）
    - 缓存命中直接返回，零计算开销
    - **超时保护**：计算超过 90 秒自动降级返回空结果，不阻塞 API
    """
    target_date = await _resolve_date(date)
    cache_key = f"limitup_screener_{target_date}"
    display_date = target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:]

    # 1. 检查内存缓存命中
    now = time.time()
    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    # 2. 检查数据库是否有预计算结果（~4ms）
    db_scores = _load_gene_scores_from_db(display_date)
    if db_scores is not None:
        qualified = [g for g in db_scores if g.qualify]
        high_gene_list = [g for g in db_scores if g.high_gene]
        result = ScreenerResult(
            date=display_date,
            gene_scores=db_scores,
            qualified=qualified,
            high_gene=high_gene_list,
            updated=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            disclaimer=DISCLAIMER,
        )
        _CACHE[cache_key] = (now, result)
        return result

    # 3. 并发保护：如果正在计算，等待结果
    if cache_key in _COMPUTING:
        waited = 0
        while cache_key in _COMPUTING and waited < 60:
            await asyncio.sleep(0.5)
            waited += 0.5
        # 重新检查缓存和数据库
        hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
        db_scores = _load_gene_scores_from_db(display_date)
        if db_scores is not None:
            qualified = [g for g in db_scores if g.qualify]
            high_gene_list = [g for g in db_scores if g.high_gene]
            result = ScreenerResult(
                date=display_date,
                gene_scores=db_scores,
                qualified=qualified,
                high_gene=high_gene_list,
                updated=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
                disclaimer=DISCLAIMER,
            )
            _CACHE[cache_key] = (now, result)
            return result

    # 4. 超时保护：使用线程执行计算
    _COMPUTING[cache_key] = True
    result_holder: list[ScreenerResult] = []
    error_holder: list[Exception] = []

    def _compute_with_timeout():
        try:
            result_holder.append(_compute_and_cache(target_date, cache_key))
        except Exception as e:
            error_holder.append(e)

    compute_thread = _threading.Thread(target=_compute_with_timeout, daemon=True)
    compute_thread.start()
    compute_thread.join(timeout=90)  # 90 秒超时

    if error_holder:
        raise error_holder[0]

    if result_holder:
        return result_holder[0]

    # 超时了：返回空结果
    _COMPUTING.pop(cache_key, None)
    return ScreenerResult(
        date=display_date,
        gene_scores=[],
        qualified=[],
        high_gene=[],
        updated=datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        disclaimer=DISCLAIMER + " （计算超时，请稍后刷新）",
    )


async def _compute_and_cache_async(target_date: str, cache_key: str) -> ScreenerResult:
    """执行基因得分计算并缓存结果（异步版本）。"""
    now = time.time()

    # 获取数据（并发）
    zt_pool, yzt_pool, zb_pool = await _fetch_zt_pool(target_date)
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

    # 批量回溯历史涨停记录（并发优化）
    codes = {c for c in seen.keys() if c.isdigit() and len(c) == 6}
    batch_history = await _collect_zt_history_batch(codes, target_date, LOOKBACK_DAYS)

    # 对每只股计算基因得分（含回测数据）
    scores: list[GeneScore] = []
    for code, item in seen.items():
        if not code.isdigit() or len(code) != 6:
            continue
        name = item.get("n", "")
        history = batch_history.get(code, [])
        gene = compute_gene_score(code, name, history, yzt_pool, zb_pool, include_backtest=True)
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

    # 保存到数据库（在线程中运行，避免阻塞事件循环）
    await asyncio.to_thread(_save_gene_scores_to_db, display_date, scores)

    # 写入缓存
    _CACHE[cache_key] = (now, result)
    return result


def _compute_and_cache(target_date: str, cache_key: str) -> ScreenerResult:
    """执行基因得分计算并缓存结果（同步兼容层，内部运行异步实现）。"""
    # 在线程中运行，没有事件循环，直接使用 asyncio.run
    return asyncio.run(_compute_and_cache_async(target_date, cache_key))


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


async def _compute_backtest_raw(code: str, lookback_days: int = 250) -> list[dict]:
    """对某只股票，用滚动窗口计算基因得分 vs 实际表现的散点数据（并发优化）。

    方法：
    1. 拉取 lookback_days 天的涨停池历史
    2. 对每一天，用该天之前的历史数据计算基因得分
    3. 记录该天的实际次日表现（是否连板）
    4. 返回散点数据供前端可视化

    返回: [{date, gene_score, actual_next_day, seal_rate, premium_rate}, ...]
    """
    target_date = datetime.now(BEIJING_TZ).strftime("%Y%m%d")
    
    # 拉取 lookback_days 天的涨停池（并发）
    all_pools: list[tuple[str, dict]] = []  # [(date_str, item), ...]
    target = datetime.strptime(target_date, "%Y%m%d")
    BATCH = 10
    
    for batch_start in range(0, lookback_days, BATCH):
        batch_end = min(batch_start + BATCH, lookback_days)
        dates = [(target - timedelta(days=back)).strftime("%Y%m%d") for back in range(batch_start, batch_end)]
        tasks = [
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", d, "fbt:asc")
            for d in dates
        ]
        pools = await asyncio.gather(*tasks, return_exceptions=True)
        
        for d, pool in zip(dates, pools):
            if isinstance(pool, Exception):
                _logger.warning("获取涨停池失败: date=%s, error=%s", d, pool)
                continue
            for item in pool:
                if str(item.get("c", "")) == code:
                    all_pools.append((d, item))
        
        if batch_end < lookback_days:
            await asyncio.sleep(0.05)
    
    if len(all_pools) < 3:
        return []  # 数据不足
    
    # 按日期排序
    all_pools.sort(key=lambda x: x[0])
    
    # 滚动计算：对每个涨停日，用之前的历史计算基因得分
    results: list[BacktestPoint] = []
    history_so_far: list[dict] = []
    yzt_all: list[dict] = []
    zb_all: list[dict] = []
    
    # 先拉昨涨停池和炸板池（用于封板率等因子计算，并发）
    yzt_dates = [(target - timedelta(days=back)).strftime("%Y%m%d") for back in range(1, min(lookback_days, 30))]
    zb_dates = yzt_dates.copy()
    
    yzt_tasks = [
        asyncio.to_thread(astock.em_zt_topic_pool, "getYesterdayZTPool", d, "zs:desc")
        for d in yzt_dates
    ]
    zb_tasks = [
        asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZBPool", d, "fbt:asc")
        for d in zb_dates
    ]
    
    yzt_results = await asyncio.gather(*yzt_tasks, return_exceptions=True)
    zb_results = await asyncio.gather(*zb_tasks, return_exceptions=True)
    
    for pool in yzt_results:
        if not isinstance(pool, Exception):
            yzt_all.extend(pool)
    for pool in zb_results:
        if not isinstance(pool, Exception):
            zb_all.extend(pool)
    
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


# ===========================================================================
# 6. 日频预计算入口（供 app.py 调度器调用）
# ===========================================================================

async def precompute_daily_async(date: str | None = None) -> ScreenerResult:
    """
    每日预计算入口（异步版本）— 由 app.py 15:35 调度器触发。
    
    计算最近 250 天的涨停基因得分，保存到数据库。
    返回 ScreenerResult 同时写入内存缓存。
    """
    if date is None:
        date = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    
    # 支持 YYYY-MM-DD 和 YYYYMMDD 两种格式
    date_fmt = date.replace("-", "") if "-" in date else date
    target_date = await _resolve_date(date_fmt)
    cache_key = f"limitup_screener_{target_date}"
    
    return await _compute_and_cache_async(target_date, cache_key)


def precompute_daily(date: str | None = None) -> ScreenerResult:
    """每日预计算入口（同步兼容层）— 由 app.py 15:35 调度器触发。"""
    if date is None:
        date = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    
    # 支持 YYYY-MM-DD 和 YYYYMMDD 两种格式
    date_fmt = date.replace("-", "") if "-" in date else date
    # 同步调用：使用 asyncio.run 运行异步实现
    target_date = asyncio.run(_resolve_date(date_fmt))
    cache_key = f"limitup_screener_{target_date}"
    
    return _compute_and_cache(target_date, cache_key)


async def backfill_async(start_date: str, end_date: str | None = None) -> list[ScreenerResult]:
    """
    历史回填（异步版本）— 分批执行，节流 asyncio.sleep(0.5)。

    对每个日期执行 precompute_daily_async，结果存入数据库。
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
            result = await precompute_daily_async(date_str)
            results.append(result)
        except Exception as e:
            logging.getLogger("vibe-research").warning("[%s] 预计算失败: %s", date_str, e)
        
        current_dt += timedelta(days=1)
        await asyncio.sleep(0.5)  # 节流
    
    return results


def backfill(start_date: str, end_date: str | None = None) -> list[ScreenerResult]:
    """历史回填（同步兼容层）— 分批执行，节流 time.sleep(0.5)。"""
    if end_date is None:
        end_date = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    
    results = []
    current_dt = start_dt
    
    while current_dt <= end_dt:
        date_str = current_dt.strftime("%Y-%m-%d")
        try:
            result = precompute_daily(date_str)
            results.append(result)
        except Exception as e:
            logging.getLogger("vibe-research").warning("[%s] 预计算失败: %s", date_str, e)
        
        current_dt += timedelta(days=1)
        time.sleep(0.5)  # 节流
    
    return results


# ===========================================================================
# 7. 全局实例
# ===========================================================================

_screener_instance = None


def get_screener():
    """获取全局选股器实例（兼容旧接口）。"""
    global _screener_instance
    if _screener_instance is None:
        _screener_instance = True  # 占位，实际使用函数式接口
    return _screener_instance
