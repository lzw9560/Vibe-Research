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

    # S084 R4.2：板块资金 3 字段（行业级，fund source 从 market.get_overview()['sectors'] 匹配）
    ind.sector_net_inflow = f.get("sector_net_inflow")
    ind.sector_inflow = f.get("sector_inflow")
    ind.sector_outflow = f.get("sector_outflow")

    # S057：流通市值——activity source 已取（tencent_quote.float_cap），塞入 IndicatorSet
    ind.float_market_cap = a.get("float_market_cap")

    # S081：PRD 2 战法因子（activity source 从 K线扩展算，塞入 IndicatorSet 消除 match_strategies 重复取数）
    ind.max_high_pct = a.get("max_high_pct")
    ind.shadow_length_pct = a.get("shadow_length_pct")
    ind.ma_5_status = a.get("ma_5_status")
    ind.prev_turnover_pct = a.get("prev_turnover_pct")

    # S084 R4.1/R4.3：tencent_quote 扩展 + 前日成交额（activity source，按历史日路径分字段）
    ind.last_close = a.get("last_close")
    ind.open = a.get("open")
    ind.change_amt = a.get("change_amt")
    ind.pe_ttm = a.get("pe_ttm")
    ind.mcap_yi = a.get("mcap_yi")
    ind.pb = a.get("pb")
    ind.prev_amount_yi = a.get("prev_amount_yi")

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
    gene_obj: Any = None,           # S084 R1：GeneScore 完整对象（model_dump 塞 card.gene_score）
    pool_item: dict | None = None,  # S084 R2：涨停池原始 dict
    derived: dict | None = None,    # S084 R3：S070 R7 分时派生
    trade_date: str | None = None,  # S085 B2：T-1 交易日（龙虎榜盘后数据，供席位聚合取数）
    with_seat_detail: bool = False,  # S085 B2：席位聚合 opt-in（bulk 漏斗默认关，单股 diagnose 开）
) -> DiagnosisCard:
    """聚合 → DiagnosisCard（AC4）。risk_flags 为客观标注（AC8/§8 极端估值）。

    S057：增八项标准三态判定（check_eight_standards），结果挂入 eight_standards 字段；
    未过数≥3 标 capped=True + cap_reason（封顶阈值在 funnel.py 消费侧实施）。
    S084：增 3 子对象（gene_score/pool_item/derived），各默认 None 降级不臆造。
    S085 B2：增 seat_detail 聚合子对象（buy_one_ratio + 席位类型聚合 + score_modifier）。
    合规 S018 R11：seat_detail 只放聚合分类，不放个体席位名/花名。无龙虎榜→None 降级不臆造。
    性能：seat_detail 取数 per-code 调 compute_consensus_signal（3 次 datacenter/code），
    bulk 漏斗（run_funnel_impl，N 候选）默认 with_seat_detail=False 跳过（避免 N×datacenter 拖垮响应）；
    单股 diagnose() 开 with_seat_detail=True（1 code，开销可接受）。
    """
    activity = assess_activity(ind, eff)
    stabilization = detect_stabilization(ind, market_ctx)
    risk_flags: list[str] = []
    # S085 A1：seal_amount 接线——zt pool 的 fund(封单额，元) 透到 ind.seal_amount，
    # 否则八项标准⑥(_check_seal_ratio) 恒 missing → fail_count 偏置 → capped 判定偏（选股池得分封顶 55）。
    # 命名碰撞守护：用 pool_item.get("fund")（封单额）非 build_indicator_set 的 fund 参数（资金流 dict）。
    # 单位：fund 元 + float_market_cap 元 → ratio 无量纲（见 eight_standards._check_seal_ratio）。
    # 非涨停股 pool_item=None → 不注入 → seal_amount=None → ⑥ missing（正确，⑥仅对涨停股有意义）。
    if pool_item:
        _fund = pool_item.get("fund")
        if _fund not in (None, "", "-"):
            try:
                ind.seal_amount = float(_fund)
            except (TypeError, ValueError):
                ind.seal_amount = None
    # S088 grill Q4：八项 ④⑤ 补全。market_ctx(=board) 只有 lianban_stocks 无 fbt/zbc，
    # ④ first_seal_time / ⑤ open_count 恒 missing。从 pool_item 注入到 per-card ctx 拷贝
    # （board 在 run_funnel 全 N 卡复用，直接赋值会泄漏上一只票数据）。
    eight_ctx = dict(market_ctx or {})
    if pool_item:
        from strategies.first_board_filter import _fbt_to_hhmm, _to_float  # noqa: PLC0415 — 复用，zt_pool_source 已有跨包先例
        fbt = pool_item.get("fbt")
        if fbt is not None:
            hhmm = _fbt_to_hhmm(fbt)  # _time_within 无法解析 5 位 fbt(92500→h=925 恒 fail)，须转 HH:MM
            if hhmm is not None:
                eight_ctx["first_seal_time"] = hhmm
        zbc_raw = pool_item.get("zbc")
        if zbc_raw is not None:
            zbc = _to_float(zbc_raw)  # coerce：_check_reopens r<=MAX 若 r 是 str 会 TypeError
            if zbc is not None:
                eight_ctx["open_count"] = int(zbc)
    eight = check_eight_standards(ind, eight_ctx)
    capped = eight.fail_count >= 3
    cap_reason = (
        f"八项标准未过{eight.fail_count}项，得分封顶{_CAP_THRESHOLD}"
        if capped else None
    )
    # S084 R1：gene_obj → model_dump(mode='json')；非 pydantic 对象（如 mock）防御性跳过
    gene_score = (
        gene_obj.model_dump(mode="json")
        if gene_obj is not None and hasattr(gene_obj, "model_dump")
        else None
    )
    # S085 B2：席位聚合 opt-in——bulk 漏斗跳过（perf），单股 diagnose 开
    seat_detail = _build_seat_detail(code, trade_date) if with_seat_detail else None
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
        gene_score=gene_score,
        pool_item=pool_item,
        derived=derived,
        seat_detail=seat_detail,
    )


