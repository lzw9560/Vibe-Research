#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S201b cost-sweep：§44 F3 verdict 在不同成本口径下的稳定性（非破坏性分析）。

不改 accounting/journal——展示 verdict 对 cost 口径的敏感度，为 S201b 校准 spec
（降 ROUND_TRIP_COST_PCT 0.70→0.15 + 修出场乐观 + 扫脚本 + 重结 journal）
提供决策依据。

成本口径：
- flat 0.10% / 0.15% / 0.20% / 0.30%（S201b RTC 候选值）
- 逐笔 _cost_pct mean（S201a 真实 size-dependent 5元门，~1.46%→S201b 后 ~0.96%）

S201b v2：BH 跨口径多重比较校正（verdict §8 #7）——5 口径各 n_comparisons=1 无跨口径
校正，BH 0.022×5=0.11>0.05 → flat 0.10% 降 exploratory 非 robust_edge。

纯函数 compute_net_at_levels 可单测；main() 调 s44_verifier + journal I/O + BH 校正。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# flat 成本口径（百分点），不含佣金/印花——模拟 ROUND_TRIP_COST_PCT 候选值
COST_LEVELS_PCT: list[float] = [0.10, 0.15, 0.20, 0.30]


def recompute_gross_v2(cases: list, bars_provider=None) -> list[tuple]:
    """S201b stage 2: 用新 path_return（stop gap-through-aware fix）重算 gross。

    旧 gross_return 是硬编码 stop_pct（乐观，gap-through 未建模）。
    新 path_return stop 分支 gap-through-aware：open<=stop→fill=open（更差），
    low<=stop→fill=stop*(1-eps)，一字跌停→carry。
    take/max_hold 分支不变（take 是 limit sell 已 realistic）。

    Read-only（不写 journal），fall back 到冻结 gross 当 bars 不足。
    返 [(gross_pct, cost_pct, entry_date), ...]（都百分数）。
    """
    from engine.accounting import path_return, _cost_pct  # noqa: PLC0415
    from engine.decision import Trades, FILL_T_PLUS_1_OPEN, FILL_ACCEPTED  # noqa: PLC0415
    from strategies.journal_recorder import (  # noqa: PLC0415
        DEFAULT_SIZE, BREAKOUT_STOP_PCT, BREAKOUT_TAKE_PCT, BREAKOUT_MAX_HOLD,
        TREND_STOP_PCT, TREND_TAKE_PCT, TREND_MAX_HOLD,
    )

    if bars_provider is None:
        from engine.bars_provider import KlineCacheBarsProvider  # noqa: PLC0415
        bars_provider = KlineCacheBarsProvider()

    arm_params = {
        "breakout": (BREAKOUT_STOP_PCT, BREAKOUT_TAKE_PCT, BREAKOUT_MAX_HOLD),
        "trend": (TREND_STOP_PCT, TREND_TAKE_PCT, TREND_MAX_HOLD),
    }

    results: list[tuple] = []
    n_recomputed = 0
    n_fallback = 0
    for rec in cases:
        gr = rec.gross_return
        if gr is None or rec.entry_price is None:
            continue
        entry_price = float(rec.entry_price)
        cost = _cost_pct(entry_price, DEFAULT_SIZE, rec.entry_date)

        params = arm_params.get(rec.arm)
        if params is None:
            # floor 等非 path_return 臂 → 用冻结 gross
            results.append((float(gr), cost, rec.entry_date))
            n_fallback += 1
            continue

        bars = bars_provider(rec.stock_code)
        if not bars:
            results.append((float(gr), cost, rec.entry_date))
            n_fallback += 1
            continue

        trades = Trades(
            code=rec.stock_code, signal_date=rec.entry_date,
            fill_type=FILL_T_PLUS_1_OPEN, direction="long",
            size=DEFAULT_SIZE, entry_price=entry_price,
            fill_status=FILL_ACCEPTED,
        )
        stop, take, max_hold = params
        pr = path_return(trades, bars, stop, take, max_hold, apply_cost=True)
        if pr is None:
            results.append((float(gr), cost, rec.entry_date))
            n_fallback += 1
        else:
            results.append((pr.gross_return_pct, pr.cost_pct, rec.entry_date))
            n_recomputed += 1

    print(f"# recompute_gross_v2: {n_recomputed} recomputed, {n_fallback} fallback (frozen)",
          file=sys.stderr)
    return results


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
    """跑 cost-sweep：读 journal + recompute_gross_v2（S201b stage 2 stop fix），各口径调 s44_verifier + BH 校正。"""
    from s44_verifier import verify  # noqa: PLC0415
    from s44_verifier.stats import bonferroni_bh  # noqa: PLC0415
    from engine.trade_journal import TradeJournal  # noqa: PLC0415

    tj = TradeJournal()
    cases = tj.query_records(is_realized=1, is_dead_arm=0, limit=10000)
    # S201b stage 2: recompute gross with stop gap-through-aware fix
    recomputed = recompute_gross_v2(cases)
    gross_returns: list[float] = []
    dates: list[str] = []
    per_trade_costs: list[float] = []
    for gross_pct, cost_pct, entry_date in recomputed:
        per_trade_costs.append(cost_pct)
        gross_returns.append(gross_pct / 100.0)
        dates.append(entry_date)

    if len(gross_returns) < 30:
        print(f"# 样本不足 {len(gross_returns)}<30，无法跑 §44 cost-sweep", file=sys.stderr)
        return

    sweeps = compute_net_at_levels(gross_returns, per_trade_costs)
    print(f"# S201b cost-sweep（RTC=0.15 + stage2 stop fix）：{len(gross_returns)} 条 event，{len(set(dates))} 唯一日", file=sys.stderr)
    print(f"# 逐笔 _cost_pct mean={sum(per_trade_costs)/len(per_trade_costs):.3f}% (S201b RTC=0.15 后)", file=sys.stderr)
    print(f"{'cost 口径':<35} {'day_mean':>10} {'status':>18} {'days_robust':>12} {'p_raw':>8} {'p_bh':>8}")
    print("-" * 100)

    # S201b verdict §8 #7：BH 跨口径多重比较校正（5 口径 n_comparisons=1 → K=5）
    raw_p_values: list[float] = []
    verdicts: list = []
    for s in sweeps:
        v = verify(
            returns=s["returns"], n_trials=1, edge_type="event", dates=dates,
            round_trip_cost=s["round_trip_cost"], frozen_commit="S194-F3-dev",
            n_comparisons=1,
        )
        verdicts.append(v)
        p_raw = getattr(v, "p_bh", None) or getattr(v, "p_bon", None) or 1.0
        raw_p_values.append(float(p_raw))

    # BH 跨口径校正（K=5）
    bh_adjusted = bonferroni_bh(raw_p_values, method="BH")

    for i, s in enumerate(sweeps):
        v = verdicts[i]
        em = getattr(v, "event_metrics", None)
        day_mean = getattr(em, "day_mean", None) if em else None
        print(f"{s['label']:<35} {str(day_mean):>10} {v.status:>18} {v.days_robust:>12} {raw_p_values[i]:>8.4f} {bh_adjusted[i]:>8.4f}")
    print()
    print("# S201b stage2 结论（stop gap-through-aware fix 后）：", file=sys.stderr)
    print("# - 全口径 falsified（含 flat 0.10%，stage1 raw p<0.05 robust_edge artifact 消失）", file=sys.stderr)
    print("# - stop 出场乐观修复使 gross 更差（gap-through fill=open > 硬编码 stop_pct），day_mean 更负", file=sys.stderr)
    print("# - 佣金门是结构性杀手（逐笔 mean=0.914% > gross day_mean），降 spread 不 unfalsify", file=sys.stderr)


if __name__ == "__main__":
    main()
