"""S017 T16 — CROSS-SECTIONAL panel real run (the short_sector task as meant).

A-share short_sector is cross-sectional stock selection: among the universe,
which names outperform the index over the next H days. The single-index
direction-prediction variant plateaus ~46-49% (random walk); this panel
variant is the one the spec's 51-55% expectation refers to.

NO-LOOK-AHEAD AUDIT (per "杜绝引入未来函数"):
  * Stock features at date t use only that stock's kline up to and including t.
  * Index (benchmark) return for the label is close[t+H]/close[t]-1 — the
    label uses future close only as the prediction TARGET, never as a feature.
  * Panel walk-forward: unique trading dates; train window = the
    TRAIN_DAYS dates ending GAP(=embargo 5 + purge 3 = 8) before the test
    window start T. Last train date = T-8; its forward label uses close[T-5]
    which is < T -> train labels never touch test features (disjoint close
    ranges). Test features use close <= test_date >= T.
  * Samples whose t+H is unavailable (last H dates) are DROPPED, not faked.

Universe: 20 liquid large-caps (fixed 6-digit codes). Benchmark: sh000300.
Features (6, all <= t): short_term_reversal, abnormal_turnover, momentum_20d,
realized_vol_5d, day_of_week, is_month_end. Macro/external/fund_flow/limitup/
seat/sentiment/text still DEFERRED (not faked).
"""
from __future__ import annotations

import time
import warnings
from datetime import datetime

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import akshare as ak

import astock  # 多源 kline 门面（baidu→sina→mootdx→akshare 回退，不绑单源）

from predict.features.behavior import short_term_reversal_ret, abnormal_turnover_ratio
from predict.models.ensemble import SoftVoteEnsemble
from predict.evaluate import win_rate, LEAKAGE_WIN_RATE_THRESHOLD

SYMBOL_INDEX = "sh000300"
UNIVERSE = [
    "600519", "000858", "600036", "601318", "000333", "600276", "002594",
    "600030", "000725", "601166", "002475", "600009", "601888", "000651",
    "600690", "000568", "002271", "601012", "600887", "000063",
]
H = 3
TRAIN_DAYS = 60      # ~3 months of panel training per fold
TEST_DAYS = 5
STEP_DAYS = 10
GAP = 8              # embargo(5)+purge(3)
LOOKBACK = 20        # max feature lookback (momentum_20d)
START = "20240801"
END = "20260730"
# dashed 形式供多源解析器返回的 "YYYY-MM-DD" 日期过滤
_START_DASH, _END_DASH = "2024-08-01", "2026-07-30"


# ── fetch ──────────────────────────────────────────────────────────────

def fetch_stock(code: str) -> dict[str, dict]:
    """多源异构取个股日K线（``astock.kline_multi``：baidu→sina→mootdx→akshare
    回退）。**不绑单源、不重试-burst**——不同网络环境不同源可达，解析器自适应；
    重试-burst 会触发东财限流升级封 IP，故单次取、源失败即换下一源。返
    ``{date: {close, vol}}``，全源失败返 ``{}``（消费者按空剔除，诚实无数据）。

    **统一复权口径**：传 ``adjust="qfq"``——只走原生前复权源（百度/akshare），
    不回退 raw 源（新浪/mootdx）。混用口径会污染收益特征与标签（除权日 raw 序列
    单日假跌、历史价虚高 7-14%→short_term_reversal/momentum_20d/realized_vol 失真）。
    百度 qfq 已 2026-07-31 实测确认（茅台 2018 收盘 413 vs 新浪 raw 730，最新日
    收敛→qfq 签名）。无 qfq 源可达即诚实返空，该股剔除。见
    [[vibe-research-s017-resume-handoff]] S008 统一复权层。
    """
    raw_bars, src = astock.kline_multi(code, adjust="qfq")
    if src:
        print(f"      [{src}]")
    bars: dict[str, dict] = {}
    for b in raw_bars:
        d = b.get("date")
        if not d or d < _START_DASH or d > _END_DASH:
            continue
        bars[d] = {"close": b.get("close"), "vol": b.get("volume")}
    return bars


