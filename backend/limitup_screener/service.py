# -*- coding: utf-8 -*-
"""limitup_screener 服务层 —— 业务逻辑、缓存、预计算。"""

from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
from datetime import datetime, timedelta

import astock

from data.mappers import zt_pool_item_from_dict
from limitup_screener.data import run_migrations, save_gene_scores, load_gene_scores
from models.market_snapshot import ZTPoolItem
from vr_paths import is_trading_day, last_trading_date_str
from limitup_screener.models import (
    GeneScore,
    ScreenerResult,
    DISCLAIMER,
    compute_gene_score,
    wilson_lower_bound,
    LOOKBACK_DAYS,
    GENE_QUALIFY_THRESHOLD,
    GENE_HIGH_THRESHOLD,
)

_BEIJING_TZ = datetime.now().astimezone().tzinfo
_logger = logging.getLogger(__name__)

# ---- 缓存 ----
_CACHE: dict = {}
_CACHE_TTL = 43200  # 12 小时
_COMPUTING: dict = {}
_RESOLVED_DATE_CACHE: dict[str, str] = {}
_RESOLVED_DATE_TTL = 3600  # 1 小时
_DATA_STALE_THRESHOLD = 3600  # 1 小时视为 stale
_DATA_EXPIRED_THRESHOLD = 86400  # 24 小时视为 expired


def _assess_freshness(age_seconds: float) -> str:
    """评估数据新鲜度。"""
    if age_seconds <= _DATA_STALE_THRESHOLD:
        return "fresh"
    if age_seconds <= _DATA_EXPIRED_THRESHOLD:
        return "stale"
    return "expired"


def _empty_screener_result(date_str: str, *, reason: str = "") -> ScreenerResult:
    """非交易日 / 降级空结果（S098 Fix A）。"""
    display_date = date_str[:4] + "-" + date_str[4:6] + "-" + date_str[6:]
    return ScreenerResult(
        date=display_date,
        gene_scores=[],
        qualified=[],
        high_gene=[],
        updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        disclaimer=DISCLAIMER + (f" （{reason}）" if reason else ""),
        data_freshness="expired",
        data_age_seconds=0.0,
    )


def _assert_not_future_date(target_date: str) -> bool:
    """S095 R1/R2：写路径未来日期守卫。

    target_date 为 YYYYMMDD 或 YYYY-MM-DD（兼容两种格式——_resolve_date 返 YYYYMMDD，
    但 precompute_daily_async 的早期未格式化参数亦可能传带 - 形式）。
    > last_trading_date_str()（最近交易日，纯本地零请求）→ 返 False（未来日期含
    周六/周日/节假日之后：周六 > 最近交易日周五，归入拒绝）。

    返 True 表示放行（target_date ≤ 最近交易日）；返 False 表示拒绝写入。
    """
    # 归一 YYYYMMDD → YYYY-MM-DD，与 last_trading_date_str() 的 ISO 形式可比
    s = str(target_date).strip()
    if "-" not in s and len(s) == 8 and s.isdigit():
        cmp = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    else:
        cmp = s
    try:
        return cmp <= last_trading_date_str()
    except Exception:
        # 日期解析异常：保守放行，交由下游 _resolve_date / is_trading_day 处理
        return True


def _cross_check_zt_history(target_date: str, zt_pool_len: int) -> bool:
    """S095 R4：交叉校验 zt_history final 快照与请求池行数。

    target_date 为 YYYYMMDD 或 YYYY-MM-DD。返回 True 表示放行写入，False 表示拒绝。

    - zt_history 存在同日 final 快照（is_final=1）且 count 与 zt_pool_len 不一致 → 拒绝（final 权威）
    - 非 final 或快照不存在 → 只告警（盘中收缩合法），放行
    - DB 查询异常 → 降级放行（不阻塞写路径，与降级风格一致）
    """
    import sqlite3
    from vr_paths import resolve_data_dir

    s = str(target_date).strip()
    if "-" not in s and len(s) == 8 and s.isdigit():
        d_iso = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    else:
        d_iso = s

    db_path = resolve_data_dir() / "zt_history.db"
    if not db_path.exists():
        # zt_history 尚未落库（全新环境 / 历史日无快照）→ 无 final 可校验，放行
        return True

    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt, MAX(is_final) AS mx FROM zt_history WHERE date = ?",
                (d_iso,),
            ).fetchone()
        finally:
            conn.close()
    except Exception as e:
        _logger.warning("[s095] 交叉校验 zt_history 查询失败 date=%s err=%s", d_iso, e)
        return True

    if row is None:
        return True
    count = row[0] or 0
    max_final = row[1]
    if count == 0:
        # 当日无快照（盘中 / 历史 DB 未覆盖）→ 只告警，放行
        return True
    if max_final == 1 and count != zt_pool_len:
        _logger.error(
            "[s095] 交叉校验拒绝写入 date=%s：zt_history final 快照行数=%d 与请求 zt_pool 行数=%d 不一致",
            d_iso, count, zt_pool_len,
        )
        return False
    if max_final != 1:
        _logger.warning(
            "[s095] 交叉校验告警 date=%s：zt_history 非 final 快照（行数=%d，pool=%d，盘中收缩合法）",
            d_iso, count, zt_pool_len,
        )
    return True


