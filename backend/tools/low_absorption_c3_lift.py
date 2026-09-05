# -*- coding: utf-8 -*-
"""S153 R8：low_absorption C3 缩量验证 harness——H4 预注册交互假设验证。

H4 C3 缩量（vol_brk<1.0）三条件交互（ma5_prox<=3 + ma_bullish + vol_brk<1）vs raw（C1+C2 无 C3）。
day_paired_lift 非池化 + day_cluster_permutation within-day survivor resampling +
rolling walk-forward + Bonferroni K=8 α_adj=0.00625。
target=path-winrate（signal_date=D+1, 入场 D+2 open, DEFAULT_PATH_PARAMS -3/+8/3）。
regime=强势/震荡（sh.000001 MA20 斜率>0，非 close>MA20）。pre-register 冻结 commit 74295b9。
R8 无 D+1 突破确认（非 platform_breakout），arms=raw/tight（无 confirm/both）。
"""
from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from tools.first_board_layer_lift import day_paired_lift, four_state, _winrate  # noqa: E402
from tools.first_board_premium_baseline import _load_kline_cache  # noqa: E402
from strategies.kline_returns import simulate_holding  # noqa: E402
from strategies.pattern_scan import scan_patterns  # noqa: E402

# 预注册冻结（commit 74295b9）
C3_THRESHOLD = 1.0             # H4 C3 vol_brk<1.0（缩量）
DEFAULT_PATH_PARAMS = (-3.0, 8.0, 3)
ALPHA_ADJ = 0.05 / 8           # Bonferroni K=8
N_PERM = 2000
PERM_SEED = 42
WALK_TRAIN = 100
WALK_TEST = 20
WALK_STEP = 20


def day_cluster_permutation(surv_by_day, raw_by_day, n_perm=N_PERM, seed=PERM_SEED):
    """within-day survivor resampling null（同 R7，pre-register 冻结 commit 74295b9）。"""
    rng = random.Random(seed)
    nulls = []
    for _ in range(n_perm):
        null_surv_by_day = {}
        for date, raw_rets in raw_by_day.items():
            surv_rets = surv_by_day.get(date, [])
            if not surv_rets or len(raw_rets) < len(surv_rets):
                continue
            null_surv_by_day[date] = rng.sample(raw_rets, len(surv_rets))
        if null_surv_by_day:
            lift_res = day_paired_lift(null_surv_by_day, raw_by_day)
            if lift_res["winrate_lift_avg"] is not None:
                nulls.append(lift_res["winrate_lift_avg"])
    return nulls


def fetch_index_bars():
    """baostock sh.000001 日K close（regime=MA20 斜率 gate）。"""
    import baostock as bs  # noqa: PLC0415
    bars = []
    try:
        bs.login()
        rs = bs.query_history_k_data_plus(
            "sh.000001", "date,close",
            start_date="2025-11-01", end_date="2026-09-05",
        )
        while rs.error_code == "0" and rs.next():
            d = rs.get_row_data()
            if d[1]:
                bars.append({"date": d[0], "close": float(d[1])})
        bs.logout()
    except Exception as e:  # noqa: BLE001
        print(f"[R8] fetch_index_bars failed: {e}")
    return bars


def compute_index_ma20_slope(index_bars):
    """regime=强势/震荡 helper：sh.000001 MA20 斜率>0 逐日。返 {date: bool}。

    MA20 斜率 = (ma20_now - ma20_prev) / ma20_prev。>0=上升趋势（H4 regime，非 close>MA20）。
    """
    closes = [float(b.get("close", 0)) for b in index_bars]
    dates = [b.get("date") for b in index_bars]
    ma20_list = []
    for i in range(len(index_bars)):
        if i < 19:
            ma20_list.append(None)
            continue
        ma20_list.append(sum(closes[i - 19:i + 1]) / 20)
    is_strong = {}
    for i in range(len(index_bars)):
        if i < 20 or ma20_list[i] is None or ma20_list[i - 1] is None or ma20_list[i - 1] == 0:
            is_strong[dates[i]] = False
            continue
        slope = (ma20_list[i] - ma20_list[i - 1]) / ma20_list[i - 1]
        is_strong[dates[i]] = slope > 0
    return is_strong


