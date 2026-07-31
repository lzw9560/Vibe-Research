# -*- coding: utf-8 -*-
"""板块情绪分化度 —— 板块内部分化 + 轮动速度监控（客观数据，非行动建议）。"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

import astock
from data.mappers import industry_sector_from_dict


@dataclass
class SectorDivergence:
    """板块情绪分化度。"""

    sector: str
    date: str
    divergence_score: float = 0.0          # 分化度 (0-100)，越高分化越严重
    rotation_speed: float = 0.0            # 轮动速度 (0-100)，越高轮动越快
    up_count: int = 0
    down_count: int = 0
    avg_change_pct: float = 0.0
    std_change_pct: float = 0.0            # 板块内涨跌幅标准差
    leader_code: str = ""
    leader_name: str = ""
    leader_change_pct: float = 0.0
    interpretation: str = ""
    last_updated: str = ""


@dataclass
class SectorRotation:
    """板块轮动快照。"""

    date: str
    sectors: list[dict] = field(default_factory=list)
    rotation_speed: float = 0.0
    hot_sectors: list[str] = field(default_factory=list)
    cold_sectors: list[str] = field(default_factory=list)
    interpretation: str = ""
    last_updated: str = ""


# ===========================================================================
# 板块分化度计算
# ===========================================================================

def _compute_divergence_score(std_change: float, up_ratio: float) -> float:
    """计算分化度评分 (0-100)。"""
    # 标准差越高 + 涨跌比越接近 1:1 → 分化越严重
    std_component = min(std_change / 3.0, 1.0) * 50  # 3% 标准差视为满分
    balance_component = (1.0 - abs(up_ratio - 0.5) * 2) * 50  # 涨跌比越平衡分化越严重
    return round(std_component + balance_component, 2)


def _compute_rotation_speed(current_ranking: list, prev_ranking: list) -> float:
    """计算板块轮动速度 (0-100)。"""
    if not current_ranking or not prev_ranking:
        return 0.0

    # 构建名称→排名字典
    curr_ranks = {s.name: i for i, s in enumerate(current_ranking)}
    prev_ranks = {s.name: i for i, s in enumerate(prev_ranking)}

    common = set(curr_ranks.keys()) & set(prev_ranks.keys())
    if not common:
        return 0.0

    # 计算排名变化绝对值的平均值
    rank_changes = [abs(curr_ranks[name] - prev_ranks[name]) for name in common]
    avg_change = sum(rank_changes) / len(rank_changes)

    # 归一化到 0-100（假设最大平均变化为 20 名）
    return round(min(avg_change / 20.0, 1.0) * 100, 2)


def _interpret_divergence(divergence_score: float, rotation_speed: float) -> str:
    """生成分化度解读。"""
    if divergence_score >= 70:
        return "板块内部分化严重，个股表现差异大，需精选标的"
    elif divergence_score >= 50:
        return "板块内部分化明显，龙头与跟风股差距拉大"
    elif divergence_score >= 30:
        return "板块内部分化一般，整体方向尚可"
    else:
        return "板块内部分化较小，个股表现相对同步"


def _interpret_rotation(rotation_speed: float) -> str:
    """生成轮动速度解读。"""
    if rotation_speed >= 70:
        return "板块轮动极快，热点切换频繁，追高风险大"
    elif rotation_speed >= 50:
        return "板块轮动较快，热点持续性一般"
    elif rotation_speed >= 30:
        return "板块轮动适中，热点有一定持续性"
    else:
        return "板块轮动缓慢，热点集中且稳定"


# ===========================================================================
# 主计算函数
# ===========================================================================

async def calculate_sector_divergence(date: str | None = None) -> list[SectorDivergence]:
    """计算全市场板块分化度。

    数据源：astock.industry_comparison() 东财行业板块涨跌幅。
    降级：东财故障时返回本地缓存。
    """
    try:
        from datetime import datetime, timedelta
        import limitup_screener as ls

        # 解析日期
        if date:
            target_date = date.replace("-", "")
        else:
            target_date = await ls._resolve_date(None)

        display_date = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"

        # 获取行业板块数据（带降级）
        from fallback import get_with_fallback
        cache_key = f"industry_comparison:{target_date}"
        sector_data = get_with_fallback(
            cache_key,
            lambda: astock.industry_comparison(top_n=100),
            ttl=600,  # 10 分钟缓存
            fallback_value={"top": [], "bottom": []},
        )
        sectors = [industry_sector_from_dict(s) for s in (sector_data.get("top", []) + sector_data.get("bottom", []))]
        if not sectors:
            return []

        # 计算每个板块的分化度
        results = []
        for sector in sectors:
            name = sector.name
            change_pct = sector.change_pct or 0
            up_count = sector.up_count or 0
            down_count = sector.down_count or 0
            total = up_count + down_count

            # 简化：用涨跌家数比 + 涨跌幅估算板块内标准差
            up_ratio = up_count / total if total > 0 else 0.5
            # 估算标准差：涨跌家数越均衡，标准差越大
            balance_factor = 1.0 - abs(up_ratio - 0.5) * 2  # 0(极端) ~ 1(均衡)
            std_estimate = abs(change_pct) * (0.5 + balance_factor * 0.5) if change_pct else 0.0

            divergence_score = _compute_divergence_score(std_estimate, up_ratio)

            results.append(SectorDivergence(
                sector=name,
                date=display_date,
                divergence_score=divergence_score,
                up_count=up_count,
                down_count=down_count,
                avg_change_pct=round(change_pct, 2),
                std_change_pct=round(std_estimate, 2),
                interpretation=_interpret_divergence(divergence_score, 0.0),
                last_updated=datetime.now().isoformat(),
            ))

        # 按分化度降序
        results.sort(key=lambda x: x.divergence_score, reverse=True)
        return results

    except Exception:
        return []


async def calculate_sector_rotation(date: str | None = None) -> SectorRotation | None:
    """计算板块轮动速度。

    对比最近 2 个交易日的行业板块排名变化。
    降级：东财故障时返回本地缓存。
    """
    try:
        from datetime import datetime, timedelta
        import limitup_screener as ls

        # 解析日期
        if date:
            target_date = date.replace("-", "")
        else:
            target_date = await ls._resolve_date(None)

        display_date = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"

        # 获取当日板块排名（带降级）
        from fallback import get_with_fallback
        cache_key = f"industry_comparison:{target_date}"
        today_data = get_with_fallback(
            cache_key,
            lambda: astock.industry_comparison(top_n=100),
            ttl=600,  # 10 分钟缓存
            fallback_value={"top": [], "bottom": []},
        )
        today_sectors = [industry_sector_from_dict(s) for s in (today_data.get("top", []) + today_data.get("bottom", []))]
        if not today_sectors:
            return None

        # 获取前一日板块排名（简化：用同一天数据模拟，实际应查询历史）
        # TODO: 接入历史板块排名数据
        prev_sectors = today_sectors.copy()  # 临时：实际应查询前一交易日

        rotation_speed = _compute_rotation_speed(today_sectors, prev_sectors)

        # 识别热点/冷门板块
        hot = [s.name for s in today_sectors[:5] if (s.change_pct or 0) > 0]
        cold = [s.name for s in today_sectors[-5:] if (s.change_pct or 0) < 0]

        return SectorRotation(
            date=display_date,
            sectors=[s.model_dump() for s in today_sectors[:20]],  # 只保留前 20
            rotation_speed=rotation_speed,
            hot_sectors=hot,
            cold_sectors=cold,
            interpretation=_interpret_rotation(rotation_speed),
            last_updated=datetime.now().isoformat(),
        )

    except Exception:
        return None


# ===========================================================================
# 缓存（简化版：内存缓存 10 分钟）
# ===========================================================================

_DIVERGENCE_CACHE: dict[str, tuple[float, Any]] = {}
_DIVERGENCE_TTL = 600  # 10 分钟


def _get_cached(key: str) -> Any | None:
    now = time.time()
    hit = _DIVERGENCE_CACHE.get(key)
    if hit and now - hit[0] < _DIVERGENCE_TTL:
        return hit[1]
    return None


def _set_cached(key: str, value: Any) -> None:
    _DIVERGENCE_CACHE[key] = (time.time(), value)


async def get_sector_divergence(date: str | None = None) -> list[SectorDivergence] | None:
    """获取板块分化度（带缓存）。"""
    cache_key = f"sector_divergence:{date or 'latest'}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result = await calculate_sector_divergence(date)
    _set_cached(cache_key, result)
    return result


async def get_sector_rotation(date: str | None = None) -> SectorRotation | None:
    """获取板块轮动（带缓存）。"""
    cache_key = f"sector_rotation:{date or 'latest'}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result = await calculate_sector_rotation(date)
    _set_cached(cache_key, result)
    return result


async def get_sector_divergence_history(days: int = 30) -> list[dict]:
    """获取板块分化度历史趋势。

    计算最近 N 个交易日的分化度数据。
    降级：计算失败时返回已缓存的历史数据或空列表。
    """
    try:
        import limitup_screener as ls
        from datetime import datetime, timedelta

        history: list[dict] = []
        # 获取最近 N 个交易日（简化：按自然日回溯，实际应使用交易日历）
        # 这里用缓存避免重复计算
        cache_key = f"sector_divergence_history:{days}"
        cached = _get_cached(cache_key)
        if cached is not None:
            return cached

        # 计算最近 N 天的分化度（最多 10 天，避免过多 API 调用）
        max_compute = min(days, 10)
        for i in range(max_compute):
            try:
                # 回溯 i 天
                target_date = (datetime.now() - timedelta(days=i)).strftime("%Y%m%d")
                display_date = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"
                
                # 尝试获取该日期的分化度
                result = await get_sector_divergence(target_date)
                if result:
                    avg_divergence = sum(r.divergence_score for r in result) / len(result)
                    avg_rotation = sum(r.rotation_speed for r in result) / len(result) if result else 0.0
                    interpretation = _interpret_divergence(avg_divergence)
                    history.append({
                        "date": display_date,
                        "divergence_score": round(avg_divergence, 2),
                        "rotation_speed": round(avg_rotation, 2),
                        "interpretation": interpretation,
                    })
            except Exception:
                continue

        # 按日期升序
        history.sort(key=lambda x: x["date"])
        _set_cached(cache_key, history)
        return history

    except Exception:
        return []
