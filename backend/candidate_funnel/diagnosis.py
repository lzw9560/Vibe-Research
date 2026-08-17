# -*- coding: utf-8 -*-
"""诊断卡聚合（S002 阶段 C）。

assess_activity: 规则可复现的活跃度分档（spec §5.2）。
build_diagnosis_card: 聚合六类指标 → DiagnosisCard（AC4）；missing 透明（AC6）。
合规：不含方向结论词（AC10）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from candidate_funnel.models import (
    ActivityAssessment,
    ActivityTier,
    Announcement,
    BaseThreshold,
    DiagnosisCard,
    EightStandardResult,
    IndicatorSet,
    StabilizationSignals,
)
from candidate_funnel.eight_standards import check_eight_standards


def assess_activity(ind: IndicatorSet, eff: BaseThreshold) -> ActivityAssessment:
    """规则可复现的活跃度分档（换手/量比/成交额/振幅），不引入方向判断。

    同输入两次结果一致（AC5）。rules_applied 记命中规则。
    """
    rules: list[str] = []
    t = ind.turnover_pct
    if t is None:
        tier = ActivityTier.COLD
        rules.append("换手未取得")
    elif t >= eff.turnover_hot:
        tier = ActivityTier.HOT
        rules.append(f"换手>={eff.turnover_hot}%")
    elif t >= eff.turnover_cold:
        tier = ActivityTier.ACTIVE
        rules.append(f"换手>={eff.turnover_cold}%")
    else:
        tier = ActivityTier.COLD
        rules.append(f"换手<{eff.turnover_cold}%")

    if ind.vol_ratio is not None and ind.vol_ratio >= eff.vol_ratio_active:
        rules.append(f"量比>={eff.vol_ratio_active}")
    if ind.amount_yi is not None and ind.amount_yi >= eff.amount_yi_min:
        rules.append(f"成交额>={eff.amount_yi_min}亿")
    if ind.amplitude_pct is not None and ind.amplitude_pct >= eff.amplitude_high:
        rules.append(f"振幅>={eff.amplitude_high}%")

    return ActivityAssessment(tier=tier, rules_applied=rules)


def detect_stabilization(ind: IndicatorSet, market_ctx: dict | None) -> StabilizationSignals:
    """企稳四信号命中判定（C2），evidence 记依据。

    market_ctx 约定字段（市场级，任一缺失则对应信号为 None）：
      dt_count/prev_dt_count、volume/prev_volume、main_flow/prev_main_flow、
      max_boards/prev_max_boards。
    """
    ctx = market_ctx or {}
    evidence: dict[str, str] = {}
    s = StabilizationSignals()

    # 跌停家数减少
    dt, prev_dt = ctx.get("dt_count"), ctx.get("prev_dt_count")
    if dt is not None and prev_dt is not None:
        s.fewer_limit_downs = dt < prev_dt
        evidence["fewer_limit_downs"] = f"跌停 {dt} < 前值 {prev_dt}"
    else:
        evidence["fewer_limit_downs"] = "跌停序列未取得"

    # 量能止跌（不再下降）
    vol, prev_vol = ctx.get("volume"), ctx.get("prev_volume")
    if vol is not None and prev_vol is not None:
        s.volume_stop_falling = vol >= prev_vol
        evidence["volume_stop_falling"] = f"量能 {vol} >= 前值 {prev_vol}"
    else:
        evidence["volume_stop_falling"] = "量能序列未取得"

    # 主力净流转正
    mf, prev_mf = ctx.get("main_flow"), ctx.get("prev_main_flow")
    if mf is not None and prev_mf is not None:
        s.main_flow_turning_positive = mf > 0 and prev_mf <= 0
        evidence["main_flow_turning_positive"] = f"主力 {mf}，前值 {prev_mf}"
    else:
        evidence["main_flow_turning_positive"] = "主力净流序列未取得"

    # 连板高度上升
    mb, prev_mb = ctx.get("max_boards"), ctx.get("prev_max_boards")
    if mb is not None and prev_mb is not None:
        s.board_height_rising = mb > prev_mb
        evidence["board_height_rising"] = f"最高连板 {mb} > 前值 {prev_mb}"
    else:
        evidence["board_height_rising"] = "连板高度序列未取得"

    s.evidence = evidence
    return s


def build_indicator_set(
    code: str,
    name: str,
    genes: dict[str, dict],
    activity: dict[str, dict],
    fund: dict[str, dict],
    auction: dict[str, dict],
    catalyst: dict[str, dict],
    board: dict,
) -> IndicatorSet:
    """合并各 source 片段 → IndicatorSet；取不到的字段留 None 并记入 missing（AC6）。"""
    ind = IndicatorSet(code=code, name=name)
    a = activity.get(code, {})
    ind.price = a.get("price")
    ind.change_pct = a.get("change_pct")
    ind.turnover_pct = a.get("turnover_pct")
    ind.vol_ratio = a.get("vol_ratio")
    ind.amount_yi = a.get("amount_yi")
    ind.amplitude_pct = a.get("amplitude_pct")
    ind.limit_up = a.get("limit_up")
    ind.limit_down = a.get("limit_down")

    f = fund.get(code, {})
    ind.main_net_inflow = f.get("main_net_inflow")
    ind.main_net_5d = f.get("main_net_5d")
    ind.dragon_tiger_inst_net = f.get("dragon_tiger_inst_net")
    ind.dragon_tiger_hot_money_relay = f.get("dragon_tiger_hot_money_relay")
    ind.northbound = f.get("northbound")

    # S057：流通市值——activity source 已取（tencent_quote.float_cap），塞入 IndicatorSet
    ind.float_market_cap = a.get("float_market_cap")

    au = auction.get(code, {})
    ind.auction_open_pct = au.get("auction_open_pct")

    ca = catalyst.get(code, {})
    ind.concepts = ca.get("concepts") or []
    ind.sector_flow = ca.get("sector_flow")
    anns = ca.get("announcements") or []
    ind.announcements = [
        Announcement(**x) if isinstance(x, dict) else x for x in anns
    ]

    for s in (board or {}).get("lianban_stocks", []):
        if isinstance(s, dict) and s.get("code") == code:
            ind.consec_boards = s.get("boards")
            break

    for src in (a, f, au, ca):
        m = (src or {}).get("missing")
        if isinstance(m, dict):
            ind.missing.update(m)
    # S073 盘前因子"最后评估"：MA/BOLL 补算 from baostock kline cache
    # （§44 未验证因子，接入评估层不硬过滤；数据缺标 missing）
    try:
        import json as _json
        from vr_paths import resolve_data_dir as _resolve_data_dir
        _kc = _resolve_data_dir() / "baostock_kline_cache.json"
        if _kc.exists():
            _cache = _json.loads(_kc.read_bytes())
            _bars = _cache.get(code, [])
            _closes = [b.get("close", 0) for b in _bars if b.get("close")]
            if len(_closes) >= 20:
                ind.ma5 = round(sum(_closes[-5:]) / 5, 3)
                ind.ma10 = round(sum(_closes[-10:]) / 10, 3)
                ind.ma20 = round(sum(_closes[-20:]) / 20, 3)
                _last20 = _closes[-20:]
                _mean = sum(_last20) / 20
                _var = sum((x - _mean) ** 2 for x in _last20) / 20
                _std = _var ** 0.5
                ind.boll_upper = round(_mean + 2 * _std, 3)
                ind.boll_lower = round(_mean - 2 * _std, 3)
            elif len(_closes) >= 5:
                ind.ma5 = round(sum(_closes[-5:]) / 5, 3)
            # <5 不填（数据不足）
        else:
            ind.missing["ma_boll"] = "kline cache 未取得"
    except Exception:
        ind.missing["ma_boll"] = "MA/BOLL 计算失败"
    return ind


def build_diagnosis_card(
    code: str,
    name: str,
    ind: IndicatorSet,
    eff: BaseThreshold,
    market_ctx: dict | None = None,
    as_of: datetime | None = None,
) -> DiagnosisCard:
    """聚合 → DiagnosisCard（AC4）。risk_flags 为客观标注（AC8/§8 极端估值）。

    S057：增八项标准三态判定（check_eight_standards），结果挂入 eight_standards 字段；
    未过数≥3 标 capped=True + cap_reason（封顶阈值在 funnel.py 消费侧实施）。
    """
    activity = assess_activity(ind, eff)
    stabilization = detect_stabilization(ind, market_ctx)
    risk_flags: list[str] = []
    eight = check_eight_standards(ind, market_ctx)
    capped = eight.fail_count >= 3
    cap_reason = (
        f"八项标准未过{eight.fail_count}项，得分封顶{_CAP_THRESHOLD}"
        if capped else None
    )
    return DiagnosisCard(
        code=code,
        name=name,
        indicators=ind,
        activity=activity,
        stabilization=stabilization,
        risk_flags=risk_flags,
        as_of=as_of or datetime.now(),
        eight_standards=eight,
        capped=capped,
        cap_reason=cap_reason,
    )


from candidate_funnel.thresholds import EIGHT_STANDARD_CAP_THRESHOLD as _CAP_THRESHOLD  # noqa: E402, I001