def fetch_index() -> dict[str, dict]:
    df = ak.stock_zh_index_daily(symbol=SYMBOL_INDEX)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df[(df["date"] >= "2024-08-01") & (df["date"] <= "2026-07-30")]
    return {str(r["date"]): {"close": float(r["close"])} for _, r in df.iterrows()}


# ── features ──────────────────────────────────────────────────────────

def stock_features(hist: list[dict], date: str, date_str: str, last_in_month: bool):
    """6 features from this stock's kline up to and including `date`. None if insufficient."""
    if len(hist) < LOOKBACK + 1:
        return None
    bars = [{"close": h["close"]} for h in hist]
    vols = [h["vol"] for h in hist]
    f0 = short_term_reversal_ret(bars, window=5)
    f1 = abnormal_turnover_ratio(vols, avg_window=5)
    f2 = _momentum(hist, 20)
    f3 = _realized_vol(hist, 5)
    if f0 is None or f1 is None or f2 is None or f3 is None or f1 == 0 or not np.isfinite(f1):
        return None
    f4 = float(datetime.strptime(date_str, "%Y-%m-%d").weekday())
    f5 = 1.0 if last_in_month else 0.0
    return [float(f0), float(f1), float(f2), float(f3), f4, f5]


def _momentum(hist, w):
    c = [h["close"] for h in hist]
    if len(c) < w + 1:
        return None
    return (c[-1] - c[-1 - w]) / c[-1 - w] * 100


def _realized_vol(hist, w):
    c = np.array([h["close"] for h in hist[-(w + 1):]], dtype=float)
    if len(c) < w + 1:
        return None
    rets = np.diff(c) / c[:-1]
    return float(np.std(rets))


# ── panel build ───────────────────────────────────────────────────────

def build_panel(stocks, index, dates_all):
    """Return (dates, X, y, stock_ids) panel over common trading dates.

    Each row = (stock, date). Features <= date; label = fwd-H relative
    outperformance vs index. Drops samples where fwd-H unavailable.
    """
    common = sorted(set(dates_all))
    # precompute per-stock history lists for O(n) feature build
    stock_hist = {c: [] for c in stocks}  # growing list of bars up to current date
    stock_dates = {c: sorted(stocks[c].keys()) for c in stocks}

    rows, ylist, date_list, sid_list = [], [], [], []
    for di, d in enumerate(common):
        last_in_month = (di + 1 < len(common)) and (common[di + 1][:7] != d[:7])
        # stock fwd return vs index fwd return
        idx_close_now = index.get(d, {}).get("close")
        idx_close_fwd = index.get(common[di + H], {}).get("close") if di + H < len(common) else None
        rel_label_ok = (idx_close_now is not None and idx_close_fwd is not None)
        for c in stocks:
            # advance this stock's history to date d
            hd = stocks[c].get(d)
            if hd is None:
                continue
            stock_hist[c].append(hd)
            feat = stock_features(stock_hist[c], d, d, last_in_month)
            if feat is None:
                continue
            if not rel_label_ok:
                # fwd target unavailable for this date -> skip (no fabrication)
                continue
            st_close = hd["close"]
            st_fwd = stocks[c].get(common[di + H], {}).get("close") if di + H < len(common) else None
            if st_fwd is None:
                continue
            st_ret = (st_fwd - st_close) / st_close
            idx_ret = (idx_close_fwd - idx_close_now) / idx_close_now
            label = 1 if st_ret > idx_ret else 0
            rows.append(feat)
            ylist.append(label)
            date_list.append(d)
            sid_list.append(c)
    return date_list, np.array(rows, dtype=float), np.array(ylist, dtype=int), sid_list


# ── walk-forward panel ────────────────────────────────────────────────