async def _resolve_date(date: str | None) -> str:
    """解析日期参数，回推到最近交易日（异步，带缓存）。"""
    if date:
        return date.replace("-", "")
    
    # 检查缓存
    now = time.time()
    cache_key = "latest_trading_day"
    cached = _RESOLVED_DATE_CACHE.get(cache_key)
    if cached and now - cached[0] < _RESOLVED_DATE_TTL:
        return cached[1]
    
    today = datetime.now(_BEIJING_TZ).strftime("%Y%m%d")
    for back in range(5):
        d = (datetime.now(_BEIJING_TZ) - timedelta(days=back)).strftime("%Y%m%d")
        try:
            pool = await asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", d)
            if pool:
                _RESOLVED_DATE_CACHE[cache_key] = (now, d)
                return d
        except Exception:
            continue
    
    _RESOLVED_DATE_CACHE[cache_key] = (now, today)
    return today


async def _fetch_zt_pool(date: str):
    """获取涨停池、昨涨停池、炸板池（并发），返回 ZTPoolItem 列表。"""
    try:
        zt, yzt, zb = await asyncio.gather(
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZTPool", date, "fbt:asc"),
            asyncio.to_thread(astock.em_zt_topic_pool, "getYesterdayZTPool", date, "zs:desc"),  # S053 R1：fbt:asc→zs:desc（fbt 对该端点返空）
            asyncio.to_thread(astock.em_zt_topic_pool, "getTopicZBPool", date, "fbt:asc"),
        )
        return (
            [zt_pool_item_from_dict(it) for it in zt],
            [zt_pool_item_from_dict(it) for it in yzt],
            [zt_pool_item_from_dict(it) for it in zb],
        )
    except Exception as e:
        _logger.exception("获取涨停池失败: date=%s", date)
        return [], [], []


def _compute_rebound_rate(zb_pool: list, zt_next_pool: list | None) -> tuple[float, list[str]]:
    """S053 R2：炸板后溢价 = T 日 zb 池次日回封率（zb ∩ T+1 zt / zb）。

    返回 (rebound_rate, missing_factors)。
    - zb 空 → (0.0, [])（无炸板何来回封，非 missing）
    - zt_next None/空 → (0.0, ["炸板后溢价"])（数据缺供，诚实标注 missing）
    - 否则 wilson 下界修正
    """
    zb_total = len(zb_pool)
    if zb_total == 0:
        return 0.0, []
    if not zt_next_pool:
        return 0.0, ["炸板后溢价"]
    zb_codes = {item.code for item in zb_pool if item.code}
    zt_next_codes = {item.code for item in zt_next_pool if item.code}
    resealed = zb_codes & zt_next_codes
    return round(wilson_lower_bound(len(resealed), zb_total) * 100, 2), []


def _fetch_zt_next_pool(target_date: str) -> list:
    """S053 R2：拉 T+1 日涨停池（用于算 zb 次日回封率）。失败返空。"""
    from datetime import datetime as _dt, timedelta as _td
    try:
        base = _dt.strptime(target_date, "%Y%m%d").date()
    except ValueError:
        return []
    # 下一日（跨周末/节假日自然跳，东财返空即 missing）
    next_d = base + _td(days=1)
    for _ in range(7):  # 最多扫 7 日找下一交易日
        d_str = next_d.strftime("%Y%m%d")
        try:
            pool = astock.em_zt_topic_pool("getTopicZTPool", d_str, "fbt:asc")
            if pool:
                return [zt_pool_item_from_dict(it) for it in pool]
        except Exception:
            pass
        next_d += _td(days=1)
    return []


