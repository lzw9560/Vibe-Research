# -*- coding: utf-8 -*-
"""S228 offline 量化：consecutive_relay 新 edge 定义验证。

vs 原 s203_harness（V1 edge = D close→D+1 open，D close=涨停价）：
  V2 edge = D+1 close → D+2 open（spec S218 line 15+38 本意）
  - entry 后移一天（D close 涨停价 → D+1 close 非涨停价，D+1 一字板被过滤）
  - exit 后移一天（D+1 open → D+2 open）
  - unbuyable 改判 D+1 一字板（entry day 封死涨停 close 买不到）而非 D 日一字板

目的：揭示当前 +1.04% verdict 真 source——
  - 若 V2 edge 消失/变负 → 当前 +1.04% 是"D 涨停封板溢价"非"连板接力 edge"→ 战法证否
  - 若 V2 edge 仍 +1% 左右 → edge 是真"连板接力"（entry 时机后移不影响）→ fix 安全

不改生产代码（_process_consecutive_relay / daily_report / API 不动）——只 offline 量化。
依赖同原 harness：baostock_kline_cache.json + zt_history.db + index_ma20_regime.json
跑法：cd backend && .venv/bin/python tools/s203_consecutive_relay_harness_v2.py
"""

import statistics  # noqa: PLC0415
import sys
from pathlib import Path

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from data_quality.schema_validator import validate_or_reject  # noqa: E402
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402
from tools.regime_stratified_consecutive_relay_lift import run  # noqa: E402
from tools.gap_regime_stratified import compute_market_o2c_gap_by_date, compute_regime_labels  # noqa: E402
from strategies.kline_returns import _is_unbuyable_next_bar  # noqa: E402
from engine.accounting import _cost_pct  # noqa: E402
from tools.s203_consecutive_relay_harness import _zt_history_picks_lbc2  # noqa: E402

KLINE = resolve_data_dir() / "baostock_kline_cache.json"
FROZEN = "f6a964e"


