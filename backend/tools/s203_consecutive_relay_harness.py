# -*- coding: utf-8 -*-
"""S203 consecutive-relay (lbc>=2 连板接力) §44 regime-stratified harness.

连板接力隔夜 gap return（D 收→D+1 开）按 MA20 3-way regime（bull/bear/range）分层，
per-regime wire_verdict(event)。问：连板接力隔夜收益是 regime 假象吗？

类比 T6 s209_t10_executor_harness.py（post_first_board lbc==1），但：
  - lbc>=2（连板接力，非首板）
  - overnight gap return（D 收→D+1 开，非 -4/+8/3 path）
  - regime-stratified（consecutive_relay_lift.run，非直接 wire_verdict）

口径：returns 用 **decimal**（如 0.02=2%），对齐 regime_stats 的
``net_mean_pct = arr.mean() * 100``；cost 用 _cost_pct/100 转换 decimal 同口径。
verify 内 ``effective_floor = max(0.003, cost*0.5)`` 只要 returns+cost 同口径 verdict 对。

依赖：.vibe-research/baostock_kline_cache.json + zt_history.db + index_ma20_regime.json
跑法：cd backend && .venv/bin/python tools/s203_consecutive_relay_harness.py
"""
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from data_quality.schema_validator import validate_or_reject  # noqa: E402
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402
from tools.regime_stratified_consecutive_relay_lift import run  # noqa: E402
from tools.gap_regime_stratified import compute_market_o2c_gap_by_date, compute_regime_labels  # noqa: E402
from strategies.kline_returns import _is_unbuyable_next_bar  # noqa: E402
from engine.accounting import _cost_pct  # noqa: E402

KLINE = ROOT / ".vibe-research" / "baostock_kline_cache.json"
ZT_DB = ROOT / ".vibe-research" / "zt_history.db"
FROZEN = "f6a964e"  # fork C fetch_zt_pool fallback commit（consecutive_relay picks 解锁基线）


def _zt_history_picks_lbc2() -> list[tuple[str, str]]:
    """zt_history lbc>=2 连板接力 picks (date, code)，有序。

    不臆造——ZT_DB 不存在返 []。
    """
    if not ZT_DB.exists():
        return []
    conn = sqlite3.connect(str(ZT_DB))
    try:
        rows = conn.execute(
            "SELECT date, code FROM zt_history WHERE lbc>=2 AND is_final=1 "
            "ORDER BY date, code"
        ).fetchall()
    finally:
        conn.close()
    return [(r[0], r[1]) for r in rows if r[0] and r[1]]


def compute_obs(
    cache: dict[str, list[dict]],
    picks: list[tuple[str, str]],
    *,
    cost_fn=_cost_pct,
) -> list[dict]:
    """连板接力隔夜 gap obs（D, code, net, win, cost）——可 test 纯函数。

    对每个 (D, code)：baostock bars 找 D_idx → D 收 close + D+1 开 open →
    gap_ret = (open[D+1] - close[D]) / close[D]（decimal）+ _is_unbuyable_next_bar
    过滤一字板 + _cost_pct（per-trade，5 元门 size-dependent，/100 转 decimal）→
    net = gap_ret - cost（decimal）。
    """
    obs: list[dict] = []
    for D, code in picks:
        bars = cache.get(code)
        if not bars:
            continue
        d_idx = next(
            (i for i, b in enumerate(bars) if str(b.get("date", ""))[:10] == D),
            None,
        )
        if d_idx is None or d_idx + 1 >= len(bars):
            continue
        nxt = bars[d_idx + 1]
        # 入场是 D 日 close（gap_ret = open[D+1] - close[D] / close[D]），该过滤 D 日
        # 一字板（全天锁涨停，close 买不到），不是 D+1。verify w5d3urvxz CRITICAL fix：
        # 原 _is_unbuyable_next_bar(nxt) 查 D+1 错天——D 日一字板 57 个被算入，抬 61% edge。
        if _is_unbuyable_next_bar(bars[d_idx]):
            continue  # D 日一字板封死（入场日 close 买不到，survivorship 过滤）
        close_d = float(bars[d_idx].get("close", 0) or 0)
        open_d1 = float(nxt.get("open", 0) or 0)
        if close_d <= 0 or open_d1 <= 0:
            continue
        gap_ret = (open_d1 - close_d) / close_d  # decimal
        cost_pct = cost_fn(open_d1, 100.0, D) if open_d1 > 0 else 0.0
        cost_dec = cost_pct / 100.0  # pct→decimal 同口径
        net = gap_ret - cost_dec
        obs.append(
            {"D": D, "code": code, "net": net, "win": 1 if net > 0 else 0, "cost": cost_dec}
        )
    return obs


