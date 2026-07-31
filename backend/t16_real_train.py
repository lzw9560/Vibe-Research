"""S017 T16 — real out-of-sample short_sector run, expanded real features.

NO-LOOK-AHEAD AUDIT (per "杜绝引入未来函数"):
  * Every feature at trading date t uses only data with timestamp <= t:
      - kline features: bars[:t+1] (close/vol up to and including t)
      - calendar features: date of t itself (known)
      - macro features: Fred value forward-filled to the most recent
        observation <= t (never a future observation)
  * Forward label = sign(close[t+H] - close[t]); samples where t+H is
    unavailable are DROPPED, never fabricated.
  * roll_retrain embargo(5)+purge(3)=8-day gap: last train sample at t-8,
    its forward label uses close[t-5] < test start t -> train labels never
    touch test features. No cross-boundary leakage.

Real data sources (all verified reachable on the remote, 2026-07-30):
  - akshare sh000300 daily kline (kline-derived features)
  - akshare trading calendar (calendar features)
  - FRED DGS10 (10Y) + DTWEXBGS (DXY) via api.stlouisfed.org (macro features)

Feature SUBSET (8 of 22) on a single index series — real-data smoke of the
Linux model stack, NOT the full S008/S018 panel pipeline. Sources NOT wired
here (fund_flow 120d limit + flaky, auction/yesterday_limit/day_trip via
limitup_sti+龙虎榜, sentiment, external, text) are deferred — not faked.
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

import numpy as np
import akshare as ak
import urllib.request

from predict.features.behavior import short_term_reversal_ret, abnormal_turnover_ratio
from predict.models.ensemble import SoftVoteEnsemble
from predict.train import roll_retrain, train_short_sector, TrainConfig
from predict.evaluate import evaluate_short_sector, win_rate, LEAKAGE_WIN_RATE_THRESHOLD

SYMBOL = "sh000300"
H = 3
FEAT_WINDOW = 5
MOM_WINDOW = 20
VOL_WINDOW = 5
N_TAIL_DAYS = 500
FRED_KEY_PATH = "/home/vdb/turing/code/Vibe-Research/.vibe-research/fred_api_key"


# ── data fetch ─────────────────────────────────────────────────────────

def fetch_kline() -> list[dict]:
    df = ak.stock_zh_index_daily(symbol=SYMBOL).tail(N_TAIL_DAYS).reset_index(drop=True)
    return [{"date": str(r["date"]), "close": float(r["close"]), "volume": float(r["volume"])}
            for _, r in df.iterrows()]


def fetch_fred(series_id: str, start: str, end: str, api_key: str) -> dict[str, float]:
    """Return {calendar_date: value} for a FRED series, forward-fillable."""
    url = (f"https://api.stlouisfed.org/fred/series/observations?"
           f"series_id={series_id}&api_key={api_key}&file_type=json"
           f"&observation_start={start}&observation_end={end}")
    with urllib.request.urlopen(url, timeout=20) as r:
        d = json.loads(r.read())
    out: dict[str, float] = {}
    for obs in d.get("observations", []):
        v = obs["value"]
        try:
            out[obs["date"]] = float(v)
        except (ValueError, TypeError):
            continue  # "." missing
    return out


def build_macro_map(bars: list[dict], api_key: str) -> dict[str, dict[str, float]]:
    """Build per-trading-date macro values (forward-filled to <= t)."""
    start = bars[0]["date"].replace("-", "")
    end = bars[-1]["date"].replace("-", "")
    dgs10 = fetch_fred("DGS10", start, end, api_key)
    dxy = fetch_fred("DTWEXBGS", start, end, api_key)
    # sorted calendar dates
    dgs_dates = sorted(dgs10)
    dxy_dates = sorted(dxy)
    macro: dict[str, dict[str, float]] = {}
    for b in bars:
        t = b["date"]
        g = _latest_le(dgs10, dgs_dates, t)
        x = _latest_le(dxy, dxy_dates, t)
        macro[t] = {"dgs10": g, "dxy": x}
    return macro


def _latest_le(series: dict[str, float], sorted_dates: list[str], t: str) -> float:
    """Forward-fill: most recent value with date **strictly before** t.

    用 ``bisect_left`` - 1（严格 < t），不含 ``obs_date == t`` 的观测：FRED
    DGS10 标 d 日的值在北京时 d+1 ~04:00 才发布，A 股 d 日 15:00 收盘时不可知，
    含同日观测即 ~1 日 look-ahead（2026-07-31 对抗验证确认）。改 ``bisect_right``
    为 ``bisect_left`` 闭合此泄漏。
    """
    import bisect
    i = bisect.bisect_left(sorted_dates, t) - 1
    if i < 0:
        return float("nan")
    return series[sorted_dates[i]]


# ── features ───────────────────────────────────────────────────────────

def build_features(bars: list[dict], macro: dict[str, dict[str, float]]):
    """(dates, X, valid_idx). 8 features, all from data <= t."""
    closes = [b["close"] for b in bars]
    vols = [b["volume"] for b in bars]
    dates, rows, valid_idx = [], [], []
    for t in range(len(bars)):
        sub_bars = bars[: t + 1]
        sub_closes = closes[: t + 1]
        sub_vols = vols[: t + 1]
        d = bars[t]["date"]

        f0 = short_term_reversal_ret(sub_bars, window=FEAT_WINDOW)        # 5d ret %
        f1 = abnormal_turnover_ratio(sub_vols, avg_window=VOL_WINDOW)      # vol ratio
        f2 = _momentum(sub_closes, MOM_WINDOW)                            # 20d ret %
        f3 = _realized_vol(sub_closes, VOL_WINDOW)                        # 5d std of rets
        f4 = _day_of_week(d)                                              # 0..4
        f5 = _is_month_end(d, bars, t)                                    # 0/1
        m = macro.get(d, {})
        f6 = _macro_change(macro, bars, t, "dgs10")                       # 5d chg
        f7 = _macro_change(macro, bars, t, "dxy")                         # 5d chg

        if any(v is None for v in (f0, f1, f2, f3)):
            continue
        if not (np.isfinite(f1) and f1 != 0):
            continue
        rows.append([float(f0), float(f1), float(f2), float(f3),
                     float(f4), float(f5), float(f6) if np.isfinite(f6) else 0.0,
                     float(f7) if np.isfinite(f7) else 0.0])
        dates.append(d)
        valid_idx.append(t)
    return dates, np.array(rows, dtype=float), valid_idx


def _momentum(closes: list[float], w: int) -> float | None:
    if len(closes) < w + 1:
        return None
    return (closes[-1] - closes[-1 - w]) / closes[-1 - w] * 100


def _realized_vol(closes: list[float], w: int) -> float | None:
    if len(closes) < w + 1:
        return None
    rets = np.diff(closes[-(w + 1):]) / np.array(closes[-(w + 1):-1])
    return float(np.std(rets))


def _day_of_week(d: str) -> float:
    return float(datetime.strptime(d, "%Y-%m-%d").weekday())


def _is_month_end(d: str, bars: list[dict], t: int) -> float:
    # last trading day of the month flag
    cur = d[:7]
    nxt = bars[t + 1]["date"][:7] if t + 1 < len(bars) else cur
    return 1.0 if nxt != cur else 0.0


def _macro_change(macro, bars, t, key) -> float:
    """5-trading-day change of a macro series (forward-filled <= t)."""
    if t < 5:
        return float("nan")
    cur = macro.get(bars[t]["date"], {}).get(key, float("nan"))
    prev = macro.get(bars[t - 5]["date"], {}).get(key, float("nan"))
    if not (np.isfinite(cur) and np.isfinite(prev)) or prev == 0:
        return float("nan")
    return cur - prev


# ── labels ─────────────────────────────────────────────────────────────

def label_past(bars, idx):
    # 过去标签窗口与所有特征窗口**不相交**（特征最长 MOM_WINDOW=20，窗口 [idx-20, idx]）。
    # 用 [idx-MOM_WINDOW-H, idx-MOM_WINDOW]（3 日收益结束于 20 日前）——相邻不重叠，
    # 闭合 2026-07-31 对抗验证确认的"行内重叠"泄漏：原 [idx-3, idx] 是特征 f0
    # 窗口 [idx-5, idx] 的字面子区间，close[idx]-close[idx-5] 含 (close[idx]-close[idx-3])
    # +（close[idx-3]-close[idx-5])，标签分子是特征机械子分量 → 0.591 虚高。
    # 改后若 0.591 坍回 ≈0.5（机会），即证 0.591 纯属重叠非预测力。
    end = idx - MOM_WINDOW
    start = end - H
    if start < 0:
        return None
    c = bars[end]["close"]
    return 1 if (c - bars[start]["close"]) / bars[start]["close"] > 0 else 0


def label_forward(bars, idx):
    if idx + H >= len(bars):
        return None
    c = bars[idx]["close"]
    return 1 if (bars[idx + H]["close"] - c) / c > 0 else 0


def assemble(bars, dates, X, valid_idx, label_fn):
    keep, y = [], []
    for i, bidx in enumerate(valid_idx):
        lab = label_fn(bars, bidx)
        if lab is None:
            continue
        keep.append(i)
        y.append(lab)
    if not keep:
        return [], np.empty((0, X.shape[1])), np.empty(0, dtype=int)
    return [dates[i] for i in keep], X[keep], np.array(y, dtype=int)


# ── run ────────────────────────────────────────────────────────────────

def run_variant(name, dates, X, y, cfg: TrainConfig):
    print(f"\n{'=' * 72}\nVariant {name}\n  n_samples={len(y)}  pos_rate={y.mean():.3f}  n_features={X.shape[1]}")
    if len(y) < 40:
        print("  too few samples — skipping")
        return
    splits = roll_retrain(dates, train_size=cfg.train_size, test_size=cfg.test_size,
                          step_days=cfg.step_days, embargo_days=cfg.embargo_days,
                          purge_days=cfg.purge_days)
    print(f"  feasible folds={len(splits)} (train_size={cfg.train_size} test_size={cfg.test_size} gap={cfg.embargo_days + cfg.purge_days})")
    if not splits:
        print("  no fold feasible — skipping")
        return

    art = train_short_sector(X, y, dates, config=cfg)
    last = art["split"]
    ev = evaluate_short_sector(art, X[list(last.test_idx)], y[list(last.test_idx)])
    print(f"  [train_short_sector] backends={art['backends']} regime={art['regime'].backend()}")
    print(f"  [last-fold OOS] test {last.test_dates[0]}..{last.test_dates[-1]} "
          f"({len(last.test_idx)} pts): win_rate={ev['win_rate']:.3f} auc={ev['auc']:.3f} "
          f"leakage_flag={ev['leakage_flag']}")

    wrs = []
    for sp in splits:
        tr, te = list(sp.train_idx), list(sp.test_idx)
        if not tr or not te:
            continue
        e = SoftVoteEnsemble().fit(X[tr], y[tr])
        proba = e.predict_proba(X[te])
        yp = (proba[:, 1] >= 0.5).astype(int) if proba.ndim == 2 else (proba >= 0.5).astype(int)
        wrs.append(win_rate(y[te], yp))
    agg = float(np.mean(wrs)) if wrs else float("nan")
    print(f"  [aggregated OOS] folds_evaluated={len(wrs)} mean_win_rate={agg:.3f} "
          f"leakage_flag(>{LEAKAGE_WIN_RATE_THRESHOLD:.0%})={agg > LEAKAGE_WIN_RATE_THRESHOLD}")


def main():
    print(f"akshare {ak.__version__}; fetching {SYMBOL} kline (tail {N_TAIL_DAYS})...")
    bars = fetch_kline()
    print(f"  fetched {len(bars)} bars: {bars[0]['date']} .. {bars[-1]['date']}")
    try:
        with open(FRED_KEY_PATH) as f:
            api_key = f.read().strip()
        print(f"  FRED key present; fetching DGS10+DTWEXBGS...")
        macro = build_macro_map(bars, api_key)
        print(f"  macro dates covered: {len(macro)}")
    except Exception as e:
        print(f"  FRED unavailable ({repr(e)[:120]}); macro features zeroed")
        macro = {b["date"]: {"dgs10": float("nan"), "dxy": float("nan")} for b in bars}

    cfg = TrainConfig()
    dates, X, valid_idx = build_features(bars, macro)
    print(f"  feature rows (post lookback): {len(X)}  X.shape={X.shape}")

    for name, fn in (("A: past-3d label, window disjoint from features (leakage-fixed)", label_past),
                     ("B: forward-3d label (honest target)", label_forward)):
        d, Xs, ys = assemble(bars, dates, X, valid_idx, fn)
        run_variant(name, d, Xs, ys, cfg)

    print(f"\n{'=' * 72}\nFeatures (8, all data <= t): short_term_reversal, abnormal_turnover,\n"
          f"  momentum_20d, realized_vol_5d, day_of_week, is_month_end, dgs10_chg5d, dxy_chg5d.\n"
          f"Deferred (not faked): fund_flow(120d limit+flaky), auction/yesterday_limit/day_trip\n"
          f"  (limitup_sti+龙虎榜), sentiment, external, text — need S008 source work.")


if __name__ == "__main__":
    main()
