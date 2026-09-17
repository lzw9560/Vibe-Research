# -*- coding: utf-8 -*-
"""scoring——15 个 score_dim* + score_candidate + rank_candidates。

实现范围：
- 011-019 9 维度评分：score_dim1_sector ~ score_dim9_event
- 新增 5 维度（grill 锁定）：score_dim_seal_time/sector_link/market_cap/seal_ratio/turnover
- 020 加权总分：score_candidate（权重按市场档位分层）
- 020 排序：rank_candidates（按板块分组+降序）
"""
from __future__ import annotations

import logging
import math

from astock import em_zt_topic_pool  # noqa: E402

from strategies.first_board.universe import (
    _market_phase,
    _fbt_to_hhmm,
    MARKET_PHASE_WEIGHTS,
    _emotion,
)
from strategies.first_board import data_extract as _data_extract

_logger = logging.getLogger(__name__)


# ===========================================================================
# 011-019 9 维度评分（每维度 0-100，数据缺失降级 50 中性）
# ===========================================================================
# 统一签名：def score_dimN_code(candidate: dict, date: str) -> float
# 返回 0-100 分。数据缺失时 try/except 返 50 分中性（不抛异常，不阻塞主流程）。
# 每个维度顶部注释"§44 未 validated，待回测校准"——维度内部逻辑未经 §44 验证。

# ── 维度1：板块评分（权重 15%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：em_zt_topic_pool hybk（行业）字段聚合同行业涨停数
#   （不依赖 gene_scores.db 当日回填——盘后未回填导致降级50）
# 逻辑：同行业涨停≥3 只=联动强，0-100 归一化。
# em_zt_topic_pool 有 24h TTL 缓存，重复调不慢（fetch_zt_pool 已拉过，命中缓存）。

