# -*- coding: utf-8 -*-
"""S066 §5 板块周期分析——3 日时序阶段分类。

从 gene_scores.db 按 (date, industry) 聚合涨停股数，计算 3 日时序动量，
判定板块在周期中的位置（启动/发酵/高潮/退潮/冷门/无历史）。

零额外 API 调用——全部从已有 gene_scores.db 计算。
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from vr_paths import resolve_data_dir

_DB = resolve_data_dir() / "gene_scores.db"


@dataclass(frozen=True)
class SectorPhase:
    """板块周期阶段分析结果。"""
    industry: str
    count_today: int
    count_avg_3d: float
    momentum: float
    phase: str  # 启动/发酵/高潮/退潮/冷门/无历史
    modifier: float  # 策略分修饰系数
    phase_note: str
    stay_days: int = 0  # task 118：连续在榜（≥1 涨停）交易日数（含 date）；0=今日不在榜


# 阶段 → 修饰系数（spec §5.4）
_PHASE_MODIFIERS: dict[str, tuple[float, str]] = {
    "启动": (1.1, "板块可能加速"),
    "发酵": (1.0, "板块正常升温"),
    "高潮": (0.9, "高潮期，注意退潮"),
    "退潮": (0.7, "追入即套"),
    "冷门": (0.8, "无板块支撑"),
    "无历史": (1.0, "中性"),
}


def _get_zt_count_by_date_industry(date: str, industry: str) -> int:
    """某日某板块涨停股数（S066 Q16 回填 industry 列后直查；原 stub 因无此列恒返 0）。"""
    conn = sqlite3.connect(str(_DB))
    try:
        return conn.execute(
            "SELECT COUNT(DISTINCT code) FROM gene_scores WHERE date = ? AND industry = ?",
            (date, industry),
        ).fetchone()[0] or 0
    except Exception:
        return 0
    finally:
        conn.close()


def classify_phase(count_today: int, count_avg_3d: float, has_history: bool = True) -> tuple[str, float, str]:
    """阶段分类（spec §5.2）。

    返回 (phase, modifier, note)。
    """
    if not has_history:
        return "无历史", 1.0, "数据不全或新板块"

    if count_avg_3d <= 1 and count_today >= 1:
        mod, note = _PHASE_MODIFIERS["启动"]
        return "启动", mod, note
    if count_today >= 5 and count_today >= count_avg_3d:
        mod, note = _PHASE_MODIFIERS["高潮"]
        return "高潮", mod, note
    if count_today > count_avg_3d and count_avg_3d >= 1:
        mod, note = _PHASE_MODIFIERS["发酵"]
        return "发酵", mod, note
    if count_today < count_avg_3d and count_avg_3d >= 3:
        mod, note = _PHASE_MODIFIERS["退潮"]
        return "退潮", mod, note
    if count_avg_3d == 0 and count_today <= 1:
        mod, note = _PHASE_MODIFIERS["冷门"]
        return "冷门", mod, note

    # has_history=True 但无子句命中（今日相对 3 日基线走弱/持平，如 today=0 + avg∈(0,3)）：
    # 走弱 → 退潮默认（task 119）。"无历史"专指 has_history=False 数据缺失，不混用。
    mod, note = _PHASE_MODIFIERS["退潮"]
    return "退潮", mod, note


def analyze_sector_phase(date: str, industry: str) -> SectorPhase | None:
    """分析某板块在 date 的周期阶段。

    需要 T-1/T-2/T-3 的涨停股数。数据缺失标"无历史"。
    """
    # 取前 3 个交易日
    prev_dates = _get_prev_trading_dates(date, 3)
    if not prev_dates:
        return SectorPhase(
            industry=industry, count_today=0, count_avg_3d=0.0,
            momentum=0.0, phase="无历史", modifier=1.0, phase_note="无历史数据",
        )

    count_today = _get_zt_count_by_date_industry(date, industry)
    counts_prev = [_get_zt_count_by_date_industry(d, industry) for d in prev_dates]
    has_history = any(c > 0 for c in counts_prev)
    count_avg_3d = sum(counts_prev) / len(counts_prev) if counts_prev else 0.0
    momentum = count_today - count_avg_3d

    phase, modifier, note = classify_phase(count_today, count_avg_3d, has_history)
    stay_days = _sector_stay_days(date, industry)

    return SectorPhase(
        industry=industry, count_today=count_today, count_avg_3d=round(count_avg_3d, 2),
        momentum=round(momentum, 2), phase=phase, modifier=modifier, phase_note=note,
        stay_days=stay_days,
    )


def _get_prev_trading_dates(date: str, n: int) -> list[str]:
    """date 前 n 个有涨停数据的交易日（查 gene_scores 的 distinct date，自带节假日过滤；
    原简化版仅跳周末会误算节假日）。"""
    conn = sqlite3.connect(str(_DB))
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM gene_scores WHERE date < ? ORDER BY date DESC LIMIT ?",
            (date, n),
        ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _sector_stay_days(date: str, industry: str, max_lookback: int = 30) -> int:
    """task 118：连续在榜（≥1 涨停）交易日数（含 date）。

    "在榜"=当日该板块有 ≥1 涨停（出现在涨停榜）。停留天数=从 date 起向前连续在榜的交易日数；
    遇不在榜日即断。0=今日不在榜。2 查询：今日 count + 前 max_lookback 日在榜日期集。
    """
    if _get_zt_count_by_date_industry(date, industry) < 1:
        return 0  # 今日不在榜
    prev = _get_prev_trading_dates(date, max_lookback)
    if not prev:
        return 1  # 今日在榜但无历史日前置
    conn = sqlite3.connect(str(_DB))
    try:
        placeholders = ",".join("?" * len(prev))
        on_board = {
            r[0] for r in conn.execute(
                f"SELECT DISTINCT date FROM gene_scores WHERE industry=? AND date IN ({placeholders})",
                [industry, *prev],
            ).fetchall()
        }
    except Exception:
        on_board = set()
    finally:
        conn.close()
    streak = 1  # 今日
    for d in prev:  # 降序（最近在前）
        if d in on_board:
            streak += 1
        else:
            break
    return streak


def sector_strength_rank(date: str, sectors: list[dict]) -> list[dict]:
    """板块强度排名（spec §5.4.1）。

    sectors: [{industry, zt_count_today, zt_momentum, fund_flow}]
    返回按强度降序排序的 TOP-10 + 候选修饰系数。
    """
    def strength(s: dict) -> float:
        zt = s.get("zt_count_today", 0)
        mom = s.get("zt_momentum", 0)
        flow = s.get("fund_flow", 0)
        return zt * 0.40 + mom * 0.30 + (1 if flow > 0 else -1 if flow < 0 else 0) * 0.30

    ranked = sorted(sectors, key=strength, reverse=True)
    result = []
    for i, s in enumerate(ranked[:10]):
        if i < 3:
            mod = 1.05
        elif i < 10:
            mod = 1.0
        else:
            mod = 0.95
        result.append({**s, "rank": i + 1, "strength": round(strength(s), 2), "modifier": mod})
    return result


def detect_rotation(date_prev: str, date_curr: str, sectors_prev: list[dict], sectors_curr: list[dict]) -> list[dict]:
    """跨板块轮动检测（spec §5.4.3）。

    对比 T 日 vs T-1 日板块涨停数排名变化。上升 >= 5 位 = 启动候选，下降 >= 5 位 = 退潮。
    """
    def rank_map(sectors: list[dict]) -> dict[str, int]:
        ranked = sorted(sectors, key=lambda s: s.get("zt_count_today", 0), reverse=True)
        return {s["industry"]: i + 1 for i, s in enumerate(ranked)}

    prev_ranks = rank_map(sectors_prev)
    curr_ranks = rank_map(sectors_curr)

    rotations = []
    all_industries = set(prev_ranks.keys()) | set(curr_ranks.keys())
    for ind in all_industries:
        prev_r = prev_ranks.get(ind, 999)
        curr_r = curr_ranks.get(ind, 999)
        change = prev_r - curr_r  # 正=上升
        if abs(change) >= 5:
            rotations.append({
                "industry": ind,
                "prev_rank": prev_r if prev_r != 999 else None,
                "curr_rank": curr_r if curr_r != 999 else None,
                "change": change,
                "signal": "启动候选" if change >= 5 else "退潮",
            })
    return rotations


def sector_breadth(up_count: int, down_count: int) -> float:
    """板块广度（spec §5.4.4）。

    sector_breadth = up_count / (up_count + down_count)
    """
    total = up_count + down_count
    if total == 0:
        return 0.0
    return round(up_count / total, 4)


def aggregate_sectors(date: str) -> list[dict]:
    """聚合当日 all industries → sectors（§5.4.1/5.4.3 输入）。
    zt_count_today + zt_momentum 从 gene_scores；fund_flow 阻断降级 0（§44 数据阻断 push2his IP限流）。"""
    conn = sqlite3.connect(str(_DB))
    try:
        industries = [r[0] for r in conn.execute(
            "SELECT DISTINCT industry FROM gene_scores WHERE date = ? AND industry IS NOT NULL",
            (date,),
        ).fetchall()]
    except Exception:
        return []
    finally:
        conn.close()
    sectors: list[dict] = []
    for ind in industries:
        count_today = _get_zt_count_by_date_industry(date, ind)
        prev_dates = _get_prev_trading_dates(date, 3)
        count_avg_3d = sum(_get_zt_count_by_date_industry(d, ind) for d in prev_dates) / max(len(prev_dates), 1)
        sectors.append({
            "industry": ind,
            "zt_count_today": count_today,
            "zt_momentum": count_today - count_avg_3d,
            "fund_flow": 0,  # §44 数据阻断降级 0
        })
    return sectors


def sector_rotation(date: str) -> dict:
    """§5.4.1 板块强度排名 TOP10 + §5.4.3 跨板块轮动检测。
    纯 label（§5.4 Q2 方向被驳，不接策略分）；fund_flow 阻断降级 0。"""
    sectors_curr = aggregate_sectors(date)
    prev_dates = _get_prev_trading_dates(date, 1)
    prev_date = prev_dates[0] if prev_dates else None
    sectors_prev = aggregate_sectors(prev_date) if prev_date else []
    rank = sector_strength_rank(date, sectors_curr)
    rotation = detect_rotation(prev_date, date, sectors_prev, sectors_curr) if (prev_date and sectors_prev) else []
    return {
        "date": date,
        "strength_rank": rank,
        "rotation": rotation,
        "fund_flow_blocked": True,
        "note": "§5.4 纯 label 不接策略分（Q2 方向被驳）；fund_flow 阻断降级 0（§44）",
    }