async def _collect_zt_history_batch(codes: set[str], date: str, lookback: int = 252) -> dict[str, list]:
    """批量回溯 lookback 天，收集多只股的涨停记录（并发优化），返 ZTPoolItem（含 pool_date）。"""
    results: dict[str, list] = {c: [] for c in codes}
    target_date = datetime.strptime(date, "%Y%m%d")

    all_dates = []
    for back in range(1, min(lookback, 30)):
        d = (target_date - timedelta(days=back)).strftime("%Y%m%d")
        all_dates.append(d)

    BATCH_SIZE = 20
    SLEEP_BETWEEN_BATCHES = 0.02
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
                    # frozen 模型：构造 ZTPoolItem 注入 pool_date（替代旧 dict(item, _pool_date=d)）
                    results.setdefault(code, []).append(zt_pool_item_from_dict(item, pool_date=d))

        if i + BATCH_SIZE < len(all_dates):
            await asyncio.sleep(SLEEP_BETWEEN_BATCHES)

    return results


async def _compute_and_cache_async(target_date: str, cache_key: str) -> ScreenerResult:
    """执行基因得分计算并缓存结果（异步版本）。"""
    # S095 R1/R2：未来日期硬闸门——target_date > 最近交易日 → 拒写返空（不查东财）
    if not _assert_not_future_date(target_date):
        _logger.warning(
            "[s095] 未来日期拒绝写入 target_date=%s > last_trading_date=%s",
            target_date, last_trading_date_str(),
        )
        return _empty_screener_result(target_date, reason="未来日期拒绝写入")

    now = time.time()

    zt_pool, yzt_pool, zb_pool = await _fetch_zt_pool(target_date)
    display_date = target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:]
    if not zt_pool:
        result = ScreenerResult(
            date=display_date,
            gene_scores=[],
            qualified=[],
            high_gene=[],
            updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            disclaimer=DISCLAIMER,
            data_freshness="fresh",
            data_age_seconds=0.0,
        )
        _CACHE[cache_key] = (now, result)
        return result

    # S095 R4：交叉校验钩子——zt_history final 快照与请求池行数不一致 → 拒绝写入
    if not _cross_check_zt_history(target_date, len(zt_pool)):
        return _empty_screener_result(target_date, reason="交叉校验不一致拒绝写入")

    # S053 R2：拉 T+1 日 zt 池算 zb 次日回封率（路径 C：service 层预算回填因子）
    zt_next_pool = await asyncio.to_thread(_fetch_zt_next_pool, target_date)
    rebound_rate, rebound_missing = _compute_rebound_rate(zb_pool, zt_next_pool)
    if rebound_missing:
        _logger.info("[screener] %s 炸板后溢价 missing（zt_next 拉取失败/空）", display_date)
    else:
        _logger.info("[screener] %s 炸板后溢价=%.2f（zb=%d zt_next=%d）",
                     display_date, rebound_rate, len(zb_pool), len(zt_next_pool or []))

    seen: dict[str, ZTPoolItem] = {}
    for item in zt_pool:
        code = item.code
        if code and code not in seen:
            seen[code] = item

    codes = {c for c in seen.keys() if c.isdigit() and len(c) == 6}
    batch_history = await _collect_zt_history_batch(codes, target_date, LOOKBACK_DAYS)

    scores = []
    for code, item in seen.items():
        if not code.isdigit() or len(code) != 6:
            continue
        name = item.name or ""
        history = batch_history.get(code, [])
        scores.append((code, name, history, yzt_pool, zb_pool, item))

    # 并行计算基因得分
    async def _compute_one(args: tuple) -> GeneScore:
        c, n, h, y, z, item = args
        return compute_gene_score(c, n, h, y, z, include_backtest=True, pool_item=item, date=target_date)

    gene_tasks = [_compute_one(s) for s in scores]
    gene_results = await asyncio.gather(*gene_tasks, return_exceptions=True)
    gene_scores = [g for g in gene_results if not isinstance(g, Exception)]

    # S053 R2 路径 C：service 层回填炸板后溢价因子（重定义 = zb 次日回封率）
    # compute_factors 算的旧值（yzt 公式错）在这里覆盖；缺数据时标 missing 不臆造
    from limitup_screener.models import calc_total_score
    for g in gene_scores:
        g.factors["炸板后溢价"] = rebound_rate
        if rebound_missing:
            if g.missing_factors is None:
                g.missing_factors = []
            if "炸板后溢价" not in g.missing_factors:
                g.missing_factors.append("炸板后溢价")
        # 权重为 0%（S047），重算 total_score 不受因子值影响，但保持一致性
        g.total_score = calc_total_score(g.factors)

    gene_scores.sort(key=lambda g: g.total_score, reverse=True)

    qualified = [g for g in gene_scores if g.qualify]
    high_gene_list = [g for g in gene_scores if g.high_gene]

    result = ScreenerResult(
        date=display_date,
        gene_scores=gene_scores,
        qualified=qualified,
        high_gene=high_gene_list,
        updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
        disclaimer=DISCLAIMER,
        data_freshness="fresh",
        data_age_seconds=0.0,
    )

    await asyncio.to_thread(save_gene_scores, display_date, gene_scores)
    _CACHE[cache_key] = (now, result)
    return result


