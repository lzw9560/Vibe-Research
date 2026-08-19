# -*- coding: utf-8 -*-
"""S070 R7 分时派生 source（S084 R3/C3）。

优先读盘后预采集表 seal_derived_features（盘后权威批量，非进行中快照）；
表无则 fallback 实时算（get_snapshots_by_code + compute_derived_features），
仍无 snapshots → None 降级（不臆造）。data_status='missing' → None（与 S070 范式一致）。

grill Q2=B 修正：派生盘前取 T-1 昨日 snapshots（非今日）。
S084 follow-up：预采集表由 derived_results 合并入 seal_derived_features（接口不变）。
"""
from __future__ import annotations


def fetch_derived(code: str, yesterday_date: str) -> dict | None:
    """S070 R7 派生（盘前取 T-1 昨日 snapshots）。

    1. 读 seal_derived_features 预采集表（S084 C2/C3，盘后 executor 落库）——
       SELECT WHERE code=? AND date=?；命中即返（不实时算，选股池读预采集）。
       data_status='missing' → None（不透传空派生）。
    2. 表无 → fallback 实时算（战法层 B2 亦会自补）：调
       risk.seal_intraday_collector.get_snapshots_by_code(code, yesterday_date)
       → strategies.intraday_features.compute_derived_features(snapshots)。
       盘前 snapshots 未采集时返 None（标"分时数据未就绪"，不臆造）。
       data_status='degraded'（部分数据）允许透传；'missing'（空）→None。
    """
    # 1. 读预采集表
    try:
        from risk.seal_intraday_collector import get_derived_result
        cached = get_derived_result(code, yesterday_date)
    except Exception:
        cached = None
    if cached is not None:
        if cached.get("data_status") == "missing":
            return None
        return cached

    # 2. fallback：表无则实时算（不 per-code 阻塞；战法层 B2 亦会自补）
    try:
        from risk.seal_intraday_collector import get_snapshots_by_code
        from strategies.intraday_features import compute_derived_features
        snaps = get_snapshots_by_code(code, yesterday_date)
        if not snaps:
            return None  # 盘前未采集，降级
        derived = compute_derived_features(snaps)
        if derived.get("data_status") == "missing":
            return None
        return derived
    except Exception:
        return None