def panel_walk_forward(dates, X, y, train_days=TRAIN_DAYS, test_days=TEST_DAYS,
                       step_days=STEP_DAYS, gap=GAP):
    """Yield (train_idx, test_idx) over the panel, date-aligned."""
    uniq = sorted(set(dates))
    pos_by_date = {d: [i for i, dd in enumerate(dates) if dd == d] for d in uniq}
    folds = []
    t = train_days + gap
    while t + test_days <= len(uniq):
        tr_dates = set(uniq[t - gap - train_days: t - gap])
        te_dates = set(uniq[t: t + test_days])
        tr = [i for i, dd in enumerate(dates) if dd in tr_dates]
        te = [i for i, dd in enumerate(dates) if dd in te_dates]
        if tr and te:
            folds.append((tr, te, uniq[t], uniq[t + test_days - 1]))
        t += step_days
    return folds


def main():
    print(f"akshare {ak.__version__}; benchmark {SYMBOL_INDEX}; universe {len(UNIVERSE)} stocks")
    print(f"  fetch window {START}..{END}; H={H} train_days={TRAIN_DAYS} test_days={TEST_DAYS} step={STEP_DAYS} gap={GAP}")
    print("  fetching index + stocks (qfq, unified caliber)...")
    index = fetch_index()
    stocks = {}
    for c in UNIVERSE:
        try:
            stocks[c] = fetch_stock(c)
            print(f"    {c}: {len(stocks[c])} bars")
        except Exception as e:
            print(f"    {c}: FETCH FAIL {repr(e)[:80]}")
        time.sleep(3)  # inter-stock spacing — avoid eastmoney rate-limit escalation
    stocks = {c: v for c, v in stocks.items() if len(v) > LOOKBACK + H + 1}
    print(f"  usable universe: {len(stocks)} stocks")

    all_dates = set(index.keys())
    for c, v in stocks.items():
        all_dates &= set(v.keys())
    print(f"  common trading dates: {len(all_dates)}")

    dates, X, y, sids = build_panel(stocks, index, all_dates)
    print(f"  panel rows: {len(y)}  X.shape={X.shape}  pos_rate={y.mean():.3f}")
    if len(y) < 200:
        print("  too few panel rows — abort")
        return

    folds = panel_walk_forward(dates, X, y)
    print(f"  feasible folds: {len(folds)}")
    if not folds:
        print("  no fold feasible — abort")
        return

    wrs = []
    for tr, te, ts0, ts1 in folds:
        e = SoftVoteEnsemble().fit(X[tr], y[tr])
        proba = e.predict_proba(X[te])
        yp = (proba[:, 1] >= 0.5).astype(int) if proba.ndim == 2 else (proba >= 0.5).astype(int)
        wrs.append(win_rate(y[te], yp))
    agg = float(np.mean(wrs))
    # also a baseline: predict majority class
    base = max(y.mean(), 1 - y.mean())
    print(f"\n  [aggregated cross-sectional OOS] folds={len(wrs)} mean_win_rate={agg:.3f} "
          f"(majority baseline={base:.3f})  leakage_flag(>{LEAKAGE_WIN_RATE_THRESHOLD:.0%})={agg > LEAKAGE_WIN_RATE_THRESHOLD}")

    # top-quintile vs bottom-quintile realized relative return (alpha check)
    last_tr, last_te, _, _ = folds[-1]
    e = SoftVoteEnsemble().fit(X[last_tr], y[last_tr])
    proba = e.predict_proba(X[last_te])[:, 1]
    te_dates = [dates[i] for i in last_te]
    # rank test samples by proba, split into top/bottom quintile, measure actual outperformance rate
    order = np.argsort(proba)
    n = len(order)
    top = order[int(0.8 * n):]
    bot = order[: int(0.2 * n)]
    print(f"  [last fold quintile spread] top-q outperform rate={y[last_te][top].mean():.3f}  "
          f"bottom-q outperform rate={y[last_te][bot].mean():.3f}  (positive spread => alpha)")

    print(f"\n  Backends (last fold): {e.backends()}")
    print("  NOTE: last-fold quintile spread above is NOT an alpha claim — single fold,")
    print("  tiny sample, rising-market biased. Trust the aggregated OOS vs majority")
    print("  baseline across all folds, not the last-fold quintile.")
    print("  Data: stocks via baidu qfq (adjust=\"qfq\" caliber-unified, no raw fallback);")
    print("  index via akshare stock_zh_index_daily. Empty-bar stocks are dropped, not faked.")


if __name__ == "__main__":
    main()