def _compute_and_cache(target_date: str, cache_key: str):
    """执行基因得分计算并缓存结果（同步兼容层）。"""
    return asyncio.run(_compute_and_cache_async(target_date, cache_key))


async def get_screener_result(date: str | None = None) -> ScreenerResult:
    """获取全市场涨停股基因得分清单（客观数据，无行动建议）。"""
    target_date = await _resolve_date(date)
    cache_key = f"limitup_screener_{target_date}"
    now = time.time()

    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _CACHE_TTL:
        age = now - hit[0]
        freshness = _assess_freshness(age)
        result = hit[1].model_copy(update={
            "data_freshness": freshness,
            "data_age_seconds": round(age, 1),
        })
        return result

    db_scores = load_gene_scores(target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:])
    if db_scores is not None:
        qualified = [g for g in db_scores if g.qualify]
        high_gene_list = [g for g in db_scores if g.high_gene]
        result = ScreenerResult(
            date=target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:],
            gene_scores=db_scores,
            qualified=qualified,
            high_gene=high_gene_list,
            updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            disclaimer=DISCLAIMER,
            data_freshness="fresh",
            data_age_seconds=0.0,
        )
        _CACHE[cache_key] = (now, result)
        return result

    if cache_key in _COMPUTING:
        waited = 0
        while cache_key in _COMPUTING and waited < 60:
            await asyncio.sleep(0.5)
            waited += 0.5
        hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < _CACHE_TTL:
            age = now - hit[0]
            freshness = _assess_freshness(age)
            return hit[1].model_copy(update={
                "data_freshness": freshness,
                "data_age_seconds": round(age, 1),
            })
        db_scores = load_gene_scores(target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:])
        if db_scores is not None:
            qualified = [g for g in db_scores if g.qualify]
            high_gene_list = [g for g in db_scores if g.high_gene]
            result = ScreenerResult(
                date=target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:],
                gene_scores=db_scores,
                qualified=qualified,
                high_gene=high_gene_list,
                updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
                disclaimer=DISCLAIMER,
                data_freshness="fresh",
                data_age_seconds=0.0,
            )
            _CACHE[cache_key] = (now, result)
            return result

    _COMPUTING[cache_key] = True
    result_holder = []
    error_holder = []

    try:
        def _compute_with_timeout():
            try:
                result_holder.append(_compute_and_cache(target_date, cache_key))
            except Exception as e:
                error_holder.append(e)

        compute_thread = threading.Thread(target=_compute_with_timeout, daemon=True)
        compute_thread.start()
        compute_thread.join(timeout=90)

        if error_holder:
            raise error_holder[0]

        if result_holder:
            return result_holder[0]

        # 超时（子线程 daemon hang，主 90s 返回）——_COMPUTING 由 finally 统一 pop
        return ScreenerResult(
            date=target_date[:4] + "-" + target_date[4:6] + "-" + target_date[6:],
            gene_scores=[],
            qualified=[],
            high_gene=[],
            updated=datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M"),
            disclaimer=DISCLAIMER + " （计算超时，请稍后刷新）",
            data_freshness="expired",
            data_age_seconds=0.0,
        )
    finally:
        # fix: 成功/错误/超时三出口统一 pop _COMPUTING，防泄漏（旧仅超时分支 pop，成功/错误泄漏致后续同 cache_key 卡 60s wait）
        _COMPUTING.pop(cache_key, None)


# ---- 公有接口（供 limitup_strategy 等外部模块调用） ----

async def public_resolve_date(date: str | None = None) -> str:
    """公有：解析日期参数，回推到最近交易日。"""
    return await _resolve_date(date)


