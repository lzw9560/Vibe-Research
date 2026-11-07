# -*- coding: utf-8 -*-
"""构建多因子 baseline 日收益序列 (mkt + SMB + UMD) — 残差 alpha OLS 归因的输入.

方法论 (residual-edge-analyzer, 第 6 种方法学):
  r_strategy = alpha + beta_mkt*mkt + beta_smb*SMB + beta_umd*UMD + residual
  alpha (截距) = 控所有因子后的残差 alpha (非 long-only EV, 非 single-factor CAPM).

为何新方法学: 之前 CAPM 只控市场单因子. 多因子 OLS 同时控 SMB+UMD,
能解 "size ≈ low-vol 非独立" (互相控制后还有独立 alpha 吗?).

本脚本只构建 **日频** 因子收益序列 (step 1-4), 不做回归 (回归在下游脚本):
  1. mkt  : sh.000001 上证综指日 pctChg (decimal, 含 2119 日)
  2. SMB  : 横截面 size long-short decile, 月度再平衡, 日频持有收益
            - size 代理 = log(20d 均成交额), 流动性代理非真市值 (需流通股本)
            - long = bottom decile (小盘/低换手), short = top decile (大盘/高换手)
  3. UMD  : Carhart 12-2 动量 long-short decile, 月度再平衡, 日频持有收益
            - signal = C[t-21]/C[t-252] - 1 (过去 12 月~1 月累计收益, 跳过最近 1 月)
            - long = top decile (winners), short = bottom decile (losers)
  4. HML  : BLOCKED — 无历史 PB/账面价值数据 (本地仅当前快照 PB, 无法月度 decile).
            按 task 允许 跳过. 输出 3 因子 baseline (mkt+SMB+UMD).

构造 (Fama-French daily factor 标准做法):
  - 月末再平衡: 每月最后一个交易日为 formation 日 R_k.
  - formation 收盘算 signal (no look-ahead: 用到 R_k 收盘价/成交额).
  - 持有期 (R_k, R_{k+1}]: 日收益 = EW(long 日收益) - EW(short 日收益),
    组合在持有期内固定不变 (constituents from R_k rebalance).
  - 首日收益 R_k+1 = C[R_k+1]/C[R_k] - 1 (formation 收盘为基准).
  - decile = 底/顶 10%, 腿内等权.
  - 横截面 winsorize 1%/99% 后排序 (防极端成交额投机股扭曲边界).
  - 流动性过滤: 20d 均成交额 >= 5000 万元 + formation 日 amount>0 (与项目 factor_zoo 一致).

诚实约束 (禁止外推 + 不臆造):
  - size 代理 = log(20d 均成交额) 是流动性/换手代理, 非真市值. 高成交额股 ≠ 大市值
    (可能是高换手投机股). 故本 SMB 实为 "低换手-高换手" 近似, 标注 caveat.
  - HML 跳过 = 不臆造 value 因子 (无 PB 不假装有). 3 因子 baseline 仍可解 size↔low-vol 非独立.
  - 散户可行性: long-short 需做空 (A股融券受限), 统计 baseline ≠ 可交易.
  - survivorship: 早期 (2018-2020) 横截面 264-766 来自非随机 backfill 子集; 小盘腿
    退市/ST 概率高 → unbalanced panel 对小盘腿有 survivorship bias.
  - 月末 close formation 假设收盘可成交 (标准 FF 约定, 微不现实但与 published factors 一致).
  - 输出仅供下游残差 alpha 回归, 非 "size/动量因子有 edge" 的结论.

输出: .vibe-research/factor_baselines.json
"""

from __future__ import annotations
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
INDEX_CACHE = DATA / "index_ohlc_cache.json"
OUT = DATA / "factor_baselines.json"