def compute_obs_v2(
    cache: dict[str, list[dict]],
    picks: list[tuple[str, str]],
    *,
    cost_fn=_cost_pct,
) -> list[dict]:
    """V2 edge obs——entry=D+1 close, exit=D+2 open（spec S218 本意）。

    vs V1 compute_obs（entry=D close 涨停价, exit=D+1 open）：
      - entry_idx=d_idx+1（D+1=entry day），exit_idx=d_idx+2（D+2=exit day）
      - unbuyable 判 bars[entry_idx]（D+1 一字板，entry day close 买不到）
      - close_entry=bars[entry_idx].close（D+1 close，非涨停价）
      - open_exit=bars[exit_idx].open（D+2 open）
      - gap_ret = (open_exit - close_entry) / close_entry

    D+1 一字板（继续封死涨停的 momentum 最强 picks）被过滤——
    若这些 picks 是 V1 +1.04% 的主要贡献者，V2 edge 将结构性消失。
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
        if d_idx is None or d_idx + 2 >= len(bars):  # V2 需 D+2 bar（V1 只需 D+1）
            continue
        entry_idx = d_idx + 1  # D+1=entry day
        exit_idx = d_idx + 2  # D+2=exit day
        entry_bar = bars[entry_idx]
        exit_bar = bars[exit_idx]
        # V2 unbuyable: 判 D+1 一字板（entry day 封死涨停 close 买不到）
        # vs V1 判 D 日一字板（D close 涨停价买不到）
        if _is_unbuyable_next_bar(entry_bar, code=code):
            continue  # D+1 一字板封死（entry day close 买不到，survivorship 过滤）
        close_entry = float(entry_bar.get("close", 0) or 0)  # D+1 close
        open_exit = float(exit_bar.get("open", 0) or 0)  # D+2 open
        if close_entry <= 0 or open_exit <= 0:
            continue
        gap_ret = (open_exit - close_entry) / close_entry  # V2 edge decimal
        cost_pct = cost_fn(open_exit, 100.0, D) if open_exit > 0 else 0.0
        cost_dec = cost_pct / 100.0
        net = gap_ret - cost_dec
        obs.append({"D": D, "code": code, "net": net, "win": 1 if net > 0 else 0, "cost": cost_dec})
    return obs


def main() -> dict:
    """跑 V2 edge chrono holdout → 对比 V1 verdict（+1.04% p=0.0054）。"""
    cache = _load_kline_cache()
    import datetime  # noqa: PLC0415

    validate_or_reject(
        "baostock_kline",
        [b for bars in cache.values() for b in bars],
        as_of=datetime.date.today().isoformat(),
    )
    picks = _zt_history_picks_lbc2()
    dates = sorted(set(D for D, _ in picks))
    print(f"[V2] 连板接力日={len(dates)} picks={len(picks)}", flush=True)
    print("[V2] edge 定义: entry=D+1 close, exit=D+2 open（vs V1: D close→D+1 open）", flush=True)
    if not picks:
        print("[V2] zt_history 无 lbc>=2 数据 → underpowered")
        return {"status": "underpowered", "n": 0, "days": 0}

    obs = compute_obs_v2(cache, picks)
    n_obs = len(obs)
    days = len(set(o["D"] for o in obs))
    print(f"[V2] obs={n_obs} days={days} (D+1 一字板过滤+缺 bars 跳过)", flush=True)
    if n_obs < 30:
        print(f"[V2] n={n_obs}<30 → underpowered")
        return {"status": "underpowered", "n": n_obs, "days": days, "reason": "n<30"}

    rets = [o["net"] for o in obs]
    dts = [o["D"] for o in obs]
    mean_cost_dec = sum(o["cost"] for o in obs) / n_obs
    regime_map = compute_regime_labels()
    if not regime_map:
        print("[FATAL] no regime labels")
        return {"status": "error", "n": n_obs, "days": days, "reason": "no regime"}

    wr = sum(o["win"] for o in obs) / n_obs
    net_mean = statistics.mean(rets)
    print(
        f"[V2] all net-WR: {wr * 100:.2f}% net_mean={net_mean * 100:.2f}% (扣 cost ~{mean_cost_dec * 100:.2f}%)",
        flush=True,
    )

    universe_by_day = compute_market_o2c_gap_by_date()
    print(f"[V2 drift] market o2c gap: {len(universe_by_day)} 天", flush=True)
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
    print(f"\n[V2 verdict] regime-stratified consecutive_relay (lbc>=2) — 新 edge:")
    for tag, r in results.items():
        st = r.get("verdict_status", "?")
        nt = r.get("verdict_note", "") or ""
        print(
            f"  {tag}: n_picks={r.get('n_picks')} n_days={r.get('n_days')} "
            f"net_mean={r.get('net_mean_pct')} winrate={r.get('win_rate')} "
            f"verdict={st} wf={r.get('walk_forward_status')} | {nt[:80]}"
        )

    from s44_verifier.stats import chronological_holdout_event_check  # noqa: PLC0415

    def _chrono_for_regime(tag: str) -> dict:
        pairs = [(r, d) for r, d in zip(rets, dts) if regime_map.get(d) == tag]
        if not pairs:
            print(f"\n[V2 chrono-OOS] no {tag}-regime obs")
            return {"decision": "insufficient", "n_test_days": 0}
        regime_rets = [p[0] for p in pairs]
        regime_dates = [p[1] for p in pairs]
        chrono = chronological_holdout_event_check(regime_rets, regime_dates, round_trip_cost=round(mean_cost_dec, 6))
        n_test = chrono.get("n_test_days", 0) or 0
        chrono["underpowered"] = n_test < 30
        print(f"\n[V2 chrono-OOS] {tag} regime 2/3-1/3 chronological holdout:")
        print(
            f"  n_train_days={chrono['n_train_days']} n_test_days={chrono['n_test_days']} "
            f"train_day_mean={chrono['train_day_mean']}"
        )
        print(
            f"  test_day_mean={chrono['test_day_mean']} test_p_one_sided={chrono['test_p_one_sided']} "
            f"test_win_rate={chrono['test_win_rate']}"
        )
        print(f"  decision={chrono['decision']} note={chrono['decision_note']}")
        return chrono

    bull_chrono = _chrono_for_regime("bull")
    bear_chrono = _chrono_for_regime("bear")

    print(f"\n{'=' * 60}")
    print("[V2 vs V1 对比]")
    print(f"  V1 (D close→D+1 open): bull net_mean=+1.04% p=0.0054 n_test=57 (旧 verdict)")
    print(
        f"  V2 (D+1 close→D+2 open): bull net_mean={bull_chrono.get('test_day_mean', '?')} "
        f"p={bull_chrono.get('test_p_one_sided', '?')} n_test={bull_chrono.get('n_test_days', '?')}"
    )
    print(
        f"  V2 bear: net_mean={bear_chrono.get('test_day_mean', '?')} "
        f"p={bear_chrono.get('test_p_one_sided', '?')} n_test={bear_chrono.get('n_test_days', '?')}"
    )
    print("  结论: V2 edge 消失/变负 → 当前 +1.04% 是'D 涨停封板溢价'非'连板接力 edge'→ 战法证否")
    print("        V2 edge 仍 +1% 左右 → edge 是真连板接力 → fix 安全")

    return {
        "results": results,
        "n_obs": n_obs,
        "days": days,
        "net_mean_pct": round(net_mean * 100, 4),
        "net_wr": round(wr, 4),
        "bull_chrono_oos": bull_chrono,
        "bear_chrono_oos": bear_chrono,
    }


if __name__ == "__main__":
    main()