def score_dim1_sector(candidate: dict, date: str) -> tuple[float, dict]:
    """板块评分——用涨停池 industry（hybk）字段聚合同行业涨停数。

    不依赖 gene_scores.db 当日回填（盘后未回填导致 sectors 为空 → 50 降级）。
    改用 candidate.industry（来自 em_zt_topic_pool hybk 字段）+ 涨停池聚合。

    Args:
        candidate: filter_first_board 产出的候选 dict（含 industry 字段）。
        date: YYYYMMDD。

    Returns:
        (score, raw)：raw 含 sector_zt_count（同行业涨停数）/industry（行业名）。
        数据缺失时对应字段 None。
    """
    raw: dict = {"sector_rank": None, "sector_zt_count": None, "industry": None}
    try:
        industry = candidate.get("industry")
        if not industry:
            return 50.0, raw
        raw["industry"] = industry

        # 从涨停池统计同行业涨停数（em_zt_topic_pool 有 24h TTL 缓存，不重复请求）
        # S131 R5：raise_on_failure=True 让源断 raise（非吞 [] 伪装零联动），
        # 外层 try/except 兜底返 50.0 降级。
        compact = date.replace("-", "") if "-" in date else date
        pool = em_zt_topic_pool("getTopicZTPool", compact, "fbt:asc", raise_on_failure=True) or []
        same_industry_count = sum(1 for p in pool if (p.get("hybk") or "") == industry)
        raw["sector_zt_count"] = same_industry_count

        # 同行业涨停数 → 评分
        if same_industry_count >= 3:
            score = 100.0  # 板块联动强
        elif same_industry_count >= 2:
            score = 80.0
        elif same_industry_count >= 1:
            score = 60.0  # 含自身，有板块归属
        else:
            score = 40.0  # 孤板（理论不会，因为 candidate 自身在该行业）
        return round(score, 1), raw
    except Exception as e:
        _logger.debug("score_dim1_sector 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度2：游资画像（权重 15%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：astock.dragon_tiger_board 取最近龙虎榜记录
#   （不取当日龙虎榜——盘后当日未出→compute_seat_risk_factor "无数据"→50 降级）
# 逻辑：有上榜记录=游资参与，机构净买入=接力支撑，0-100 归一化。

def score_dim2_hot_money(candidate: dict, date: str) -> tuple[float, dict]:
    """游资画像评分——用最近龙虎榜记录（不取当日）。

    旧实现调 compute_seat_risk_factor(code, date) 取当日龙虎榜，盘后当日未出 →
    "无数据" → 50 降级。改用 dragon_tiger_board(code) 取最近 30 天上榜记录，
    从 records 数量 + institution.net_amt 判断游资活跃度。

    Args:
        candidate: 候选 dict（含 code）。
        date: YYYYMMDD（本维度取最近龙虎榜，不严格按 date）。

    Returns:
        (score, raw)：raw 含 seat_risk_label（风险标签）/one_day_ratio（一日游占比，
        最近龙虎榜无此字段，恒 None）/billboard_count（上榜次数）/inst_net（机构净买入万元）。
        数据缺失时对应字段 None。
    """
    raw: dict = {
        "seat_risk_label": None, "one_day_ratio": None,
        "billboard_count": None, "inst_net": None,
    }
    try:
        from astock import dragon_tiger_board
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        _dt = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date  # S085 A2d：YYYYMMDD→ISO（dragon_tiger_board strptime %Y-%m-%d，裸传 YYYYMMDD 会 ValueError→静默 50）
        raw_dt = dragon_tiger_board(code, trade_date=_dt) or {}  # S085 A2d 残留：传 date 修 replay 误取今日
        records = raw_dt.get("records") or []
        institution = raw_dt.get("institution") or {}
        billboard_count = len(records)
        inst_net = institution.get("net_amt") if isinstance(institution, dict) else None
        raw["billboard_count"] = billboard_count
        raw["inst_net"] = inst_net

        if billboard_count == 0:
            raw["seat_risk_label"] = "无龙虎榜记录"
            return 50.0, raw

        # 有上榜记录 → 游资参与，基础分 60
        score = 60.0
        raw["seat_risk_label"] = "有龙虎榜记录"
        # 机构净买入 > 0 → 接力支撑加分
        if inst_net is not None and inst_net > 0:
            # 机构净买入 0-5000 万 → +10-20 分
            score = 60.0 + min(20.0, math.log10(max(inst_net, 1.0)) * 5.0)
            raw["seat_risk_label"] = "机构净买入接力"
        # 上榜次数多（≥3 次）→ 游资活跃再加 5 分
        if billboard_count >= 3:
            score = min(score + 5.0, 100.0)
            raw["seat_risk_label"] = f"游资活跃({billboard_count}次上榜)"

        return round(max(0.0, min(100.0, score)), 1), raw
    except Exception as e:
        _logger.debug("score_dim2_hot_money 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度3：封板强度（权重 20%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：ZTPoolItem 封单/首封/炸板 + breakout_20d（可选）+ 振幅
# 逻辑：封板越早/封单越大/不炸=越强，0-100 加权。

def score_dim3_seal_strength(candidate: dict, date: str) -> tuple[float, dict]:
    """封板强度评分。

    逻辑（加权，各子项 0-100）：
    - 首封时间（40%）：9:25-9:30 满分，越晚越低，14:00 后 0 分
    - 封单/流通市值（30%）：≥2% 满分，<0.5% 0 分
    - 炸板次数（30%）：0 炸板满分，≥2 次 0 分

    Args:
        candidate: 候选 dict（含 first_seal/seal_amount/float_cap/break_times）。
        date: YYYYMMDD（本维度不直接用，预留）。

    Returns:
        (score, raw)：raw 含 first_seal/seal_amount/float_cap/seal_ratio/break_times。
        数据缺失时对应字段 None。
    """
    raw: dict = {
        "first_seal": None, "seal_amount": None, "float_cap": None,
        "seal_ratio": None, "break_times": None,
    }
    try:
        # 子项1：首封时间（92500-145000 → 0-100）
        fbt = candidate.get("first_seal")
        raw["first_seal"] = fbt
        time_score = 50.0  # 缺失中性
        if fbt is not None and 90000 <= fbt <= 150000:
            # 92500=满分，145000=0 分，线性递减
            if fbt <= 93000:
                time_score = 100.0  # 开盘秒板
            elif fbt <= 100000:
                time_score = 90.0  # 早盘
            elif fbt <= 130000:
                time_score = 70.0  # 上午-午后
            elif fbt <= 140000:
                time_score = 40.0  # 下午
            else:
                time_score = 20.0  # 尾盘

        # 子项2：封单/流通市值
        seal = candidate.get("seal_amount")
        fcap = candidate.get("float_cap")
        raw["seal_amount"] = seal
        raw["float_cap"] = fcap
        seal_score = 50.0  # 缺失中性
        if seal is not None and fcap is not None and fcap > 0:
            ratio = seal / fcap  # 0-1
            raw["seal_ratio"] = round(ratio, 4)
            if ratio >= 0.02:
                seal_score = 100.0
            elif ratio >= 0.01:
                seal_score = 80.0
            elif ratio >= 0.005:
                seal_score = 60.0
            elif ratio >= 0.001:
                seal_score = 30.0
            else:
                seal_score = 10.0

        # 子项3：炸板次数
        bt = candidate.get("break_times")
        raw["break_times"] = bt
        bt_score = 100.0  # 缺失视为不炸（满分）
        if bt is not None:
            if bt == 0:
                bt_score = 100.0
            elif bt == 1:
                bt_score = 60.0
            elif bt >= 2:
                bt_score = 0.0

        total = time_score * 0.40 + seal_score * 0.30 + bt_score * 0.30
        return round(max(0.0, min(100.0, total)), 1), raw
    except Exception as e:
        _logger.debug("score_dim3_seal_strength 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度4：筹码结构（权重 10%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：tencent_quote 换手/量比/成交额/振幅
# 逻辑：缩量+健康换手=筹码稳定，0-100 加权。

def score_dim4_chip(candidate: dict, date: str) -> tuple[float, dict]:
    """筹码结构评分。

    逻辑（加权，各子项 0-100）：
    - 换手率（40%）：5-15% 健康满分，>25% 筹码松动 0 分，<2% 过冷 30 分
    - 量比（30%）：0.8-1.5 健康满分，≥2.0 放量 0 分
    - 成交额（30%）：1-10 亿健康满分，>15 亿过大 0 分

    数据来源：tencent_quote（实时/盘后收盘行情）。
    数据缺失 → 该子项 -1 不参与加权（对齐 score_dim_turnover sibling）；
    全部子项缺失 → 维度返 -1 不参与加权（不伪装"筹码结构中等"，防 chip 权重启用即引爆）。

    Returns:
        (score, raw)：raw 含 turnover（换手率%）/vol_ratio（量比）/amount（成交额元）。
        数据缺失时对应字段 None。
    """
    raw: dict = {"turnover": None, "vol_ratio": None, "amount": None}
    try:
        chip = candidate.get("_chip_structure")
        if chip is None:
            chip = _data_extract.extract_chip_structure(candidate.get("code", ""), date)
            candidate["_chip_structure"] = chip

        # 子项1：换手率（缺失→-1 不参与加权）
        tp = chip.get("turnover_pct")
        raw["turnover"] = tp
        tp_score = -1.0
        if tp is not None:
            if 5.0 <= tp <= 15.0:
                tp_score = 100.0
            elif 2.0 <= tp < 5.0 or 15.0 < tp <= 25.0:
                tp_score = 70.0
            elif tp > 25.0:
                tp_score = 0.0
            else:  # < 2.0
                tp_score = 30.0

        # 子项2：量比（缺失→-1 不参与加权）
        vr = chip.get("vol_ratio")
        raw["vol_ratio"] = vr
        vr_score = -1.0
        if vr is not None:
            if 0.8 <= vr <= 1.5:
                vr_score = 100.0
            elif 0.5 <= vr < 0.8 or 1.5 < vr < 2.0:
                vr_score = 70.0
            elif vr >= 2.0:
                vr_score = 0.0
            else:  # < 0.5
                vr_score = 30.0

        # 子项3：成交额（优先 tencent amount，降级涨停池 amount；缺失→-1 不参与加权）
        amt = chip.get("amount")
        if amt is None:
            amt = candidate.get("amount")
        raw["amount"] = amt
        amt_score = -1.0
        if amt is not None:
            amt_yi = amt / 1e8  # 元 → 亿
            if 1.0 <= amt_yi <= 10.0:
                amt_score = 100.0
            elif 0.3 <= amt_yi < 1.0 or 10.0 < amt_yi <= 15.0:
                amt_score = 70.0
            elif amt_yi > 15.0:
                amt_score = 0.0
            else:  # < 0.3 亿
                amt_score = 30.0

        # 加权：缺失子项（-1）不参与，权重重分配到有效子项
        # （对齐 score_candidate 维度级 -1 重分配）；全部缺失 → 维度返 -1 不参与加权
        # （对齐 score_dim_turnover 缺失返 -1）。
        sub_items = ((tp_score, 0.40), (vr_score, 0.30), (amt_score, 0.30))
        active = [(s, w) for s, w in sub_items if s >= 0]
        if not active:
            return -1.0, raw
        weighted_sum = sum(s * w for s, w in active)
        total = weighted_sum / sum(w for _, w in active)
        return round(max(0.0, min(100.0, total)), 1), raw
    except Exception as e:
        _logger.debug("score_dim4_chip 数据缺失 -1 code=%s err=%s", candidate.get("code"), e)
        return -1.0, raw


# ── 维度5：竞价确认（权重 10%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：T 日 9:25 竞价高开 1-3% + 竞价量≥昨日 5%
# 逻辑：T 日盘前实时，T-1 盘后预填 0 待 T 日更新。

def score_dim5_auction(candidate: dict, date: str) -> tuple[float, dict]:
    """竞价确认评分（废弃——数据缺失返 -1 不参与加权）。

    T-1 盘后无 T 日竞价数据 → 返 -1（数据缺失，不参与加权，权重重分配）。
    T 日盘前 9:25 后实盘接入时从 astock 取竞价数据重算。

    Returns:
        (score, raw)：score=-1（数据缺失），raw 两字段均 None。
    """
    raw: dict = {"auction_open_pct": None, "auction_vol_ratio": None}
    return -1.0, raw  # 数据缺失，不参与加权


# ── 维度6：北向资金（权重 10%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：predict.features.fund_flow.fetch_northbound 个股北向净流入
# 逻辑：正流入加分（2024-08-19 后停更降级 50 分）

def score_dim6_northbound(candidate: dict, date: str) -> tuple[float, dict]:
    """北向资金评分。

    逻辑：
    - 调 fetch_northbound(code, date) 取个股北向净流入（万元）
    - 正流入（>0）→ 70-100 分（越大越高）
    - 负流出（<0）→ 0-50 分
    - None（停更/无数据）→ 50 分中性

    2024-08-19 北向规则变更后个股日级北向数据停更，返 None → 50 分中性。

    Returns:
        (score, raw)：raw 含 northbound_net（北向净流入，万元）。
        停更/无数据 → None。
    """
    raw: dict = {"northbound_net": None}
    try:
        from predict.features.fund_flow import fetch_northbound
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        d = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date
        nb = fetch_northbound(code, d)  # 万元
        raw["northbound_net"] = nb
        if nb is None:
            # 2024-08-19 后个股北向停更 / 当日无数据 → -1（数据缺失，不参与加权）
            return -1.0, raw
        if nb > 0:
            # 正流入：0-10000 万 → 70-100 分（对数缩放，避免极值）
            score = 70.0 + min(30.0, math.log10(max(nb, 1.0)) * 10.0)
            return round(max(0.0, min(100.0, score)), 1), raw
        else:
            # 负流出：0 到 -5000 万 → 50 到 0 分
            score = max(0.0, 50.0 + (nb / 100.0))  # 每流出 100 万扣 1 分
            return round(max(0.0, min(100.0, score)), 1), raw
    except Exception as e:
        # fail-closed（2026-09-17 修，workflow wxs85fzwg 风险专家发现）：
        # 取数异常 → -1（数据缺失不参与加权），不返 50（fail-open 数据坏时放行，违不臆造底线）
        _logger.debug("score_dim6_northbound 降级 -1 fail-closed code=%s err=%s", candidate.get("code"), e)
        return -1.0, raw


# ── 维度7：龙虎榜机构（权重 10%）──────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：astock.dragon_tiger_board + data.mappers.dragon_tiger_from_dict
# 逻辑：机构净买入=基本面认可（无龙虎榜降级 50 分）

def score_dim7_institution(candidate: dict, date: str) -> tuple[float, dict]:
    """龙虎榜机构评分。

    逻辑：
    - 调 astock.dragon_tiger_board(code) 取机构净买入（万元）
    - 机构净买入 >0 → 70-100 分（越大越高）
    - 机构净卖出 <0 → 0-50 分
    - 无龙虎榜 / 无机构席位 → 50 分中性

    Returns:
        (score, raw)：raw 含 inst_net（机构净买入，万元）。
        无龙虎榜/无机构席位 → None。
    """
    raw: dict = {"inst_net": None}
    try:
        from astock import dragon_tiger_board
        from data.mappers import dragon_tiger_from_dict
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        _dt = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 else date  # S085 A2d：YYYYMMDD→ISO（dragon_tiger_board strptime %Y-%m-%d，裸传 YYYYMMDD 会 ValueError→静默 50）
        raw_dt = dragon_tiger_board(code, trade_date=_dt) or {}  # S085 A2d 残留：传 date 修 replay 误取今日
        dt = dragon_tiger_from_dict(raw_dt)
        inst_net = dt.institution_net  # 万元
        raw["inst_net"] = inst_net
        if inst_net is None:
            # 无龙虎榜 / 无机构席位 → 50 分中性
            return 50.0, raw
        if inst_net > 0:
            # 机构净买入：0-5000 万 → 70-100 分
            score = 70.0 + min(30.0, math.log10(max(inst_net, 1.0)) * 10.0)
            return round(max(0.0, min(100.0, score)), 1), raw
        else:
            # 机构净卖出：每卖出 100 万扣 1 分
            score = max(0.0, 50.0 + (inst_net / 100.0))
            return round(max(0.0, min(100.0, score)), 1), raw
    except Exception as e:
        _logger.debug("score_dim7_institution 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度8：题材热度（权重 5%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：astock.ths_limit_up_pool reason 聚合
# 逻辑：同题材涨停≥3 只=满热度

def score_dim8_theme(candidate: dict, date: str) -> tuple[float, dict]:
    """题材热度评分。

    逻辑：
    - 调 ths_limit_up_pool(date) 取涨停池 reason 题材聚合
    - 候选股 reason 命中题材涨停≥3 只 → 100 分（满热度）
    - 2 只 → 70 分
    - 1 只（自身）→ 30 分（无题材热度）
    - 无 reason / 数据缺失 → 50 分中性

    Returns:
        (score, raw)：raw 含 theme_zt_count（同题材涨停数）/theme_name（命中的题材名）。
        数据缺失时对应字段 None。
    """
    raw: dict = {"theme_zt_count": None, "theme_name": None}
    try:
        from astock import ths_limit_up_pool
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        pool = ths_limit_up_pool(date)
        if not pool:
            return 50.0, raw
        # 找到候选股的 reason
        cand_item = next((p for p in pool if p.get("code") == code), None)
        if not cand_item or not cand_item.get("reason"):
            return 50.0, raw
        reason = cand_item["reason"]
        raw["theme_name"] = reason
        # split 题材（+ / 、 / ; 等分隔）
        for sep in ("+", "、", ";", "，", "/"):
            reason = reason.replace(sep, "+")
        tags = [t.strip() for t in reason.split("+") if t.strip()]
        if not tags:
            return 50.0, raw
        # 聚合每个题材的涨停数
        concept_count: dict[str, int] = {}
        for item in pool:
            r = (item.get("reason") or "").strip()
            if not r:
                continue
            for sep in ("+", "、", ";", "，", "/"):
                r = r.replace(sep, "+")
            for tag in r.split("+"):
                tag = tag.strip()
                if tag:
                    concept_count[tag] = concept_count.get(tag, 0) + 1
        # 取候选股题材的最大涨停数
        max_count = max((concept_count.get(t, 0) for t in tags), default=0)
        raw["theme_zt_count"] = max_count
        # theme_name 精确为涨停数最多的那个题材
        if tags:
            best_tag = max(tags, key=lambda t: concept_count.get(t, 0))
            raw["theme_name"] = best_tag
        if max_count >= 3:
            return 100.0, raw
        elif max_count == 2:
            return 70.0, raw
        elif max_count == 1:
            return 30.0, raw
        else:
            return 50.0, raw
    except Exception as e:
        _logger.debug("score_dim8_theme 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ── 维度9：事件评分（权重 5%）──────────────────────────────────────────
# §44 未 validated，待回测校准。
# 数据源：astock.announcements + news_radar_context.classify_announcement
# 逻辑：#33/#34 利多加分 + #35-39 利空扣分，无公告=50 分中性

def score_dim9_event(candidate: dict, date: str) -> tuple[float, dict]:
    """事件评分。

    逻辑：
    - 调 astock.announcements(code) 取近期公告
    - 用 classify_announcement(title) 分类
    - 预增/扭亏/重组/回购/增持（#33/#34 利好）→ 70-100 分
    - 风险提示（#35-39 利空）→ 0-30 分
    - 未知/无公告 → 50 分中性

    Args:
        candidate: 候选 dict（含 code）。
        date: YYYYMMDD（本维度取近期公告，不严格按 date）。

    Returns:
        (score, raw)：raw 含 event_type（利多/利空/中性分类）/announcement_title（公告标题）。
        无公告时 event_type="无公告"，announcement_title=None。
    """
    raw: dict = {"event_type": None, "announcement_title": None}
    try:
        from astock import announcements
        from strategies.news_radar_context import classify_announcement
        code = candidate.get("code", "")
        if not code:
            return 50.0, raw
        anns = announcements(code, limit=10) or []
        if not anns:
            # 无公告 → 50 分中性
            raw["event_type"] = "无公告"
            return 50.0, raw
        # 取最近一条公告分类
        latest = anns[0] if isinstance(anns[0], dict) else {}
        title = latest.get("title") or ""
        raw["announcement_title"] = title
        ann_type = classify_announcement(title)
        raw["event_type"] = ann_type
        if ann_type in ("预增", "扭亏", "重组", "回购", "增持"):
            # 利好：预增/扭亏=90，重组=85，回购=80，增持=75
            score_map = {"预增": 90.0, "扭亏": 90.0, "重组": 85.0, "回购": 80.0, "增持": 75.0}
            return score_map.get(ann_type, 70.0), raw
        elif ann_type == "风险提示":
            # 利空：0-30 分
            return 20.0, raw
        else:
            # 未知/其他 → 50 分中性
            return 50.0, raw
    except Exception as e:
        _logger.debug("score_dim9_event 降级 50 code=%s err=%s", candidate.get("code"), e)
        return 50.0, raw


# ===========================================================================
# 新增评分维度（grill 锁定：封板时间/板块联动/市值/封单比，待回测校准）
# ===========================================================================
# 数据缺失维度返 score=-1，不参与加权（权重重分配到其他有效维度）。

def score_dim_seal_time(candidate: dict, date: str) -> tuple[float, dict]:
    """封板时间评分——10:30 前满分，越晚越低。

    旧层1的 late_seal_time 硬剔除改为评分（grill 决策）。

    Returns:
        (score, raw)：raw 含 first_seal/seal_time_hhmm。
        first_seal 缺失 → score=-1（不参与加权）。
    """
    raw: dict = {"first_seal": None, "seal_time_hhmm": None}
    fbt = candidate.get("first_seal")
    if fbt is None:
        return -1.0, raw  # 数据缺失，不参与加权
    raw["first_seal"] = fbt
    raw["seal_time_hhmm"] = _fbt_to_hhmm(fbt)
    # fbt 格式 HHMMSS 数字，92500=09:25:00
    if fbt <= 103000:      # 10:30 前满分
        return 100.0, raw
    elif fbt <= 110000:    # 10:30-11:00
        return 80.0, raw
    elif fbt <= 130000:    # 11:00-13:00
        return 60.0, raw
    elif fbt <= 140000:    # 13:00-14:00
        return 40.0, raw
    else:                  # 14:00 后尾盘
        return 20.0, raw


def score_dim_sector_link(candidate: dict, date: str) -> tuple[float, dict]:
    """板块联动评分——同行业涨停≥3 只满分。

    复用 score_dim1_sector 的 em_zt_topic_pool hybk 聚合逻辑（不依赖 gene_scores.db）。

    Returns:
        (score, raw)：raw 含 sector_zt_count/industry。
        industry 缺失 → score=-1。
    """
    raw: dict = {"sector_zt_count": None, "industry": None}
    try:
        industry = candidate.get("industry")
        if not industry:
            return -1.0, raw  # 无行业归属，数据缺失
        raw["industry"] = industry
        compact = date.replace("-", "") if "-" in date else date
        # S131 R5：raise_on_failure=True 让源断 raise（非吞 [] 伪装零联动），
        # 外层 try/except 兜底返 -1.0（数据缺失不参与加权）。
        pool = em_zt_topic_pool("getTopicZTPool", compact, "fbt:asc", raise_on_failure=True) or []
        same_industry_count = sum(1 for p in pool if (p.get("hybk") or "") == industry)
        raw["sector_zt_count"] = same_industry_count
        if same_industry_count >= 3:
            return 100.0, raw  # 板块联动强
        elif same_industry_count >= 2:
            return 80.0, raw
        elif same_industry_count >= 1:
            return 60.0, raw
        else:
            return 40.0, raw
    except Exception as e:
        _logger.debug("score_dim_sector_link 降级 -1 code=%s err=%s", candidate.get("code"), e)
        return -1.0, raw


def score_dim_market_cap(candidate: dict, date: str) -> tuple[float, dict]:
    """市值评分——流通市值<200 亿满分（小盘更易封板）。

    Returns:
        (score, raw)：raw 含 float_cap_yi。
        float_cap 缺失 → score=-1。
    """
    raw: dict = {"float_cap_yi": None}
    float_cap = candidate.get("float_cap")
    if not float_cap or float_cap <= 0:
        return -1.0, raw
    cap_yi = float_cap / 1e8  # 转亿
    raw["float_cap_yi"] = round(cap_yi, 2)
    if cap_yi < 50:
        return 100.0, raw
    elif cap_yi < 100:
        return 90.0, raw
    elif cap_yi < 200:
        return 80.0, raw
    elif cap_yi < 500:
        return 50.0, raw
    else:
        return 30.0, raw


def score_dim_seal_ratio(candidate: dict, date: str) -> tuple[float, dict]:
    """封单比评分——封单/流通市值越高越好。

    旧层1的 min_seal_ratio 硬剔除底线保留（0.1%），但 0.1%-2% 区间改为评分。

    Returns:
        (score, raw)：raw 含 seal_ratio。
        seal_amount/float_cap 缺失 → score=-1。
    """
    raw: dict = {"seal_ratio": None}
    seal = candidate.get("seal_amount")
    fcap = candidate.get("float_cap")
    if not seal or not fcap or fcap <= 0:
        return -1.0, raw
    ratio = seal / fcap
    raw["seal_ratio"] = round(ratio, 4)
    if ratio >= 0.02:       # ≥2% 满分
        return 100.0, raw
    elif ratio >= 0.01:    # 1-2%
        return 80.0, raw
    elif ratio >= 0.005:   # 0.5-1%
        return 60.0, raw
    else:                  # <0.5%（含硬剔除底线 0.1% 以上的）
        return 30.0, raw


def score_dim_turnover(candidate: dict, date: str) -> tuple[float, dict]:
    """换手率评分——倒 U 型，5-15% 最优（grill 收紧：换手改评分，不硬剔除）。

    数据源：baostock 历史K线 turn 字段（extract_chip_structure 已预取缓存）。
    旧层2的 max_turnover=30% 硬剔除改为评分：
    - 5-15% 健康满分（筹码交换充分但不松动）
    - 2-5% / 15-25% 次优（偏冷/偏热）
    - >25% 低分（筹码松动）
    - <2% 过冷（无人气）

    Returns:
        (score, raw)：raw 含 turnover_pct。
        数据缺失（无 baostock 历史K线）→ score=-1 不参与加权。
    """
    raw: dict = {"turnover_pct": None}
    # 复用层2预取的 _chip_structure 缓存（避免重复请求 baostock）
    chip = candidate.get("_chip_structure")
    if chip is None:
        chip = _data_extract.extract_chip_structure(candidate.get("code", ""), date)
        candidate["_chip_structure"] = chip
    tp = chip.get("turnover_pct")
    raw["turnover_pct"] = tp
    if tp is None:
        return -1.0, raw  # 数据缺失，不参与加权
    if 5.0 <= tp <= 15.0:
        return 100.0, raw
    elif 2.0 <= tp < 5.0 or 15.0 < tp <= 25.0:
        return 70.0, raw
    elif tp > 25.0:
        return 30.0, raw  # 筹码松动低分（不再硬剔除）
    else:  # < 2.0
        return 40.0, raw  # 过冷


# _SCORE_DIMS / score_candidate / rank_candidates 见 pipeline.py（S174 拆分：
# 15 个 score_dim* 留 scoring.py（同域内聚），加权+排序移 pipeline.py 保 <800 行）。
