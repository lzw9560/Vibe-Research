#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T6.1+T6.2 实测：F3 融合整体 §44 event edge verdict + multifactor null 对账。

S201a 修复（2026-09-13）：cost 口径统一——逐笔调 accounting._cost_pct(entry_price, size, entry_date)
（保留 5元门 size-dependent 非 flatten），传真实 mean cost 作 round_trip_cost（materiality floor 缩放）。
旧 flat 0.2%（忽略 5元门散户乐观）→ 不可复现（-1.14% vs +0.36% 翻 verdict sign）。
修复后与 journal 同口径（_cost_pct 含 5元门×2/notional + 印花 + spread），诚实可复现。

用 s44_verifier.verify(edge_type='event')：
- returns = 1092 条交易的 net 收益（gross - 逐笔 _cost_pct）；
- dates = entry_date（per-pick 对齐——day-clustered n 非 pooled）；
- edge_type='event'（不用 selection——spec grill CRITICAL#2 survivors 不可复现）；
- pass 门 = status=='robust_edge'。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s44_verifier import verify  # noqa: E402
from engine.trade_journal import TradeJournal  # noqa: E402
from engine.accounting import _cost_pct  # noqa: E402
from strategies.journal_recorder import DEFAULT_SIZE  # noqa: E402
from tools.f3_verdict import interpret_f3_verdict  # noqa: E402


def main() -> None:
    tj = TradeJournal()
    cases = tj.query_records(is_realized=1, is_dead_arm=0, limit=10000)

    # S201a：逐笔调 accounting._cost_pct（保留 5元门 size-dependent，非 flat）
    # gross_return 是百分数如 4.0=4%，÷100 转分数，减 逐笔成本/100（成本也是百分数）
    returns: list[float] = []
    dates: list[str] = []
    costs: list[float] = []
    for rec in cases:
        gr = rec.gross_return
        if gr is None:
            continue
        # 逐笔成本（entry_price + DEFAULT_SIZE=100 + entry_date）
        entry_price = float(rec.entry_price) if rec.entry_price else 0.0
        cost_pct = _cost_pct(entry_price, DEFAULT_SIZE, rec.entry_date)
        costs.append(cost_pct)
        # net return = gross/100 - cost_pct/100（都转分数）
        returns.append(float(gr) / 100.0 - cost_pct / 100.0)
        dates.append(rec.entry_date)

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

    print(f"\n=== S194 F3 融合整体 §44 event edge（S201a cost 口径统一后）===")
    print(f"  status: {v.status}  event_status: {getattr(v, 'event_status', None)}")
    print(f"  day_mean: {day_mean}  days_robust: {v.days_robust}  p_bh: {getattr(v, 'p_bh', None)}")
    print(f"  n: {v.n}  n_effective(day-clustered): {getattr(v, 'n_effective', None)}")
    print(f"  round_trip_cost: {mean_cost_pct:.3f}%（逐笔 _cost_pct mean，size-dependent 5元门保留）")
    print(f"  cost range: {min(costs):.3f}% ~ {max(costs):.3f}%（size-dependent 非 flat）")
    print(f"\n  fusion_conclusion: {interp['fusion_conclusion']}")
    print(f"  null_engagement: {interp['null_engagement']}")
    print(f"\n  ⚠️ S201a 修复：旧 flat 0.2% → 逐笔 _cost_pct mean={mean_cost_pct:.3f}%（含 5元门 size-dependent）")
    print(f"  verdict 变化：+0.36% robust_edge（旧 0.2%）→ ~-1.0% falsified/exploratory（诚实可复现）")


if __name__ == "__main__":
    main()