def run_low_absorption_c3_lift():
    """R8 主入口：逐(code,D) 算 raw/tight by_day → lift+permutation+walk-forward。"""
    cache = _load_kline_cache()
    if not cache:
        print("[R8] 无 kline cache")
        return {"error": "no cache"}
    index_bars = fetch_index_bars()
    is_strong = compute_index_ma20_slope(index_bars) if index_bars else {}

    raw_by_day = defaultdict(list)
    tight_by_day = defaultdict(list)
    raw_strong = defaultdict(list)
    tight_strong = defaultdict(list)
    n_events = 0

    for code, bars in cache.items():
        if not bars or len(bars) < 24:
            continue
        for d_idx in range(20, len(bars) - 4):
            D = bars[d_idx].get("date")
            pat = scan_patterns(code, bars[:d_idx + 1], sector_bars=None)  # 切片 gotcha
            c1 = pat.ma5_proximity is not None and pat.ma5_proximity <= 3
            c2 = pat.ma_bullish is True
            if not (c1 and c2):
                continue
            sd1 = bars[d_idx + 1].get("date")  # signal_date=D+1，入场 D+2 open
            raw_sim = simulate_holding(bars, sd1, *DEFAULT_PATH_PARAMS)
            if raw_sim is None:
                continue
            n_events += 1
            ret = raw_sim["return_pct"]
            raw_by_day[D].append(ret)
            strong = is_strong.get(D, False)
            if strong:
                raw_strong[D].append(ret)
            c3 = pat.volume_breakout_ratio is not None and pat.volume_breakout_ratio < C3_THRESHOLD
            if c3:
                tight_by_day[D].append(ret)  # ⊆raw 同 ret
                if strong:
                    tight_strong[D].append(ret)

    print(f"[R8] low_absorption 事件 {n_events}, raw days={len(raw_by_day)}")

    results = {}
    arms = [("tight", tight_by_day)]
    for name, surv in arms:
        obs = day_paired_lift(surv, raw_by_day)
        nulls = day_cluster_permutation(surv, raw_by_day)
        obs_lift = obs["winrate_lift_avg"]
        p = (sum(1 for n in nulls if n >= obs_lift) / len(nulls)) if nulls else 1.0
        verdict = four_state(obs_lift, obs["surv_n_pooled"])
        results[name] = {
            "lift": obs_lift, "n": obs["surv_n_pooled"], "p_value": round(p, 4),
            "alpha_adj": ALPHA_ADJ, "verdict": verdict,
            "is_significant": p < ALPHA_ADJ,
        }
        print(f"  {name}: lift={obs_lift} n={obs['surv_n_pooled']} p={p:.4f} "
              f"verdict={verdict} sig={p < ALPHA_ADJ}")

    # regime=强势/震荡 subset (H4)
    results_strong = {}
    obs_s = day_paired_lift(tight_strong, raw_strong)
    nulls_s = day_cluster_permutation(tight_strong, raw_strong)
    obs_lift_s = obs_s["winrate_lift_avg"]
    p_s = (sum(1 for n in nulls_s if n >= obs_lift_s) / len(nulls_s)) if nulls_s else 1.0
    results_strong["tight"] = {
        "lift": obs_lift_s, "n": obs_s["surv_n_pooled"], "p_value": round(p_s, 4),
        "is_significant": p_s < ALPHA_ADJ,
    }

    # rolling walk-forward（train 不优化用冻结 C3=1.0）
    all_dates = sorted(raw_by_day.keys())
    wf_results = []
    for start in range(0, max(0, len(all_dates) - WALK_TRAIN - WALK_TEST + 1), WALK_STEP):
        test_dates = set(all_dates[start + WALK_TRAIN:start + WALK_TRAIN + WALK_TEST])
        if not test_dates:
            continue
        for name, surv in arms:
            test_surv = {d: r for d, r in surv.items() if d in test_dates}
            test_raw = {d: r for d, r in raw_by_day.items() if d in test_dates}
            if test_surv and test_raw:
                wf_obs = day_paired_lift(test_surv, test_raw)
                wf_results.append({
                    "window_start": start, "arm": name,
                    "test_lift": wf_obs["winrate_lift_avg"],
                    "test_n": wf_obs["surv_n_pooled"],
                })

    matrix = {
        "pre_register_commit": "74295b9",
        "params": {
            "c3": C3_THRESHOLD, "path": list(DEFAULT_PATH_PARAMS),
            "alpha_adj": ALPHA_ADJ, "n_perm": N_PERM, "null_model": "within-day survivor resampling",
        },
        "n_events": n_events,
        "overall": results,
        "regime_strong": results_strong,
        "walk_forward_windows": wf_results,
        "note": ("H4 C3 缩量 vs raw(C1+C2); day_paired_lift 非池化; within-day survivor resampling null; "
                 "Bonferroni K=8; rolling walk-forward; regime=MA20 斜率>0; 无 D+1 确认(非 platform)"),
    }
    out_dir = Path(ROOT / "backend" / ".scratch" / "s153-low-absorption-c3-lift")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "matrix.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[R8] matrix saved: {out_path}")
    return matrix


if __name__ == "__main__":
    run_low_absorption_c3_lift()
