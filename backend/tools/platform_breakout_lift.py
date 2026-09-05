# -*- coding: utf-8 -*-
"""S153 R7：platform_breakout 验证 harness——H1-H3 预注册交互假设验证。

H1 紧度（amplitude<=6.0）/ H2 D+1 收盘确认（bars[D+1].high>cons_max_high→D+2 入场，无 look-ahead）/
H3 双过滤 vs raw（C1+C2 无 C3/确认）。day_paired_lift 非池化 + day_cluster_permutation
within-day survivor resampling + rolling walk-forward + Bonferroni K=8 α_adj=0.00625。
target=path-winrate（signal_date=D+1, 入场 D+2 open, DEFAULT_PATH_PARAMS -3/+8/3）。
复用 first_board_layer_lift.day_paired_lift/four_state/_winrate +
first_board_premium_baseline._load_kline_cache + kline_returns.simulate_holding_with_confirm +
pattern_scan.scan_patterns。pre-register 冻结 commit 74295b9（null=within-day survivor resampling,
阈值 amplitude<=6.0, train 不优化）。
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
from strategies.kline_returns import simulate_holding, simulate_holding_with_confirm  # noqa: E402
from strategies.pattern_scan import scan_patterns  # noqa: E402

# 预注册冻结（commit 74295b9）
TIGHT_THRESHOLD = 6.0           # H1 紧度 amplitude<=6.0
DEFAULT_PATH_PARAMS = (-3.0, 8.0, 3)  # stop/take/max_hold
ALPHA_ADJ = 0.05 / 8           # Bonferroni K=8
N_PERM = 2000
PERM_SEED = 42
WALK_TRAIN = 100               # rolling walk-forward train 日
WALK_TEST = 20                 # test 日
WALK_STEP = 20                 # 前移


def day_cluster_permutation(surv_by_day, raw_by_day, n_perm=N_PERM, seed=PERM_SEED):
    """within-day survivor resampling null 分布（pre-register 冻结 commit 74295b9）。

    surv⊆raw 同 ret，逐日内随机选同大小子集当 survivor 重算 day_paired_lift，返 null lift 列表。
    observed lift 须在 null 分布 P95 以上。filter-edge 锐检验（非 date-shuffle，后者与
    day_paired_lift 去池化重复）。
    """
    rng = random.Random(seed)
    nulls = []
    for _ in range(n_perm):
        null_surv_by_day = {}
        for date, raw_rets in raw_by_day.items():
            surv_rets = surv_by_day.get(date, [])
            if not surv_rets or len(raw_rets) < len(surv_rets):
                continue
            null_surv_by_day[date] = rng.sample(raw_rets, len(surv_rets))  # 同大小随机子集
        if null_surv_by_day:
            lift_res = day_paired_lift(null_surv_by_day, raw_by_day)
            if lift_res["winrate_lift_avg"] is not None:
                nulls.append(lift_res["winrate_lift_avg"])
    return nulls


def fetch_index_bars():
    """baostock sh.000001 日K close（regime=bull MA20 gate，不限流）。"""
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
        print(f"[R7] fetch_index_bars failed: {e}")
    return bars


def compute_index_ma20(index_bars):
    """regime=bull helper：sh.000001 close>MA20 逐日。返 {date: bool_is_bull}。"""
    closes = [float(b.get("close", 0)) for b in index_bars]
    dates = [b.get("date") for b in index_bars]
    is_bull = {}
    for i in range(len(index_bars)):
        if i < 19:
            is_bull[dates[i]] = False
            continue
        ma20 = sum(closes[i - 19:i + 1]) / 20
        is_bull[dates[i]] = closes[i] > ma20
    return is_bull


def run_platform_breakout_lift():
    """R7 主入口：逐(code,D) 算 raw/tight/confirm/both by_day → lift+permutation+walk-forward。"""
    cache = _load_kline_cache()
    if not cache:
        print("[R7] 无 kline cache")
        return {"error": "no cache"}
    index_bars = fetch_index_bars()
    is_bull = compute_index_ma20(index_bars) if index_bars else {}

    raw_by_day = defaultdict(list)
    tight_by_day = defaultdict(list)
    confirm_by_day = defaultdict(list)
    both_by_day = defaultdict(list)
    raw_bull, tight_bull, confirm_bull, both_bull = (defaultdict(list) for _ in range(4))
    n_events = 0

    for code, bars in cache.items():
        if not bars or len(bars) < 24:
            continue
        for d_idx in range(20, len(bars) - 4):  # ≥20 回看 ∧ ≥4 前向（bars 非等长）
            D = bars[d_idx].get("date")
            pat = scan_patterns(code, bars[:d_idx + 1], sector_bars=None)  # 切片 gotcha
            c1 = pat.consolidation_days is not None and pat.consolidation_days >= 5
            c2 = pat.volume_breakout_ratio is not None and pat.volume_breakout_ratio > 2
            if not (c1 and c2):
                continue
            sd1 = bars[d_idx + 1].get("date")  # signal_date=D+1，入场 D+2 open
            raw_sim = simulate_holding(bars, sd1, *DEFAULT_PATH_PARAMS)  # raw arm D+2 入场
            if raw_sim is None:
                continue
            n_events += 1
            ret = raw_sim["return_pct"]
            raw_by_day[D].append(ret)
            bull = is_bull.get(D, False)
            if bull:
                raw_bull[D].append(ret)
            c3 = pat.consolidation_amplitude is not None and pat.consolidation_amplitude <= TIGHT_THRESHOLD
            if c3:
                tight_by_day[D].append(ret)  # ⊆raw 同 ret
                if bull:
                    tight_bull[D].append(ret)
            cmh = pat.consolidation_max_high
            conf_sim = simulate_holding_with_confirm(bars, sd1, cmh, *DEFAULT_PATH_PARAMS)
            if conf_sim is not None:
                confirm_by_day[D].append(conf_sim["return_pct"])
                if bull:
                    confirm_bull[D].append(conf_sim["return_pct"])
                if c3:
                    both_by_day[D].append(conf_sim["return_pct"])
                    if bull:
                        both_bull[D].append(conf_sim["return_pct"])

    print(f"[R7] platform_breakout 事件 {n_events}, raw days={len(raw_by_day)}")

    results = {}
    arms = [("tight", tight_by_day), ("confirm", confirm_by_day), ("both", both_by_day)]
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

    # regime=bull subset (H1-3)
    results_bull = {}
    for name, surv in [("tight", tight_bull), ("confirm", confirm_bull), ("both", both_bull)]:
        obs = day_paired_lift(surv, raw_bull)
        nulls = day_cluster_permutation(surv, raw_bull)
        obs_lift = obs["winrate_lift_avg"]
        p = (sum(1 for n in nulls if n >= obs_lift) / len(nulls)) if nulls else 1.0
        results_bull[name] = {
            "lift": obs_lift, "n": obs["surv_n_pooled"], "p_value": round(p, 4),
            "is_significant": p < ALPHA_ADJ,
        }

    # rolling walk-forward（按 date 切窗，逐窗 test 段 day_paired_lift 看 OOS 稳定，train 不优化用冻结 6.0）
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
            "tight": TIGHT_THRESHOLD, "path": list(DEFAULT_PATH_PARAMS),
            "alpha_adj": ALPHA_ADJ, "n_perm": N_PERM, "null_model": "within-day survivor resampling",
        },
        "n_events": n_events,
        "overall": results,
        "regime_bull": results_bull,
        "walk_forward_windows": wf_results,
        "note": ("H1-H3 vs raw; day_paired_lift 非池化; within-day survivor resampling null; "
                 "Bonferroni K=8 α_adj=0.00625; rolling walk-forward train 不优化; regime=bull subset"),
    }
    out_dir = Path(ROOT / "backend" / ".scratch" / "s153-platform-breakout-lift")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "matrix.json"
    out_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[R7] matrix saved: {out_path}")
    return matrix


if __name__ == "__main__":
    run_platform_breakout_lift()
