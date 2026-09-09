# -*- coding: utf-8 -*-
"""exclusions——三层剔除（封板质量/筹码/市场环境）。

实现范围：
- 007 层1：exclude_layer1_seal_quality（封板质量硬底线）
- 008 层2：exclude_layer2_chip_structure（grill 收紧：改透传，只预取 _chip_structure）
- 009-010 层3：exclude_layer3_market_env（市场环境 T-1 粗筛）
- 辅助：_sector_zt_count / _market_drop_pct
"""
from __future__ import annotations

import logging

from data.sources.baostock_src import fetch_bars  # noqa: E402  P2 DRY: baostock 统一接口
from market import _emotion  # noqa: E402  私有函数，任务要求；后续可升级公开接口
from astock import em_zt_topic_pool  # noqa: E402

from strategies.first_board.universe import EXCLUDE_THRESHOLDS
from strategies.first_board import data_extract as _data_extract
from strategies.first_board.data_extract import _HS300_PCT_CACHE

_logger = logging.getLogger(__name__)


def exclude_layer1_seal_quality(first_boards: list[dict]) -> tuple[list[dict], list[dict]]:
    """剔除层1：封板质量硬底线（不分市场状态，固定）。

    条件（任一命中即剔除，待回测校准）：
    - 炸板次数 ≥ max_break_times（默认 2）
    - 封单/流通市值 < min_seal_ratio（默认 0.1%，封单太薄）

    ⚠️ 首封时间不再硬剔除（改为 score_dim_seal_time 评分体现）。
    数据缺失降级：break_times/seal_amount/float_cap 任一缺失，跳过对应条件
    （不因数据缺失误剔除）。

    Args:
        first_boards: filter_first_board 返回的首板列表。

    Returns:
        (kept, filtered_records)：每项 {code, name, layer:1, reason}
    """
    kept: list[dict] = []
    filtered: list[dict] = []

    max_bt = EXCLUDE_THRESHOLDS["max_break_times"]
    min_sr = EXCLUDE_THRESHOLDS["min_seal_ratio"]

    for fb in first_boards:
        code = fb.get("code", "")
        reasons: list[str] = []

        # 条件1：炸板次数
        bt = fb.get("break_times")
        if bt is not None and bt >= max_bt:
            reasons.append(f"炸板{int(bt)}次")

        # 条件2：封单/流通市值
        seal = fb.get("seal_amount")
        fcap = fb.get("float_cap")
        if seal is not None and fcap is not None and fcap > 0:
            ratio = seal / fcap
            if ratio < min_sr:
                reasons.append(f"封单/流通市值{ratio*100:.2f}%")

        if reasons:
            filtered.append({
                "code": code,
                "name": fb.get("name", ""),
                "layer": 1,
                "reason": "/".join(reasons),
            })
        else:
            kept.append(fb)

    return kept, filtered


