# -*- coding: utf-8 -*-
"""极端行情检测 —— 涨停潮/跌停潮动态阈值（客观数据，非行动建议）。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import astock
from vr_paths import is_trading_day

import logging
_logger = logging.getLogger(__name__)


@dataclass
class ExtremeMarketSignal:
    """极端行情信号。"""

    date: str
    signal_type: str          # 涨停潮 / 跌停潮 / 正常
    zt_count: int = 0         # 涨停家数
    dt_count: int = 0         # 跌停家数
    zb_count: int = 0         # 炸板家数
    total_attempts: int = 0   # 尝试涨停总数（涨停+炸板）
    zt_ratio: float = 0.0     # 涨停占比（相对尝试数）
    dt_ratio: float = 0.0     # 跌停占比（相对全市场）
    threshold_zt: float = 0.0 # 动态涨停阈值
    threshold_dt: float = 0.0 # 动态跌停阈值
    is_extreme: bool = False  # 是否极端行情
    interpretation: str = ""
    last_updated: str = ""
    data_status: str = "ok"   # ok | missing | degraded（数据诚实标记，对齐 sentiment_context:45；Tier-1 仅加字段，逻辑待 Tier-2）


# ===========================================================================
# 动态阈值计算
# ===========================================================================

def _compute_dynamic_thresholds(zt_history: list[int], dt_history: list[int]) -> tuple[float, float]:
    """基于历史数据计算动态阈值。

    使用均值 + 2倍标准差作为极端阈值。
    """
    import statistics

    # 涨停阈值
    if len(zt_history) >= 5:
        zt_mean = statistics.mean(zt_history)
        zt_stdev = statistics.stdev(zt_history) if len(zt_history) > 1 else 0
        threshold_zt = zt_mean + 2 * zt_stdev
    else:
        threshold_zt = 100.0  # 默认阈值

    # 跌停阈值
    if len(dt_history) >= 5:
        dt_mean = statistics.mean(dt_history)
        dt_stdev = statistics.stdev(dt_history) if len(dt_history) > 1 else 0
        threshold_dt = dt_mean + 2 * dt_stdev
    else:
        threshold_dt = 50.0  # 默认阈值

    return round(threshold_zt, 2), round(threshold_dt, 2)


def _interpret_extreme(signal_type: str, zt_count: int, dt_count: int, zt_ratio: float, dt_ratio: float) -> str:
    """生成极端行情解读。"""
    if signal_type == "涨停潮":
        return f"涨停潮：涨停{zt_count}家，占比{zt_ratio:.1%}，市场情绪极度亢奋"
    elif signal_type == "跌停潮":
        return f"跌停潮：跌停{dt_count}家，占比{dt_ratio:.1%}，市场情绪极度悲观"
    else:
        return "市场情绪正常，无明显极端行情"


def _resolve_pool_provenance(meta: dict[str, Any], pools_all_empty: bool) -> tuple[str, str]:
    """从 fallback meta 解析涨停池数据诚实状态 + last_updated（S112 R5，对齐 S111 R4）。

    - live fetch 成功（非空池）→ ('ok', now)：可判定极端行情
    - 命中陈旧缓存（meta.is_stale）→ ('degraded', 缓存时间戳)：不戳 now，不基于陈旧判定
    - 源断且缓存失效（空池兜底）→ ('missing', '')：不判"正常"，与真平静区分
    """
    if meta.get("is_stale"):
        cache_ts = meta.get("cache_ts")
        last_updated = datetime.fromtimestamp(cache_ts).isoformat() if cache_ts else ""
        return "degraded", last_updated
    if pools_all_empty:
        return "missing", ""
    return "ok", datetime.now().isoformat()


# ===========================================================================
# 主检测函数
# ===========================================================================

async def detect_extreme_market(date: str | None = None) -> ExtremeMarketSignal | None:
    """检测极端行情（涨停潮/跌停潮）。

    数据源：astock.em_zt_topic_pool() 东财涨停板行情中心。
    降级：东财故障时返回本地缓存或默认值。
    """
    try:
        import limitup_screener as ls

        # 解析日期
        if date:
            target_date = date.replace("-", "")
        else:
            target_date = await ls._resolve_date(None)

        display_date = f"{target_date[:4]}-{target_date[4:6]}-{target_date[6:8]}"

        # 交易日守卫：东财涨停池对非交易日请求静默回退到最近交易日数据（不报错），
        # 传入非交易日会拿错位数据。先用纯本地 is_trading_day 校验，非交易日直接走
        # 该函数既有的"无数据"降级路径（与东财故障时返回 None 一致）。
        try:
            _d = datetime.strptime(target_date, "%Y%m%d")
            if not is_trading_day(_d.date()):
                return None
        except ValueError:
            return None

        # 获取涨停池、跌停池、炸板池（带降级 + 诚实元数据，S112 R5）
        from fallback import get_with_fallback_meta
        cache_key = f"zt_pool:{target_date}"
        pool_data, meta = get_with_fallback_meta(
            cache_key,
            lambda: {
                "zt": astock.em_zt_topic_pool("getTopicZTPool", target_date, "fbt:asc"),
                "dt": astock.em_zt_topic_pool("getTopicDTPool", target_date, "fund:asc"),
                "zb": astock.em_zt_topic_pool("getTopicZBPool", target_date, "fbt:asc"),
            },
            ttl=600,  # 10 分钟缓存
            fallback_value={"zt": [], "dt": [], "zb": []},
        )

        zt_pool = pool_data.get("zt", [])
        dt_pool = pool_data.get("dt", [])
        zb_pool = pool_data.get("zb", [])

        zt_count = len(zt_pool)
        dt_count = len(dt_pool)
        zb_count = len(zb_pool)
        total_attempts = zt_count + zb_count

        # 计算占比
        zt_ratio = zt_count / total_attempts if total_attempts > 0 else 0.0
        dt_ratio = dt_count / (zt_count + dt_count + zb_count) if (zt_count + dt_count + zb_count) > 0 else 0.0

        # 数据诚实性：从 fallback meta 解析 status + last_updated（源断不戳 now，对齐 S111 R4）
        pools_all_empty = zt_count == 0 and dt_count == 0 and zb_count == 0
        data_status, last_updated = _resolve_pool_provenance(meta, pools_all_empty)

        # 源断（missing）→ 不判"正常"与真平静区分；陈旧（degraded）→ 不基于陈旧判极端
        if data_status == "missing":
            _logger.warning(
                "detect_extreme_market 涨停/跌停/炸板池源断且缓存失效 date=%s，标 missing 不判正常",
                display_date,
            )
            return ExtremeMarketSignal(
                date=display_date,
                signal_type="数据缺失",
                zt_count=0,
                dt_count=0,
                zb_count=0,
                total_attempts=0,
                zt_ratio=0.0,
                dt_ratio=0.0,
                threshold_zt=100.0,
                threshold_dt=50.0,
                is_extreme=False,
                interpretation="数据源断开，涨停/跌停/炸板池取数失败，无法判定极端行情（非'正常'平静市）",
                last_updated=last_updated,
                data_status=data_status,
            )
        if data_status == "degraded":
            _logger.warning(
                "detect_extreme_market 涨停/跌停/炸板池命中陈旧缓存 date=%s，标 degraded 不基于陈旧判定",
                display_date,
            )
            return ExtremeMarketSignal(
                date=display_date,
                signal_type="数据延迟",
                zt_count=zt_count,
                dt_count=dt_count,
                zb_count=zb_count,
                total_attempts=total_attempts,
                zt_ratio=round(zt_ratio, 4),
                dt_ratio=round(dt_ratio, 4),
                threshold_zt=100.0,
                threshold_dt=50.0,
                is_extreme=False,
                interpretation="涨停/跌停/炸板池取数失败，展示最近缓存数据（陈旧，非实时，不判定极端行情）",
                last_updated=last_updated,
                data_status=data_status,
            )

        # ok：live 数据，正常判定极端行情
        # 获取历史数据计算动态阈值（简化：用内存中的历史记录）
        # TODO: 接入历史涨停/跌停数据
        zt_history = [zt_count]  # 临时：实际应查询历史
        dt_history = [dt_count]
        threshold_zt, threshold_dt = _compute_dynamic_thresholds(zt_history, dt_history)

        signal_type = "正常"
        is_extreme = False
        if zt_count >= threshold_zt and zt_ratio >= 0.7:
            signal_type = "涨停潮"
            is_extreme = True
        elif dt_count >= threshold_dt and dt_ratio >= 0.3:
            signal_type = "跌停潮"
            is_extreme = True

        return ExtremeMarketSignal(
            date=display_date,
            signal_type=signal_type,
            zt_count=zt_count,
            dt_count=dt_count,
            zb_count=zb_count,
            total_attempts=total_attempts,
            zt_ratio=round(zt_ratio, 4),
            dt_ratio=round(dt_ratio, 4),
            threshold_zt=threshold_zt,
            threshold_dt=threshold_dt,
            is_extreme=is_extreme,
            interpretation=_interpret_extreme(signal_type, zt_count, dt_count, zt_ratio, dt_ratio),
            last_updated=last_updated,
            data_status=data_status,
        )

    except Exception as e:  # S094 audit/#6 over-correction fix: log + re-raise（不再吞→health except 接 ok=false；非交易日/无数据 None L101→ok=true 正确区分 no-signal vs broken）
        _logger.warning("detect_extreme_market 异常 date=%s: %s", date, e)
        raise


# ===========================================================================
# 缓存（简化版：内存缓存 5 分钟）
# ===========================================================================

_EXTREME_CACHE: dict[str, tuple[float, Any]] = {}
_EXTREME_TTL = 300  # 5 分钟


def _get_cached(key: str) -> Any | None:
    now = time.time()
    hit = _EXTREME_CACHE.get(key)
    if hit and now - hit[0] < _EXTREME_TTL:
        return hit[1]
    return None


def _set_cached(key: str, value: Any) -> None:
    _EXTREME_CACHE[key] = (time.time(), value)


async def get_extreme_market_signal(date: str | None = None) -> ExtremeMarketSignal | None:
    """获取极端行情信号（带缓存）。"""
    cache_key = f"extreme_market:{date or 'latest'}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    result = await detect_extreme_market(date)
    # S112 review fix：不缓存 missing 信号（对齐 sector_divergence 范式）——源断返
    # '数据缺失'时不入缓存，源恢复后下次调用立即重探（否则最长 _EXTREME_TTL 延迟
    # 再探测，盘中断源期假'平静'延迟暴露）。degraded 可缓存（陈旧计数仍有参考）。
    if result is not None and getattr(result, "data_status", "ok") != "missing":
        _set_cached(cache_key, result)
    return result
