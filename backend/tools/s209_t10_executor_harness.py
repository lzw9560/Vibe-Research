# -*- coding: utf-8 -*-
# S209 T6: post-首板 relay §44 验证 harness（lbc==1 首板 D+1 path）
# verdict (预期): underpowered（~46 天 < 60 天 R6 gate，诚实不造假 robust_edge）
#   - selection edge: day_paired lift（picks vs universe）+ permutation + walk-forward + Bonferroni K=2
#   - event edge: picks 群体净收益 > 0（event_materiality_floor）
#   - day_paired 控 regime（同日配对，非 pooled——pooled day-cluster 膨胀，§44v2 已证 4.686x→1.723x）
# DRY: scan_pre_limitup（S208）+ simulate_holding + _cost_pct + _is_unbuyable + wire_verdict（mirror lianban_lift）
# 继承 breakout -4/+8/3（74295b9 冻结，不新 sweep——小样本 sweep=overfit）
# 前提证否：breakout +0.36% net 是 5元佣金门+regime 假象（S201）→ post_first_board exploratory 自证
"""S209 T6: post-首板 relay (lbc==1) §44 验证 harness——T10 executor 配套。

跑 scan_pre_limitup(T-1) → simulate_holding(-4/+8/3) + _cost_pct + _is_unbuyable → §44 verdict
（K=2 Bonferroni: selection + event）。预期 underpowered（~46 天 < 60 R6 gate，诚实）。
DRY 复用 lianban_lift pattern（simulate_holding + wire_verdict），不重写统计栈。

跑法：cd backend && .venv/bin/python tools/s209_t10_executor_harness.py
依赖：.vibe-research/baostock_kline_cache.json + zt_history.db（zero em_get，全离线 cache）。
"""
import datetime  # noqa: F401
import sqlite3
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from data_quality.schema_validator import validate_or_reject  # noqa: E402
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402  # S204 T1: enriched pctChg
from tools._s44_wire import wire_verdict  # noqa: E402  # S168 接线 §44v2
from strategies.kline_returns import simulate_holding, _is_unbuyable_next_bar  # noqa: E402
from engine.accounting import _cost_pct  # noqa: E402  # S201b: per-trade cost 非 flat 0.70
from pre_limitup_scanner import scan_pre_limitup  # noqa: E402  # S208: lbc==1 首板源

KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
ZT_DB = ROOT / ".vibe-research" / "zt_history.db"
PARAMS = (-4.0, 8.0, 3)  # 继承 breakout DEFAULT_PATH_PARAMS（74295b9 冻结，不 sweep——小样本 sweep=overfit）
FROZEN = "45bafca"  # frozen at pre-harness commit（S209 T6 引入前 HEAD；reproduce 用此 codebase + harness 本 commit）


def _zt_history_dates() -> list[str]:
    """zt_history 所有首板日（DISTINCT date WHERE lbc==1 exists），有序。

    不臆造——ZT_DB 不存在返 []（harness main 标 underpowered）。
    """
    if not ZT_DB.exists():
        return []
    conn = sqlite3.connect(str(ZT_DB))
    try:
        rows = conn.execute(
            "SELECT DISTINCT date FROM zt_history WHERE lbc=1 AND is_final=1 ORDER BY date"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows if r[0]]


def compute_obs(
    cache: dict[str, list[dict]],
    dates: list[str],
    *,
    scanner=scan_pre_limitup,
    holder=simulate_holding,
    cost_fn=_cost_pct,
) -> list[dict[str, Any]]:
    """算 post_first_board obs（D, code, net, win, cost）——可 test 纯函数。

    对每个首板日 D：scan_pre_limitup(D, previous_trade_day=D) → lbc==1 候选
    → simulate_holding(bars, D, -4, 8, 3)（D+1 open entry）+ _is_unbuyable_next_bar 过滤
    + _cost_pct（per-trade，5元门 size-dependent）→ net = return_pct - cost。

    依赖注入（scanner/holder/cost_fn）供 test mock。不臆造数据。
    """
    obs: list[dict[str, Any]] = []
    for D in dates:
        cands = scanner(D, previous_trade_day=D)
        if not cands:
            continue
        for c in cands:
            code = c.get("code") or ""
            if not code:
                continue
            bars = cache.get(code)
            if not bars:
                continue
            d_idx = next((i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == D), None)
            if d_idx is None or d_idx + 1 >= len(bars):
                continue
            if _is_unbuyable_next_bar(bars[d_idx + 1]):
                continue  # 一字板封死买不到（survivorship 过滤）
            sim = holder(bars, D, *PARAMS)
            if sim is None:
                continue
            entry_price = float(bars[d_idx + 1].get("open", 0) or 0)
            cost = cost_fn(entry_price, 100.0, D) if entry_price > 0 else 0.0
            net = sim["return_pct"] - cost
            obs.append({"D": D, "code": code, "net": net, "win": 1 if net > 0 else 0, "cost": cost})
    return obs