def exclude_layer2_chip_structure(
    candidates: list[dict], date: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """剔除层2：grill 收紧后简化为透传（不剔除，只缓存 _chip_structure 供评分用）。

    grill 收紧决策：移除换手>30% 硬剔除（改 score_dim_turnover 倒U型评分），
    层2不再剔除任何候选——只预取 _chip_structure（baostock 历史K线换手/量比/成交额）
    缓存到候选对象，供 score_dim_turnover / score_dim4_chip 评分复用，避免重复请求。

    Args:
        candidates: 通过层1的候选 list[dict]。
        date: YYYY-MM-DD 或 YYYYMMDD（T-1 日，用于查 baostock 历史 K 线）。

    Returns:
        (kept, filtered_records)：kept=candidates 原样透传，filtered=[]（不剔除）。
    """
    for fb in candidates:
        # 预取筹码结构缓存（供评分复用，不剔除）
        if fb.get("_chip_structure") is None:
            code = fb.get("code", "")
            fb["_chip_structure"] = _data_extract.extract_chip_structure(code, date)
    return list(candidates), []


def _sector_zt_count(first_boards: list[dict], industry: str | None) -> int:
    """同板块涨停数（含首板+连板，基于 first_boards 池聚合）。

    industry 为 None 或空 → 返回 0（无法判定板块，视为孤板）。
    """
    if not industry:
        return 0
    return sum(1 for fb in first_boards if (fb.get("industry") or "") == industry)


def _market_drop_pct(date: str) -> float | None:
    """沪深300 当日涨跌幅（历史，无未来函数）。

    数据源：baostock 查 sh.000300 历史日K（``pctChg`` 字段=涨跌幅%）。
    baostock 指数 K 线不入 baostock_kline_cache.json（缓存只含个股），
    故用 baostock 库实时查历史指数（非实时行情，历史数据无未来函数）。
    模块级缓存避免重复 login。

    Args:
        date: YYYY-MMDD 或 YYYY-MM-DD（归一为 YYYY-MM-DD 查 baostock）。

    Returns:
        沪深300 涨跌幅（百分数，如 -1.8 表示跌 1.8%）。
        取不到 → None（不阻塞层3）。

    ⚠️ 无未来函数：用 date 当日历史指数数据，不用 index_quote() 实时接口。
    旧实现调 index_quote() 返回 T 日指数，用于 T-1 市场环境 = 未来函数。
    """
    d = date if "-" in date else f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    # 模块级缓存（date → pct），避免重复 login/query
    if d in _HS300_PCT_CACHE:
        return _HS300_PCT_CACHE[d]
    try:
        bars = fetch_bars("sh.000300", d, d, fields="date,pctChg", adjustflag="3")
        pct: float | None = bars[0]["pctChg"] if bars else None
        _HS300_PCT_CACHE[d] = pct
        return pct
    except Exception as e:
        _logger.warning("_market_drop_pct baostock 指数失败 date=%s err=%s", d, e)
        return None


def exclude_layer3_market_env(
    candidates: list[dict], date: str, first_boards: list[dict] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """剔除层3：市场环境（T-1 粗筛）。

    条件：
    - 大盘跌 > market_drop_threshold（默认 -1.5%）→ 标记 high_risk（不直接剔除，
      仅在 env_flags 标记；实盘需结合其他信号）
    - 同板块涨停 < min_sector_zt_count（默认 2）且无题材 → 剔除（孤板无板块效应）

    数据来源：market._emotion(date)（max_boards/ladder）+ 上证指数实时行情 +
    first_boards 自身同板块聚合。

    数据缺失降级：_emotion 返空或指数取不到 → env_flags 对应字段 None，
    不剔除（层3 失败不阻塞候选）。

    Args:
        candidates: 通过层2的候选 list[dict]。
        date: YYYYMMDD 或 YYYY-MM-DD，涨停池日期。
        first_boards: filter_first_board 返回的首板池（用于同板块聚合）。
                      None 则用 candidates 自身（候选池可能已过滤，板块计数偏小）。

    Returns:
        (kept, filtered_records, env_flags)：
        - kept: 通过层3的候选 list[dict]
        - filtered_records: 被剔除记录 list[dict]，每项 {code, layer:3, reason}
        - env_flags: dict 含
            - market_drop_pct: float | None（上证涨跌幅，百分数）
            - high_risk: bool（大盘跌 >1.5% 标记）
            - max_boards: int | None（最高连板）
            - ladder_broken: bool（无连板梯队，max_boards<2）
    """
    fb_pool = first_boards if first_boards is not None else candidates

    # 取市场情绪（max_boards/ladder）
    emotion: dict = {}
    try:
        emotion = _emotion(date) or {}
    except Exception as e:
        _logger.warning("exclude_layer3 _emotion 失败 date=%s err=%s", date, e)
        emotion = {}

    max_boards_raw = emotion.get("max_boards")
    max_boards = int(max_boards_raw) if max_boards_raw is not None else None
    ladder = emotion.get("ladder") or []
    ladder_broken = (max_boards is not None and max_boards < 2) or (not ladder)

    # 取大盘涨跌幅
    market_drop = _market_drop_pct(date)
    threshold = EXCLUDE_THRESHOLDS["market_drop_threshold"]
    high_risk = (market_drop is not None and market_drop <= threshold)

    env_flags: dict = {
        "market_drop_pct": market_drop,
        "high_risk": high_risk,
        "max_boards": max_boards,
        "ladder_broken": ladder_broken,
    }

    # 层3 grill 收紧：改纯环境标记（不剔除，只输出 env_flags）
    # 孤板/创业板不硬剔除，改评分（score_dim_sector_link 体现板块联动）
    # 只预取 _sector_info 缓存供评分复用
    for fb in candidates:
        code = fb.get("code", "")
        if fb.get("_sector_info") is None:
            fb["_sector_info"] = _data_extract.extract_sector(code)

    # grill 收紧：层3不剔除任何候选，全部保留（环境风险在 env_flags 标记，
    # 评分权重分层 market_phase 体现——冰点档降仓位而非清空）
    return list(candidates), [], env_flags
