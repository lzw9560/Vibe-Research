#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S201b cost-sweep：§44 F3 verdict 在不同成本口径下的稳定性（非破坏性分析）。

不改 accounting/journal——展示 verdict 对 cost 口径的敏感度，为 S201b 校准 spec
（降 ROUND_TRIP_COST_PCT 0.70→0.10-0.20% + 修出场乐观 + 扫脚本 + 重结 journal）
提供决策依据。

成本口径：
- flat 0.10% / 0.20% / 0.30% / 0.70%（旧 spread+slip，含美股假设）
- 逐笔 _cost_pct mean（S201a 真实 size-dependent 5元门，~1.46%）

纯函数 compute_net_at_levels 可单测；main() 调 s44_verifier + journal I/O。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# flat 成本口径（百分点），不含佣金/印花——模拟 ROUND_TRIP_COST_PCT 候选值
COST_LEVELS_PCT: list[float] = [0.10, 0.20, 0.30, 0.70]


def compute_net_at_levels(
    gross_returns: list[float],
    per_trade_costs: list[float],
    levels_pct: list[float] | None = None,
) -> list[dict]:
    """纯函数：算各 flat cost 口径 + 逐笔 _cost_pct 口径下的 net returns。

    gross_returns: 分数（0.013=1.3%），per_trade_costs: 百分数（1.46=1.46%）。
    返 [{label, returns, round_trip_cost, cost_pct_mean}]，returns 分数，rtc 分数。
    单调性：cost 越高 net 越低（测试断言）。
    """
    levels = levels_pct or COST_LEVELS_PCT
    mean_cost = sum(per_trade_costs) / len(per_trade_costs) if per_trade_costs else 0.0
    out: list[dict] = []
    for c in levels:
        returns = [gr - c / 100.0 for gr in gross_returns]
        out.append({
            "label": f"flat {c}%",
            "returns": returns,
            "round_trip_cost": c / 100.0,
            "cost_pct_mean": mean_cost,
        })
    # 逐笔 _cost_pct（S201a 真实 size-dependent 5元门）
    out.append({
        "label": f"逐笔 _cost_pct mean={mean_cost:.3f}%",
        "returns": [gr - c / 100.0 for gr, c in zip(gross_returns, per_trade_costs)],
        "round_trip_cost": mean_cost / 100.0,
        "cost_pct_mean": mean_cost,
    })
    return out


def main() -> None:
    """跑 cost-sweep：读 journal gross + 逐笔 _cost_pct，各口径调 s44_verifier。"""
    from s44_verifier import verify  # noqa: PLC0415
    from engine.trade_journal import TradeJournal  # noqa: PLC0415
    from engine.accounting import _cost_pct  # noqa: PLC0415
    from strategies.journal_recorder import DEFAULT_SIZE  # noqa: PLC0415

    tj = TradeJournal()
    cases = tj.query_records(is_realized=1, is_dead_arm=0, limit=10000)
    gross_returns: list[float] = []
    dates: list[str] = []
    per_trade_costs: list[float] = []
    for rec in cases:
        gr = rec.gross_return
        if gr is None:
            continue
        entry_price = float(rec.entry_price) if rec.entry_price else 0.0
        per_trade_costs.append(_cost_pct(entry_price, DEFAULT_SIZE, rec.entry_date))
        gross_returns.append(float(gr) / 100.0)
        dates.append(rec.entry_date)

    if len(gross_returns) < 30:
        print(f"# 样本不足 {len(gross_returns)}<30，无法跑 §44 cost-sweep", file=sys.stderr)
        return

    sweeps = compute_net_at_levels(gross_returns, per_trade_costs)
    print(f"# S201b cost-sweep：{len(gross_returns)} 条 event，{len(set(dates))} 唯一日", file=sys.stderr)
    print(f"{'cost 口径':<35} {'day_mean':>10} {'status':>18} {'days_robust':>12} {'p_bh':>8}")
    print("-" * 90)
    for s in sweeps:
        v = verify(
            returns=s["returns"], n_trials=1, edge_type="event", dates=dates,
            round_trip_cost=s["round_trip_cost"], frozen_commit="S194-F3-dev",
            n_comparisons=1,
        )
        em = getattr(v, "event_metrics", None)
        day_mean = getattr(em, "day_mean", None) if em else None
        print(f"{s['label']:<35} {str(day_mean):>10} {v.status:>18} {v.days_robust:>12} {str(getattr(v,'p_bh',None)):>8}")
    print()
    print("# 结论：", file=sys.stderr)
    print("# - 所有口径都 falsified → cost 校准不改变结论（edge 真无，S201b 降 spread 无翻案价值）", file=sys.stderr)
    print("# - 低 cost(0.10) robust_edge 但高 cost falsified → edge 被 cost 吃掉（S201b 校准重要，可能 unfalsify）", file=sys.stderr)
    print("# - 逐笔 1.46% vs flat 0.70% verdict 不同 → size-dependent 5元门重要（S182 fix 验证）", file=sys.stderr)


if __name__ == "__main__":
    main()
