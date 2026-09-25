#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T6.1+T6.2 实测：F3 融合整体 §44 event edge verdict + multifactor null 对账。

S201a 修复（2026-09-13）：cost 口径统一——逐笔调 accounting._cost_pct(entry_price, size, entry_date)
（保留 5元门 size-dependent 非 flatten），传真实 mean cost 作 round_trip_cost（materiality floor 缩放）。
旧 flat 0.2%（忽略 5元门散户乐观）→ 不可复现（-1.14% vs +0.36% 翻 verdict sign）。
修复后与 journal 同口径（_cost_pct 含 5元门×2/notional + 印花 + spread），诚实可复现。

S201b stage 2（2026-09-14）：出场乐观修复——recompute_gross_v2 重算 stop gap-through-aware
fill（旧硬编码 gross=float(stop_pct)=-4.0% → open<=stop→fill=open 更差, low<=stop→fill=stop*(1-eps),
一字跌停→carry）。take-side 不碰（limit sell 已 realistic）。1709/2888 stop exits 受影响。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s44_verifier import verify  # noqa: E402
from engine.trade_journal import TradeJournal  # noqa: E402
from tools.cost_sweep_s201b import recompute_gross_v2  # noqa: E402
from tools.f3_verdict import interpret_f3_verdict  # noqa: E402


def main() -> None:
    tj = TradeJournal()
    cases = tj.query_records(is_realized=1, is_dead_arm=0, limit=10000)

    # S201b stage 2: recompute gross with stop gap-through-aware fix
    recomputed = recompute_gross_v2(cases)
    returns: list[float] = []
    dates: list[str] = []
    costs: list[float] = []
    for gross_pct, cost_pct, entry_date in recomputed:
        costs.append(cost_pct)
        # net return = gross/100 - cost_pct/100（都转分数）
        returns.append(gross_pct / 100.0 - cost_pct / 100.0)
        dates.append(entry_date)

    mean_cost_pct = sum(costs) / len(costs) if costs else 0.0
    print(f"# F3 event edge: {len(returns)} 条融合 event（net 收益，逐笔 _cost_pct mean={mean_cost_pct:.3f}%）, {len(set(dates))} 唯一日", file=sys.stderr)
    if len(returns) < 30:
        print(f"# 样本不足（{len(returns)}<30），无法跑 §44", file=sys.stderr)
        return

    # S201a：传真实 mean cost 作 round_trip_cost（materiality floor 缩放，当前 0.0→floor 卡 min 0.003）
    v = verify(
        returns=returns,
        n_trials=1,
        edge_type="event",
        dates=dates,
        round_trip_cost=mean_cost_pct / 100.0,  # 转分数（0.015=1.5%），让 materiality floor 缩放
        frozen_commit="S194-F3-dev",
        n_comparisons=1,
    )

    em = getattr(v, "event_metrics", None)
    day_mean = getattr(em, "day_mean", None) if em else None
    interp = interpret_f3_verdict(
        status=v.status,
        event_status=getattr(v, "event_status", None),
        day_mean=day_mean,
        days_robust=v.days_robust,
        p_bh=getattr(v, "p_bh", None),
    )

    print(f"\n=== S194 F3 融合整体 §44 event edge（S201b stage2 stop fix 后）===")
    print(f"  status: {v.status}  event_status: {getattr(v, 'event_status', None)}")
    print(f"  day_mean: {day_mean}  days_robust: {v.days_robust}  p_bh: {getattr(v, 'p_bh', None)}")
    print(f"  n: {v.n}  n_effective(day-clustered): {getattr(v, 'n_effective', None)}")
    print(f"  round_trip_cost: {mean_cost_pct:.3f}%（逐笔 _cost_pct mean，size-dependent 5元门保留）")
    print(f"  cost range: {min(costs):.3f}% ~ {max(costs):.3f}%（size-dependent 非 flat）")
    print(f"\n  fusion_conclusion: {interp['fusion_conclusion']}")
    print(f"  null_engagement: {interp['null_engagement']}")
    print(f"\n  ⚠️ S201b stage2: stop gap-through-aware fill（1709/2888 stop exits 受影响）")
    print(f"  旧硬编码 gross=-4.0% → open<=stop→fill=open（更差），诚实修出场乐观")


if __name__ == "__main__":
    main()