def _verdict_summary(v) -> dict:
    """Verdict dataclass → summary dict（防御 .status/.selection_lift/.n/.days_robust）。"""
    return {
        "status": getattr(v, "status", None),
        "selection_lift": getattr(v, "selection_lift", None),
        "n": getattr(v, "n", None),
        "days_robust": getattr(v, "days_robust", None),
    }


def main() -> dict[str, Any]:
    """跑 §44 验证 → wire_verdict（selection + event，K=2 Bonferroni）→ 返 summary。

    <30 obs → underpowered（诚实，不造假 robust_edge，R6 gate）。
    """
    cache = _load_kline_cache()
    # S163 R1: 坏 bar（缺字段/负价/high<low/stale/空/错型）拒绝进 §44 verdict
    validate_or_reject(
        "baostock_kline",
        [b for bars in cache.values() for b in bars],
        as_of=datetime.date.today().isoformat(),
    )
    dates = _zt_history_dates()
    print(f"首板日={len(dates)}", flush=True)
    if not dates:
        print("[S209] zt_history 无首板数据 → underpowered（n=0）")
        return {"status": "underpowered", "n": 0, "days": 0, "reason": "no zt_history dates"}

    obs = compute_obs(cache, dates)
    n_obs = len(obs)
    days = len(set(o["D"] for o in obs))
    if n_obs < 30:
        print(f"n={n_obs} <30 探索性 → underpowered（诚实，R6 gate days<60）")
        return {"status": "underpowered", "n": n_obs, "days": days, "reason": "n<30"}

    all_wins = sum(o["win"] for o in obs)
    wr_all = all_wins / n_obs
    net_mean = statistics.mean(o["net"] for o in obs)
    mean_cost = sum(o["cost"] for o in obs) / n_obs if obs else 0.0
    print(f"\nobs={n_obs} days={days} | all net-WR(首板 D+1): {wr_all*100:.2f}% net_mean={net_mean:.2f}% "
          f"(扣 cost ~{mean_cost:.2f}%)")

    # day_paired: picks = all lbc==1（post_first_board 是 binary arm，无 score-ranked quintile split）。
    # 同日 picks == universe（all first-board）→ selection lift≈1.0 by design；
    # 真 selection edge 须 score-ranked（post_first_board 无 score），标 underpowered/探索性。
    # day_paired 控 regime（同日配对非 pooled）。
    survivors_by_day: dict[str, list[float]] = {}
    universe_by_day: dict[str, list[float]] = {}
    for o in obs:
        survivors_by_day.setdefault(o["D"], []).append(o["net"])
        universe_by_day.setdefault(o["D"], []).append(o["net"])
    rets = [r for rs in survivors_by_day.values() for r in rs]
    dts = [d for d, rs in survivors_by_day.items() for _ in rs]

    # selection wire_verdict（day_paired lift，K=2 Bonferroni: selection + event）
    v_sel = wire_verdict(
        line_id="post_first_board:selection",
        returns=rets,
        dates=dts,
        edge_type="selection",
        frozen_commit=FROZEN,
        survivors_by_day=dict(survivors_by_day),
        universe_by_day=dict(universe_by_day),
        n_comparisons=2,  # Bonferroni K=2（selection + event，§44v2 按 n 调不 over-correct）
        round_trip_cost=round(mean_cost, 4),
        script="tools/s209_t10_executor_harness.py",
        params={
            "arm": "post_first_board", "path": list(PARAMS), "cost": "per_trade",
            "source": "scan_pre_limitup", "lbc": 1, "quintile": "none_binary_arm",
        },
    )
    # event wire_verdict（群体净收益 > 0，K=2 Bonferroni；event 不用 survivors/universe）
    v_evt = wire_verdict(
        line_id="post_first_board:event",
        returns=rets,
        dates=dts,
        edge_type="event",
        frozen_commit=FROZEN,
        n_comparisons=2,  # Bonferroni K=2（同 selection 共享 family）
        round_trip_cost=round(mean_cost, 4),
        script="tools/s209_t10_executor_harness.py",
        params={
            "arm": "post_first_board", "path": list(PARAMS), "cost": "per_trade",
            "source": "scan_pre_limitup", "lbc": 1,
        },
    )
    print(f"\n[verdict] selection: status={v_sel.status} lift={v_sel.selection_lift} "
          f"n={v_sel.n} days_robust={v_sel.days_robust}")
    print(f"[verdict] event:     status={v_evt.status} n={v_evt.n} days_robust={v_evt.days_robust}")
    return {
        "selection": _verdict_summary(v_sel),
        "event": _verdict_summary(v_evt),
        "n_obs": n_obs,
        "days": days,
        "net_mean": round(net_mean, 4),
        "net_wr": round(wr_all, 4),
    }


if __name__ == "__main__":
    main()