def main() -> dict:
    """跑 §44 regime-stratified verdict → consecutive_relay_lift.run → 返 summary。

    <30 obs → underpowered（诚实，不造假 robust_edge，R6 gate）。
    """
    cache = _load_kline_cache()
    # S163 R1: 坏 bar（缺字段/负价/high<low/stale/空/错型）拒绝进 §44 verdict
    import datetime  # noqa: PLC0415
    validate_or_reject(
        "baostock_kline",
        [b for bars in cache.values() for b in bars],
        as_of=datetime.date.today().isoformat(),
    )
    picks = _zt_history_picks_lbc2()
    dates = sorted(set(D for D, _ in picks))
    print(f"连板接力日={len(dates)} picks={len(picks)}", flush=True)
    if not picks:
        print("[S203] zt_history 无 lbc>=2 数据 → underpowered")
        return {"status": "underpowered", "n": 0, "days": 0, "reason": "no lbc>=2 picks"}

    obs = compute_obs(cache, picks)
    n_obs = len(obs)
    days = len(set(o["D"] for o in obs))
    print(f"obs={n_obs} days={days} (一字板过滤+缺 bars 跳过)", flush=True)
    if n_obs < 30:
        print(f"n={n_obs}<30 → underpowered（诚实，R6 gate）")
        return {"status": "underpowered", "n": n_obs, "days": days, "reason": "n<30"}

    rets = [o["net"] for o in obs]
    dts = [o["D"] for o in obs]
    mean_cost_dec = sum(o["cost"] for o in obs) / n_obs
    regime_map = compute_regime_labels()
    if not regime_map:
        print("[FATAL] no regime labels（index_ma20_regime.json 缺 + baostock 调失败）")
        return {"status": "error", "n": n_obs, "days": days, "reason": "no regime"}

    wr = sum(o["win"] for o in obs) / n_obs
    net_mean = statistics.mean(rets)
    print(
        f"all net-WR(连板接力 隔夜gap): {wr*100:.2f}% net_mean={net_mean*100:.2f}% "
        f"(扣 cost ~{mean_cost_dec*100:.2f}%)",
        flush=True,
    )

    # S210 T3: 算 market o2c gap by date 传 run()（drift fix 控牛市 drift）
    universe_by_day = compute_market_o2c_gap_by_date()
    print(f"[drift] market o2c gap: {len(universe_by_day)} 天", flush=True)
    results = run(
        returns=rets,
        dates=dts,
        regime_map=regime_map,
        universe_by_day=universe_by_day,
        frozen_commit=FROZEN,
        round_trip_cost=round(mean_cost_dec, 6),
        walk_train=20,
        walk_test=10,
        step=10,
    )
    print(f"\n[verdict] regime-stratified consecutive_relay (lbc>=2):")
    for tag, r in results.items():
        st = r.get("verdict_status", "?")
        nt = r.get("verdict_note", "") or ""
        print(
            f"  {tag}: n_picks={r.get('n_picks')} n_days={r.get('n_days')} "
            f"net_mean={r.get('net_mean_pct')} winrate={r.get('win_rate')} "
            f"verdict={st} wf={r.get('walk_forward_status')} pk={r.get('purged_kfold_status')} | {nt[:80]}"
        )

    # S217: chronological 2/3-1/3 holdout forward-OOS on the bull regime
    # (the only robust_edge arm; in-sample robust_edge +1.57% — does it survive
    # held-out data? pre-registered in specs/S217, zero-tunable split).
    from s44_verifier.stats import chronological_holdout_event_check  # noqa: PLC0415

    bull_pairs = [(r, d) for r, d in zip(rets, dts) if regime_map.get(d) == "bull"]
    if bull_pairs:
        bull_rets = [p[0] for p in bull_pairs]
        bull_dates = [p[1] for p in bull_pairs]
        chrono = chronological_holdout_event_check(
            bull_rets, bull_dates, round_trip_cost=round(mean_cost_dec, 6)
        )
        print("\n[S217 chrono-OOS] bull regime 2/3-1/3 chronological holdout:")
        print(
            f"  n_train_days={chrono['n_train_days']} n_test_days={chrono['n_test_days']} "
            f"train_day_mean={chrono['train_day_mean']}"
        )
        print(
            f"  test_day_mean={chrono['test_day_mean']} test_p_one_sided={chrono['test_p_one_sided']} "
            f"test_win_rate={chrono['test_win_rate']} test_day_std={chrono['test_day_std']}"
        )
        print(f"  decision={chrono['decision']}")
        print(f"  note: {chrono['decision_note']}")
    else:
        print("\n[S217 chrono-OOS] no bull-regime obs to hold out")
        chrono = {"decision": "insufficient", "n_test_days": 0}

    return {
        "results": results,
        "n_obs": n_obs,
        "days": days,
        "net_mean_pct": round(net_mean * 100, 4),
        "net_wr": round(wr, 4),
        "bull_chrono_oos": chrono,
    }


if __name__ == "__main__":
    main()