async def public_fetch_zt_pool(date: str):
    """公有：获取涨停池、昨涨停池、炸板池（并发）。"""
    return await _fetch_zt_pool(date)


async def public_collect_zt_history_batch(codes: set[str], date: str, lookback: int = 252) -> dict[str, list]:
    """公有：批量回溯 lookback 天，收集多只股的涨停记录（返 ZTPoolItem，含 pool_date）。"""
    return await _collect_zt_history_batch(codes, date, lookback)


def public_get_cache() -> dict:
    """公有：获取内存缓存（只读）。"""
    return _CACHE


def public_get_cache_ttl() -> int:
    """公有：获取缓存 TTL。"""
    return _CACHE_TTL


def public_load_gene_scores(date: str) -> list | None:
    """公有：从数据库加载基因得分。"""
    from limitup_screener.data import load_gene_scores
    return load_gene_scores(date)


async def precompute_daily_async(date: str | None = None) -> ScreenerResult:
    """每日预计算入口（异步版本）。"""
    if date is None:
        date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    date_fmt = date.replace("-", "") if "-" in date else date

    # Fix A：交易日守卫——非交易日（周末/节假日）不预计算。
    # 根因：东财涨停池对非交易日请求静默回退返回最近交易日池，
    # 基因得分预计算会把上一交易日池标成非交易日入库，造成日期错位。
    # 同款模式见 limitup_sti/service.py 的 precompute_daily。
    from datetime import date as _date_cls
    try:
        _parsed = _date_cls.fromisoformat(
            f"{date_fmt[:4]}-{date_fmt[4:6]}-{date_fmt[6:8]}"
        )
        if not is_trading_day(_parsed):
            _logger.warning(
                "[screener] %s 非交易日，跳过基因得分预计算（防周末污染）",
                date_fmt,
            )
            return _empty_screener_result(date_fmt, reason="非交易日不预计算")
    except (ValueError, TypeError):
        # 日期格式异常无法判定，交由下游 _resolve_date 处理
        pass

    # S095 R2：未来日期硬闸门——is_trading_day 拦非交易日，本闸门拦"交易日但
    # 比最近交易日还未来"的边界情况（例如今天周五盘中请求下周一）。
    if not _assert_not_future_date(date_fmt):
        _logger.warning(
            "[s095] %s 未来日期拒绝写入（precompute_daily_async）", date_fmt,
        )
        return _empty_screener_result(date_fmt, reason="未来日期拒绝写入")

    target_date = await _resolve_date(date_fmt)
    cache_key = f"limitup_screener_{target_date}"
    return await _compute_and_cache_async(target_date, cache_key)


def precompute_daily(date: str | None = None) -> ScreenerResult:
    """每日预计算入口（同步兼容层）。"""
    if date is None:
        date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
    date_fmt = date.replace("-", "") if "-" in date else date

    # Fix A：交易日守卫（同步通道），同 precompute_daily_async。
    from datetime import date as _date_cls
    try:
        _parsed = _date_cls.fromisoformat(
            f"{date_fmt[:4]}-{date_fmt[4:6]}-{date_fmt[6:8]}"
        )
        if not is_trading_day(_parsed):
            _logger.warning(
                "[screener] %s 非交易日，跳过基因得分预计算（防周末污染）",
                date_fmt,
            )
            return _empty_screener_result(date_fmt, reason="非交易日不预计算")
    except (ValueError, TypeError):
        pass

    # S095 R2：未来日期硬闸门（同步通道），同 precompute_daily_async。
    if not _assert_not_future_date(date_fmt):
        _logger.warning(
            "[s095] %s 未来日期拒绝写入（precompute_daily）", date_fmt,
        )
        return _empty_screener_result(date_fmt, reason="未来日期拒绝写入")

    target_date = asyncio.run(_resolve_date(date_fmt))
    cache_key = f"limitup_screener_{target_date}"
    return _compute_and_cache(target_date, cache_key)


async def backfill_async(start_date: str, end_date: str | None = None) -> list[ScreenerResult]:
    """历史回填（异步版本）。"""
    if end_date is None:
        end_date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
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
        await asyncio.sleep(0.5)
    return results


def backfill(start_date: str, end_date: str | None = None) -> list[ScreenerResult]:
    """历史回填（同步兼容层）。"""
    if end_date is None:
        end_date = datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d")
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
        time.sleep(0.5)
    return results