LIQ_AMT_FLOOR = 50_000_000.0  # 20d 均成交额 >= 5000 万元 (与 factor_zoo 一致)
SIZE_DAYS = 20  # size 信号回看窗
UMD_SHORT = 21  # 跳过最近 1 月 (~21 交易日)
UMD_LONG = 252  # 12 月回看 (~252 交易日)
MIN_DECILE_STOCKS = 5  # 腿内至少 5 只当日有收益才计
MIN_CROSS_SECTION = 20  # 再平衡日横截面 < 20 跳过


# ---------- data loading ----------


def scan_kline_dates() -> set[str]:
    """Quick pre-scan: all dates present in kline cache (for calendar alignment)."""
    conn = sqlite3.connect(str(KLINE_DB))
    dates: set[str] = set()
    for (bj,) in conn.execute("SELECT bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list):
            continue
        for b in bars:
            if isinstance(b, dict) and b.get("date"):
                dates.add(b["date"])
    conn.close()
    return dates


def load_calendar_and_index(kline_dates: set[str]) -> tuple[list[str], dict[str, float]]:
    """trading calendar = index dates ∩ kline dates (aligns market to stock-data window)
    + market daily decimal returns keyed to that calendar."""
    idx = json.loads(INDEX_CACHE.read_text())["sh.000001"]
    bars = [b for b in idx if isinstance(b, dict) and b.get("date") and b.get("pctChg") is not None]
    # intersect with kline dates so calendar matches the stock-data window (2018-2026, 2119 d)
    kept = [b for b in bars if b["date"] in kline_dates]
    kept.sort(key=lambda b: b["date"])
    calendar = [b["date"] for b in kept]
    mkt = {b["date"]: float(b["pctChg"]) / 100.0 for b in kept}
    return calendar, mkt


def load_panels(calendar: list[str]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build close[ncodes, ndates] + amount[ncodes, ndates], masked nan.
    Returns (close, amount, codes)."""
    di = {d: i for i, d in enumerate(calendar)}
    nd = len(calendar)
    # two passes: first collect per-code series to size the code list
    conn = sqlite3.connect(str(KLINE_DB))
    raw: list[tuple[str, dict[str, float], dict[str, float]]] = []
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list):
            continue
        closes: dict[str, float] = {}
        amts: dict[str, float] = {}
        for b in bars:
            if not isinstance(b, dict):
                continue
            d = b.get("date")
            if d is None or d not in di:
                continue
            c = b.get("close")
            a = b.get("amount")
            if c is not None and float(c) > 0:
                closes[d] = float(c)
            if a is not None and float(a) > 0:
                amts[d] = float(a)
        if closes:
            raw.append((code, closes, amts))
    conn.close()

    codes = [r[0] for r in raw]
    nc = len(codes)
    close = np.full((nc, nd), np.nan, dtype=np.float64)
    amount = np.full((nc, nd), np.nan, dtype=np.float64)
    for i, (_, cls, amt) in enumerate(raw):
        for d, c in cls.items():
            close[i, di[d]] = c
        for d, a in amt.items():
            amount[i, di[d]] = a
    return close, amount, codes


def daily_returns(close: np.ndarray) -> np.ndarray:
    """close-to-close daily decimal returns, nan where either side missing."""
    ret = np.full_like(close, np.nan)
    ret[:, 1:] = close[:, 1:] / close[:, :-1] - 1.0
    # zero out rows where prev was nan (np propagation already nan, but guard inf)
    ret[~np.isfinite(ret)] = np.nan
    return ret


# ---------- month-end rebalance dates ----------


def month_end_dates(calendar: list[str]) -> list[int]:
    """Indices of the last trading day of each calendar month."""
    out: list[int] = []
    for i, d in enumerate(calendar):
        # d like "2018-01-31"
        ym = d[:7]
        if i + 1 < len(calendar) and calendar[i + 1][:7] == ym:
            continue  # not the last in month
        out.append(i)
    return out


# ---------- decile formation ----------


def winsorize(vals: np.ndarray, lo: float = 0.01, hi: float = 0.99) -> np.ndarray:
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        return vals
    qlo, qhi = np.quantile(finite, [lo, hi])
    return np.clip(vals, qlo, qhi)


def form_decile_legs(signal: np.ndarray, long_is_top: bool) -> tuple[np.ndarray, np.ndarray]:
    """Given a 1-D signal array (nan = ineligible), return (long_idx, short_idx).
    long_is_top=True → long=top decile (winners); False → long=bottom decile (small).
    Winsorize eligible signals 1/99, then rank. Decile = 10%."""
    eligible = np.where(np.isfinite(signal))[0]
    n = eligible.size
    if n < MIN_CROSS_SECTION:
        return np.array([], dtype=int), np.array([], dtype=int)
    sig_elig = signal[eligible].copy()
    sig_w = winsorize(sig_elig)
    order = np.argsort(sig_w)  # ascending
    ndec = max(1, n // 10)
    if long_is_top:
        long_local = order[n - ndec :]  # top
        short_local = order[:ndec]  # bottom
    else:
        long_local = order[:ndec]  # bottom (small)
        short_local = order[n - ndec :]  # top (big)
    return eligible[long_local], eligible[short_local]


# ---------- factor series construction ----------


def build_smb_series(
    close: np.ndarray, amount: np.ndarray, ret: np.ndarray, calendar: list[str], rebal_idx: list[int]
) -> dict[str, float]:
    """SMB daily returns: month-end rebalance, log(20d mean amount) signal.
    long = small (bottom decile), short = big (top decile)."""
    series: dict[str, float] = {}
    di = {d: i for i, d in enumerate(calendar)}
    for k, ri in enumerate(rebal_idx):
        # need 20d history ending at ri
        if ri - SIZE_DAYS + 1 < 0:
            continue
        amt_window = amount[:, ri - SIZE_DAYS + 1 : ri + 1]  # [nc, 20]
        # explicit finite-mean (all-nan rows → nan, no empty-slice warning)
        finite_mask = np.isfinite(amt_window)
        finite_cnt = finite_mask.sum(axis=1)
        finite_sum = np.where(finite_mask, amt_window, 0.0).sum(axis=1)
        mean_amt = np.where(finite_cnt > 0, finite_sum / np.maximum(finite_cnt, 1), np.nan)
        # eligibility: 20d history present (finite), mean_amt >= floor, formation amount>0
        form_amt = amount[:, ri]
        elig = np.isfinite(mean_amt) & (mean_amt >= LIQ_AMT_FLOOR) & np.isfinite(form_amt) & (form_amt > 0)
        signal = np.full(close.shape[0], np.nan)
        signal[elig] = np.log(mean_amt[elig])
        long_idx, short_idx = form_decile_legs(signal, long_is_top=False)
        if long_idx.size == 0 or short_idx.size == 0:
            continue
        # holding period (ri, next_rebal]
        end = rebal_idx[k + 1] if k + 1 < len(rebal_idx) else len(calendar) - 1
        for d in range(ri + 1, end + 1):
            lr = ret[long_idx, d]
            sr = ret[short_idx, d]
            lr = lr[np.isfinite(lr)]
            sr = sr[np.isfinite(sr)]
            if lr.size < MIN_DECILE_STOCKS or sr.size < MIN_DECILE_STOCKS:
                continue
            series[calendar[d]] = float(lr.mean() - sr.mean())
    return series


def build_umd_series(close: np.ndarray, ret: np.ndarray, calendar: list[str], rebal_idx: list[int]) -> dict[str, float]:
    """UMD daily returns: month-end rebalance, 12-2 momentum signal.
    long = winners (top decile), short = losers (bottom decile)."""
    series: dict[str, float] = {}
    for k, ri in enumerate(rebal_idx):
        if ri - UMD_LONG < 0:  # need 12m history
            continue
        c_now = close[:, ri - UMD_SHORT]  # ~1 month ago
        c_past = close[:, ri - UMD_LONG]  # ~12 months ago
        signal = c_now / c_past - 1.0
        signal[~np.isfinite(signal)] = np.nan
        # eligibility: both endpoints finite & positive
        elig = np.isfinite(signal) & np.isfinite(c_now) & np.isfinite(c_past) & (c_past > 0)
        signal[~elig] = np.nan
        long_idx, short_idx = form_decile_legs(signal, long_is_top=True)
        if long_idx.size == 0 or short_idx.size == 0:
            continue
        end = rebal_idx[k + 1] if k + 1 < len(rebal_idx) else len(calendar) - 1
        for d in range(ri + 1, end + 1):
            lr = ret[long_idx, d]
            sr = ret[short_idx, d]
            lr = lr[np.isfinite(lr)]
            sr = sr[np.isfinite(sr)]
            if lr.size < MIN_DECILE_STOCKS or sr.size < MIN_DECILE_STOCKS:
                continue
            series[calendar[d]] = float(lr.mean() - sr.mean())
    return series


# ---------- stats + correlations ----------


def series_stats(series: dict[str, float], label: str) -> dict:
    vals = np.array([v for v in series.values() if np.isfinite(v)], dtype=np.float64)
    n = vals.size
    if n == 0:
        return {"label": label, "n": 0}
    mean = float(vals.mean())
    std = float(vals.std(ddof=1)) if n > 1 else 0.0
    sharpe = mean / std * (252**0.5) if std > 0 else 0.0
    wr = float((vals > 0).mean() * 100)
    return {
        "label": label,
        "n": int(n),
        "mean_pct": round(mean * 100, 5),
        "std_pct": round(std * 100, 5),
        "annualized_mean_pct": round(mean * 100 * 252, 4),
        "annualized_sharpe": round(sharpe, 4),
        "wr_pct": round(wr, 2),
    }


def correlation_matrix(mkt: dict, smb: dict, umd: dict) -> dict:
    """Pearson correlation over dates where all 3 are present."""
    common = sorted(set(mkt) & set(smb) & set(umd))
    if len(common) < 10:
        return {"n_aligned": len(common), "note": "too few aligned dates"}
    M = np.array([mkt[d] for d in common])
    S = np.array([smb[d] for d in common])
    U = np.array([umd[d] for d in common])
    cMS = float(np.corrcoef(M, S)[0, 1])
    cMU = float(np.corrcoef(M, U)[0, 1])
    cSU = float(np.corrcoef(S, U)[0, 1])
    return {
        "n_aligned": len(common),
        "aligned_date_range": f"{common[0]}~{common[-1]}",
        "matrix": {
            "mkt": {"mkt": 1.0, "smb": round(cMS, 4), "umd": round(cMU, 4)},
            "smb": {"mkt": round(cMS, 4), "smb": 1.0, "umd": round(cSU, 4)},
            "umd": {"mkt": round(cMU, 4), "smb": round(cSU, 4), "umd": 1.0},
        },
    }


# ---------- main ----------


def main() -> int:
    print("==> loading calendar + index ...", flush=True)
    kline_dates = scan_kline_dates()
    calendar, mkt = load_calendar_and_index(kline_dates)
    print(f"    n_dates={len(calendar)} range {calendar[0]}~{calendar[-1]}", flush=True)

    print("==> loading kline panels (close + amount) ...", flush=True)
    close, amount, codes = load_panels(calendar)
    print(f"    codes={len(codes)} close_shape={close.shape} finite_close={int(np.isfinite(close).sum())}", flush=True)

    ret = daily_returns(close)

    rebal_idx = month_end_dates(calendar)
    print(
        f"==> month-end rebalance dates: {len(rebal_idx)} "
        f"first={calendar[rebal_idx[0]]} last={calendar[rebal_idx[-1]]}",
        flush=True,
    )

    print("==> building SMB daily series ...", flush=True)
    smb = build_smb_series(close, amount, ret, calendar, rebal_idx)
    print(f"    SMB days={len(smb)} range {min(smb)}~{max(smb)}" if smb else "    SMB empty", flush=True)

    print("==> building UMD daily series ...", flush=True)
    umd = build_umd_series(close, ret, calendar, rebal_idx)
    print(f"    UMD days={len(umd)} range {min(umd)}~{max(umd)}" if umd else "    UMD empty", flush=True)

    corr = correlation_matrix(mkt, smb, umd)

    out = {
        "metadata": {
            "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "methodology": "Fama-French/Carhart cross-sectional decile long-short, "
            "monthly rebalance, daily holding returns (decimal)",
            "market_benchmark": "sh.000001 (上证综指, price index excl. dividends)",
            "rebalance_freq": "monthly (last trading day of month)",
            "holding": "T+1 close to next rebalance close; constituents fixed during holding",
            "decile": "bottom/top 10%, equal-weight within leg",
            "winsorize": "1%/99% cross-section before ranking",
            "liquidity_filter": f"20d mean amount >= {LIQ_AMT_FLOOR:.0f} CNY + formation amount>0",
            "lookahead_guard": "signal at formation close; returns start next day",
            "date_range": f"{calendar[0]}~{calendar[-1]}",
            "n_dates": len(calendar),
            "n_codes_loaded": len(codes),
            "survivorship_note": "early 2018-2020 cross-section ~264-766 from non-random "
            "backfill; unbalanced panel; small-cap leg survivorship bias",
            "caveats": [
                "SMB size proxy = log(20d mean amount) is liquidity/turnover proxy, NOT true "
                "market cap (needs shares outstanding). High-amount stocks may be high-turnover "
                "speculative, not large-cap. This SMB is a low-turnover/high-turnover approximation.",
                "HML skipped (no historical PB/book-value data locally; valuation skill gives only "
                "current-snapshot PB, not monthly series needed for decile formation). 3-factor baseline.",
                "long-short needs shorting (A股散户融券受限); statistical baseline != tradeable.",
                "月末 close formation assumes tradeable at close (standard FF convention, "
                "mildly unrealistic for A-shares).",
                "Output is for downstream residual-alpha OLS regression only; NOT a claim that "
                "size/momentum factors have edge.",
            ],
        },
        "factors_built": ["mkt", "smb", "umd"],
        "hml_blocker": "no historical PB/book-value data locally; HML skipped per task "
        "(跳过 allowed). Only current-snapshot PB available via valuation skill, "
        "not the monthly historical PB series needed for cross-sectional decile "
        "formation. To build true HML, must first populate a historical PB panel.",
        "factor_series": {
            "mkt": dict(sorted(mkt.items())),
            "smb": dict(sorted(smb.items())),
            "umd": dict(sorted(umd.items())),
        },
        "factor_stats": {
            "mkt": series_stats(mkt, "mkt"),
            "smb": series_stats(smb, "smb"),
            "umd": series_stats(umd, "umd"),
        },
        "factor_correlations": corr,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n==> written {OUT}", flush=True)

    print("\n=== factor stats ===")
    for k in ["mkt", "smb", "umd"]:
        s = out["factor_stats"][k]
        print(
            f"  {k:4s}: n={s.get('n', 0):4d} mean={s.get('mean_pct', '?')}%/d "
            f"std={s.get('std_pct', '?')}%/d ann_sharpe={s.get('annualized_sharpe', '?')} "
            f"wr={s.get('wr_pct', '?')}%"
        )
    print("\n=== correlation matrix (aligned) ===")
    if "matrix" in corr:
        m = corr["matrix"]
        print(f"  aligned n={corr['n_aligned']} range={corr['aligned_date_range']}")
        print(f"              mkt      smb      umd")
        print(f"  mkt      {m['mkt']['mkt']:.4f}   {m['mkt']['smb']:+.4f}   {m['mkt']['umd']:+.4f}")
        print(f"  smb      {m['smb']['mkt']:+.4f}   {m['smb']['smb']:.4f}   {m['smb']['umd']:+.4f}")
        print(f"  umd      {m['umd']['mkt']:+.4f}   {m['umd']['smb']:+.4f}   {m['umd']['umd']:.4f}")
    else:
        print(f"  {corr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