def _build_seat_detail(code: str, trade_date: str | None) -> dict | None:
    """从 seat_engine + hot_money_seats 取席位聚合信号 → seat_detail 子对象。

    聚合 only（守 S018 R11）：buy_one_ratio + 席位类型聚合列表 + score_modifier/risk_label。
    不放个体席位名/营业部名。无 trade_date / 无龙虎榜 / 取数异常 → None 降级（不臆造）。
    承重：seat_detail 不参与 capped/胜率/结算，仅选股池呈现（见 核实报告.md B2）。
    """
    if not trade_date:
        return None
    try:
        from seat_engine.service import get_engine
        engine = get_engine()
        consensus = engine.compute_consensus_signal(trade_date, code)
    except Exception:
        return None
    if not consensus or not consensus.get("details"):
        return None
    details = consensus["details"]
    # score_modifier（画像未建→modifier 1.0 降级，hot_money_seats 既有逻辑）
    score_modifier = None
    risk_label = None
    try:
        from strategies.hot_money_seats import compute_seat_risk_factor
        seat_risk = compute_seat_risk_factor(code, trade_date)
        if seat_risk is not None:
            score_modifier = seat_risk.score_modifier
            risk_label = seat_risk.risk_label
    except Exception:
        pass
    return {
        "buy_one_ratio": details.get("buy_one_ratio"),
        "buy_seat_types": details.get("buy_seat_types") or [],
        "sell_seat_types": details.get("sell_seat_types") or [],
        "consensus_signal": consensus.get("signal"),
        "score_modifier": score_modifier,
        "risk_label": risk_label,
        "data_status": "ok" if details.get("buy_one_ratio") is not None else "partial",
    }


from candidate_funnel.thresholds import EIGHT_STANDARD_CAP_THRESHOLD as _CAP_THRESHOLD  # noqa: E402, I001
