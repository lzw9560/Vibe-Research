# -*- coding: utf-8 -*-
"""S205 T4: 5 战法 match 逻辑（命中返 composite，不命中 None）。

5 战法：一字竞价（BLOCKER）/弱转强/N字反击/低吸龙头/形态反包。
调 pattern_scan_s205 compute_* 算 indicators → dragon_score composite。
命中 = composite > MATCH_THRESHOLD（0.3 先验，sweep 后不调 weight）。

DRY：复用 S203 dragon_score composite + S205 compute + DIMENSION_REGISTRY data_source。
"""
from __future__ import annotations

from typing import Any

from strategies.dragon_score import dragon_score
from strategies.s205_registry import get_s205_config
from strategies import pattern_scan_s205 as ps


MATCH_THRESHOLD: float = 0.3  # composite > 0.3 命中（0-100 scale → >30）


def _score(战法: str, indicators: dict[str, float]) -> float | None:
    """调 dragon_score 算 composite，>threshold 返 composite（0-100），否则 None。"""
    config = get_s205_config(战法)
    if config is None:
        return None
    composite = dragon_score(config, code="", trade_date="", indicators=indicators)
    if composite > MATCH_THRESHOLD * 100:
        return composite
    return None


# ── T4a: 一字竞价（BLOCKER: auction_signal 无免费源→返 None）──────────
def match_yizi_jingjia(
    code: str, date: str, bars: list[dict] | None = None, msc: dict | None = None, **kwargs: Any
) -> float | None:
    """一字竞价 match（BLOCKER：auction_signal 无免费源→返 None）。

    auction_signal 维度 data_source 是 BLOCKER（Tushare/hithink 付费，无免费历史竞价）。
    无 auction_signal → composite 必低（auction_signal weight=0.30 贡献 0）→ 不命中。
    标 BLOCKER skipif——返 None（不实现 match 逻辑）。
    """
    # BLOCKER: auction_signal 无源 → 跳过（不臆造竞价数据）
    return None


# ── T4b: 弱转强 ────────────────────────────────────────────────────
def match_ruozhuanqiang(
    code: str, date: str, bars: list[dict] | None = None, msc: dict | None = None, **kwargs: Any
) -> float | None:
    """弱转强 match：预期差反包 + 量能 + 情绪 + 技术 + 板块。"""
    indicators = {
        "expectation_gap_reversal": ps.compute_expectation_gap_reversal(code, date, bars=bars),
        "volume_confirm": _msc_volume_confirm(msc),
        "emotion_cycle": _msc_emotion(msc),
        "tech_pattern": _msc_tech(msc, bars),
        "sector_strength": _msc_sector(msc),
    }
    return _score("弱转强", indicators)


# ── T4c: N字反击 ──────────────────────────────────────────────────
def match_nzi_fanji(
    code: str, date: str, bars: list[dict] | None = None, msc: dict | None = None, **kwargs: Any
) -> float | None:
    """N字反击 match：量能节奏 + 回调结构 + 技术 + 情绪 + 板块。"""
    indicators = {
        "volume_rhythm": ps.compute_volume_rhythm(bars=bars),
        "pullback_structure": ps.compute_pullback(bars=bars),
        "tech_pattern": _msc_tech(msc, bars),
        "emotion_cycle": _msc_emotion(msc),
        "sector_strength": _msc_sector(msc),
    }
    return _score("N字反击", indicators)


# ── T4d: 低吸龙头 ─────────────────────────────────────────────────
def match_dixi_longtou(
    code: str, date: str, bars: list[dict] | None = None, msc: dict | None = None, **kwargs: Any
) -> float | None:
    """低吸龙头 match：技术 + 龙头确认 + 回调节奏 + 量能反转 + 情绪 + 板块改口径。"""
    sector_rank = msc.get("sector_rank") if msc else None
    lbc = msc.get("lbc") if msc else None
    high_gene = msc.get("high_gene") if msc else None
    indicators = {
        "tech_pattern": _msc_tech(msc, bars),
        "leader_identity": ps.compute_leader_identity(
            sector_rank=sector_rank, lbc=lbc, high_gene=high_gene,
        ),
        "pullback_rhythm": ps.compute_pullback_rhythm(
            days_since_last_zt=msc.get("days_since_last_zt") if msc else None,
            pullback_pct=msc.get("pullback_pct") if msc else None,
            is_first_pullback=msc.get("is_first_pullback") if msc else None,
        ),
        "volume_reversal": _msc_volume_reversal(msc, bars),
        "emotion_cycle": _msc_emotion(msc),
        "sector_strength_alt": _msc_sector_alt(msc),
    }
    return _score("低吸龙头", indicators)


# ── T4e: 形态反包 ─────────────────────────────────────────────────
def match_xingtai_fanbao(
    code: str, date: str, bars: list[dict] | None = None, msc: dict | None = None, **kwargs: Any
) -> float | None:
    """形态反包 match：技术 + 量能 + 反包确认 + 情绪 + 板块。"""
    indicators = {
        "tech_pattern": _msc_tech(msc, bars),
        "volume_confirm": _msc_volume_confirm(msc),
        "reversal_confirm": ps.compute_reversal_confirm(bars=bars),
        "emotion_cycle": _msc_emotion(msc),
        "sector_strength": _msc_sector(msc),
    }
    return _score("形态反包", indicators)


# ── msc helpers（读 market_scan_ctx / 涨停池 raw 指标，缺数据→0.0）──
def _msc_volume_confirm(msc: dict | None) -> float:
    if not msc:
        return 0.0
    return ps._clip01(msc.get("volume_breakout_ratio", 0.0) / 2.0)


def _msc_emotion(msc: dict | None) -> float:
    if not msc:
        return 0.0
    return ps._clip01(msc.get("sti_score", 0.0) / 100.0)


def _msc_tech(msc: dict | None, bars: list[dict] | None = None) -> float:
    if not msc:
        return 0.0
    return ps._clip01(msc.get("tech_score", 0.0))


def _msc_sector(msc: dict | None) -> float:
    if not msc:
        return 0.0
    zt = msc.get("zt_count_today", 0.0)
    return ps._clip01(zt / 5.0 if zt else 0.0)


def _msc_sector_alt(msc: dict | None) -> float:
    if not msc:
        return 0.0
    rank = msc.get("sector_rank")
    if rank is None:
        return 0.0
    return ps._clip01(1.0 - (rank - 1) / 5.0) if rank >= 1 else 0.0


def _msc_volume_reversal(msc: dict | None, bars: list[dict] | None = None) -> float:
    if not msc:
        return 0.0
    return ps._clip01(msc.get("volume_reversal_ratio", 0.0) / 2.0)


__all__ = [
    "MATCH_THRESHOLD",
    "match_yizi_jingjia",
    "match_ruozhuanqiang",
    "match_nzi_fanji",
    "match_dixi_longtou",
    "match_xingtai_fanbao",
]
