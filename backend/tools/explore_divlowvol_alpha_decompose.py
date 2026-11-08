# -*- coding: utf-8 -*-
"""explore_divlowvol_alpha_decompose.py — 红利低波 512890 alpha 来源拆解.

核心问题 (memory dividend-low-vol-base + outward-verify-multi):
  512890 年化 13.47% vs 沪深300 5.11%, market beta 0.517, alpha +10.83% (R²0.34).
  剩余 66% 是 value/size/low-vol 因子暴露. 学术 1510.01679: 控制 E/P+D/P 后
  红利低波 residual flat → value proxy 非 independent alpha (SSRN paywalled 未独立核实).

本脚本用项目数据验证 1510.01679: 月频回归
  r_512890 ~ alpha + beta_mkt*mkt + beta_value*HML(E/P+D/P) + beta_size*SMB
  控 value/size 后 alpha(截距)是否显著:
    - alpha flat(不显著) → value proxy 印证 1510.01679 (无独立 low-vol alpha)
    - alpha 仍显著 → low-vol 独立 anomaly (与 value 死矛盾, 须重框底仓定位)

数据 (全部走 vr_paths.resolve_data_dir + 本地 SQLite 缓存, 复用 value 因子脚本方法):
  - 512890 qfq 日线 → 月 return (akshare fund_etf_hist_em)
  - 沪深300 日线 → 月 return (akshare stock_zh_index_daily_em) [market]
  - value HML: 250 股 universe, E/P(TTM_EPS重建/raw_close) + D/P(trailing div/raw_close)
    复合 value score, 月末再平衡 long top-30% short bottom-30%, PIT 基本面
  - size SMB: factor_baselines.json 日频 SMB (5255 股 panel, 已 validated) → 月聚合

方法 (复用 residual-edge-analyzer / size-vs-lowvol 脚本):
  - OLS + NW-HAC SE (Bartlett, optimal lag)
  - M1 CAPM / M2 +value(1510.01679 核心) / M3 +value+size
  - VIF 多重共线诊断, rolling 36m alpha 稳定性, alternate baseline sensitivity
  - Bonferroni ×3 (3 模型 alpha 并行检验) + BH FDR

诚实约束 (§44 v3 + 不外推):
  - 250 股 universe 是 top-liquidity survivors (≥6yr), value 因子受幸存者偏差
    BUT 512890 持一篮子红利低波股 (中证红利低波动指数), 非 250 universe 子集 —
    universe mismatch 是 factor proxy 偏差, 标注不纠 (spanning test 仍有效)
  - A 股 value 2019-2026 显著负 (E/P t=-3.5, value 惩罚) → HML 可能负,
    512890 loading 方向不确定 (value 股 vs 低波股行为可能背离) — 回归测真实 loading
  - 月频 n~92 (2019-02~2026-09), 3 因子回归 n/k 充足
  - ETF 不退市, 幸存者偏差小; index benchmark 沪深300 宽基
  - 用 raw return (含 rf), alpha 含 rf 常数项 — 控因子前后 alpha 变化是核心, 非绝对水平
  - 单一 ETF 样本 n=1, 不外推到 "低波因子有/无 alpha"; 仅 512890 alpha 归因

kill: value proxy 数据不可得 → blocked; 控 value 后 alpha 不显著 → falsified(独立 alpha 死,
      512890=value proxy 印证 1510.01679).

跑法: cd /Users/lizhiwei/project/code/stock/Vibe-Research/backend
      .venv/bin/python tools/explore_divlowvol_alpha_decompose.py
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import norm
from statsmodels.regression.linear_model import OLS

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir  # noqa: E402

DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
FUND_DB = DATA / "fundamentals_cache.db"
RAW_CLOSE_DB = DATA / "monthly_raw_close.db"
DIV_DB = DATA / "dividends_cache.db"
FACTOR_JSON = DATA / "factor_baselines.json"

ETF_CODE = "512890"
BENCH_CODE = "sh000300"
START = "20190118"
N_MODELS_PARALLEL = 3  # Bonferroni ×3 (M1/M2/M3 alpha)
ALPHA = 0.05
ROLLING_WINDOW = 36  # 36 月滚动 alpha (月频, n~92)
VALUE_LEG_PCT = 0.30  # Fama-French 30/30/40 breakpoints


# ── anti-ban: circuit_breaker 防封 (akshare 东财端点) ──────────────────────

def _safe_ak(call_desc: str, fn):
    """带 circuit_breaker + retry 的 akshare 调用 (防封 IP)."""
    try:
        from circuit_breaker import get_breaker  # noqa: PLC0415

        br = get_breaker("eastmoney")
        if not br.allow_request():
            print(f"  ⚠️ circuit_breaker OPEN, {call_desc} 跳过 (防封)")
            return None
    except Exception:
        pass  # circuit_breaker 不可用时降级直连 (ETF/index 历史端点低风险)
    import time as _t

    for attempt in range(3):
        try:
            r = fn()
            try:
                from circuit_breaker import get_breaker  # noqa: PLC0415

                get_breaker("eastmoney").record_success()
            except Exception:
                pass
            return r
        except Exception as e:
            try:
                from circuit_breaker import get_breaker  # noqa: PLC0415

                get_breaker("eastmoney").record_failure()
            except Exception:
                pass
            print(f"  ⚠️ {call_desc} attempt {attempt + 1} fail: {e}")
            _t.sleep(1.0 * (attempt + 1))
    return None


# ── 1. ETF + 沪深300 月 return ──────────────────────────────────────────────

def fetch_etf_monthly() -> pd.Series:
    """512890 qfq 日线 → 月 return (月末 close 环比)."""
    import akshare as ak  # noqa: PLC0415

    def _get():
        return ak.fund_etf_hist_em(symbol=ETF_CODE, period="daily", start_date=START, end_date="20261108", adjust="qfq")

    df = _safe_ak("ETF hist", _get)
    if df is None or len(df) == 0:
        raise RuntimeError("ETF data fetch failed (akshare)")
    df["日期"] = pd.to_datetime(df["日期"])
    df = df.sort_values("日期").set_index("日期")
    # 月末 close (resample M 取每月最后交易日)
    monthly_close = df["收盘"].resample("ME").last().dropna()
    monthly_ret = monthly_close.pct_change().dropna()
    monthly_ret.name = "etf"
    return monthly_ret


def fetch_bench_monthly() -> pd.Series:
    """沪深300 日线 → 月 return."""
    import akshare as ak  # noqa: PLC0415

    def _get():
        return ak.stock_zh_index_daily_em(symbol=BENCH_CODE)

    df = _safe_ak("index daily", _get)
    if df is None or len(df) == 0:
        raise RuntimeError("index data fetch failed (akshare)")
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    df = df[df.index >= pd.Timestamp(START)]
    monthly_close = df["close"].resample("ME").last().dropna()
    monthly_ret = monthly_close.pct_change().dropna()
    monthly_ret.name = "mkt"
    return monthly_ret


# ── 2. value 因子构建 (复用 explore_value_factor-monthly 方法) ────────────────

def pit_pubdate(stat_date: str) -> str:
    y, m = int(stat_date[:4]), int(stat_date[5:7])
    if m == 3:
        return f"{y}-04-30"
    if m == 6:
        return f"{y}-08-31"
    if m == 9:
        return f"{y}-10-31"
    if m == 12:
        return f"{y + 1}-04-30"
    return stat_date


def load_fundamentals_pit() -> dict[str, list[dict]]:
    if not FUND_DB.exists():
        return {}
    conn = sqlite3.connect(str(FUND_DB))
    rows = conn.execute(
        "SELECT code, stat_date, bvps, eps FROM fundamentals WHERE stat_date >= '2017-01-01' ORDER BY code, stat_date"
    ).fetchall()
    conn.close()
    by_code: dict[str, list[dict]] = defaultdict(list)
    for code, sd, bvps, eps in rows:
        by_code[code].append({"pit": pit_pubdate(sd), "stat": sd, "bvps": bvps, "eps": eps})
    return dict(by_code)


def reconstruct_ttm_eps(funds: list[dict], rebalance_date: str) -> float | None:
    avail = [f for f in funds if f["pit"] <= rebalance_date and f.get("eps") is not None]
    if not avail:
        return None
    cur = avail[-1]
    cur_stat = cur["stat"]
    cur_y, cur_m = int(cur_stat[:4]), int(cur_stat[5:7])
    cur_eps = cur["eps"]
    if cur_eps is None:
        return None
    if cur_m == 12:
        return cur_eps
    prior_year = cur_y - 1
    prior_annual = next((f for f in avail if f["stat"] == f"{prior_year}-12-31"), None)
    prior_same_q = next((f for f in avail if f["stat"] == f"{prior_year}-{cur_stat[5:]}"), None)
    if prior_annual is None or prior_same_q is None:
        return None
    if prior_annual["eps"] is None or prior_same_q["eps"] is None:
        return None
    return cur_eps + prior_annual["eps"] - prior_same_q["eps"]


def trailing_bvps(funds: list[dict], rebalance_date: str) -> float | None:
    """PIT 每股净资产(bvps):取 rebalance_date 前最近一期(存量非 TTM,不需重建)。

    B/P 第三因子(6专家panel第二步):补全 value 三族控制(E/P+D/P+B/P)。
    排除负净资产(bvps<=0)= 破产风险股,同 archive backtest_bp 口径。
    """
    avail = [f for f in funds if f["pit"] <= rebalance_date and f.get("bvps") is not None]
    if not avail:
        return None
    bvps = avail[-1]["bvps"]
    if bvps is None or bvps <= 0:  # 排除负净资产
        return None
    return float(bvps)


def load_raw_close() -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    """code -> {month(YYYY-MM): close}, 停牌(vol=0)过滤. 复用 value 脚本.
    返回 (by_month, canonical_date) — canonical_date[month]=该月最大交易日(PIT 用)."""
    by_code: dict[str, dict[str, float]] = defaultdict(dict)
    canonical: dict[str, str] = {}
    if not RAW_CLOSE_DB.exists():
        return dict(by_code), canonical
    conn = sqlite3.connect(str(RAW_CLOSE_DB))
    for code, d, c in conn.execute("SELECT code, date, close FROM raw_close"):
        try:
            c = float(c) if str(c) not in ("nan", "None", "") else None
        except (ValueError, TypeError):
            c = None
        if c is None or c <= 0:
            continue
        month = d[:7]
        by_code[code][month] = c
        if month not in canonical or d > canonical[month]:
            canonical[month] = d
    conn.close()
    return dict(by_code), canonical


def load_dividends() -> dict[str, list[tuple[str, float]]]:
    if not DIV_DB.exists():
        return {}
    conn = sqlite3.connect(str(DIV_DB))
    by_code: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for code, ex, cash in conn.execute(
        "SELECT code, ex_date, cash_per_share FROM dividends ORDER BY code, ex_date"
    ):
        by_code[code].append((ex, cash))
    conn.close()
    return dict(by_code)


def trailing_dp(divs: list[tuple[str, float]], rebalance_date: str) -> float | None:
    try:
        rd = datetime.strptime(rebalance_date, "%Y-%m-%d")
        lo = rd - timedelta(days=365)
    except Exception:
        return None
    total = 0.0
    for ex, cash in divs:
        try:
            ed = datetime.strptime(ex, "%Y-%m-%d")
        except Exception:
            continue
        if lo <= ed <= rd:
            total += cash
    return total if total > 0 else None


def load_monthly_prices() -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    """code -> {month(YYYY-MM): qfq close}, 停牌(vol=0)过滤. 返回 (by_month, canonical_date)."""
    conn = sqlite3.connect(str(KLINE_DB))
    code_months: dict[str, dict[str, float]] = defaultdict(dict)
    canonical: dict[str, str] = {}
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list):
            continue
        by_month: dict[str, tuple[str, float]] = {}
        for b in bars:
            d = b.get("date", "")
            if not d or len(d) < 7:
                continue
            month = d[:7]
            c = b.get("close")
            try:
                c = float(c) if c else None
            except (ValueError, TypeError):
                c = None
            if c is None or c <= 0:
                continue
            vol = b.get("volume", 0)
            try:
                vol = float(vol) if vol else 0
            except (ValueError, TypeError):
                vol = 0
            if vol <= 0:
                continue  # 停牌冻结 close 不用
            prev = by_month.get(month)
            if prev is None or d > prev[0]:
                by_month[month] = (d, c)
                if month not in canonical or d > canonical[month]:
                    canonical[month] = d
        for month, (d, c) in by_month.items():
            code_months[code][month] = c
    conn.close()
    return dict(code_months), canonical


def compute_monthly_returns(prices: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """code -> {month: return} (按 calendar month 排序, 月末 close 环比)."""
    rets: dict[str, dict[str, float]] = {}
    for code, md in prices.items():
        sorted_m = sorted(md.keys())
        r: dict[str, float] = {}
        for i in range(1, len(sorted_m)):
            prev_c = md[sorted_m[i - 1]]
            cur_c = md[sorted_m[i]]
            if prev_c > 0:
                r[sorted_m[i]] = (cur_c - prev_c) / prev_c
        rets[code] = r
    return rets


def select_universe(size: int = 250) -> list[str]:
    conn = sqlite3.connect(str(KLINE_DB))
    rows = []
    for code, bj in conn.execute("SELECT code, bars_json FROM kline"):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or len(bars) < 1500:
            continue
        amts = [float(b.get("amount", 0) or 0) for b in bars if b.get("amount")]
        if amts:
            rows.append((code, sum(amts) / len(amts)))
    conn.close()
    rows.sort(key=lambda x: -x[1])
    return [c for c, _ in rows[:size]]


def build_value_hml(
    funds: dict[str, list[dict]],
    raw_close: dict[str, dict[str, float]],
    canonical_raw: dict[str, str],
    dividends: dict[str, list[tuple[str, float]]],
    month_rets: dict[str, dict[str, float]],
    canonical_kline: dict[str, str],
) -> pd.Series:
    """Value HML 月频 long-short: E/P+D/P 复合 value score, 月末再平衡 long top-30% short bottom-30%.

    时序: 月末 M 用 PIT 基本面 + raw_close 算 value score, 形成 portfolio,
    持有收益 = 下个月(M+1) month_ret (formation-holding lag 防 look-ahead).
    返回 Series index=持有期月(月末 Timestamp), value=long_ret - short_ret (decimal).
    全部按 calendar month(YYYY-MM) 索引, 避免交易日变体对齐问题.
    """
    # 共同可用月份 (raw_close ∩ kline month_rets), PIT 基本面 2018-Q2+ → 从 2018-10 起
    raw_months = {m for md in raw_close.values() for m in md}
    kline_months = {m for md in month_rets.values() for m in md}
    common_months = sorted(raw_months & kline_months)
    rebal_months = [m for m in common_months if m >= "2018-10"]
    hml: dict[str, float] = {}
    n_long_total = 0
    for i, m in enumerate(rebal_months):
        if i + 1 >= len(rebal_months):
            break
        next_m = rebal_months[i + 1]  # 持有期月份
        # PIT 再平衡日 (该月最大交易日)
        rd = canonical_raw.get(m) or canonical_kline.get(m) or f"{m}-28"
        # 算 value score (E/P + D/P + B/P 三因子,6专家panel第二步补全 value 三族)
        scores: list[tuple[str, float, float, float]] = []
        for code in raw_close:
            if next_m not in month_rets.get(code, {}):
                continue
            close = raw_close[code].get(m)
            if not close or close <= 0:
                continue
            fl = funds.get(code)
            ttm = reconstruct_ttm_eps(fl, rd) if fl else None
            divs = dividends.get(code)
            dp_num = trailing_dp(divs, rd) if divs else None
            bvps = trailing_bvps(fl, rd) if fl else None
            if ttm is None or ttm <= 0:  # E/P 需正盈利
                continue
            if dp_num is None or dp_num <= 0:  # D/P 需有分红 (高质量 value)
                continue
            if bvps is None or bvps <= 0:  # B/P 需正净资产 (排除破产风险)
                continue
            ep = ttm / close
            dp = dp_num / close
            bp = bvps / close
            scores.append((code, ep, dp, bp))
        if len(scores) < 20:
            continue
        # cross-sectional percentile rank (复合 value = 三因子平均 rank)
        eps_vals = [s[1] for s in scores]
        dp_vals = [s[2] for s in scores]
        bp_vals = [s[3] for s in scores]

        def pct_rank(vals: list[float], v: float) -> float:
            return sum(1 for x in vals if x <= v) / len(vals)

        composite = []
        for code, ep, dp, bp in scores:
            r_ep = pct_rank(eps_vals, ep)
            r_dp = pct_rank(dp_vals, dp)
            r_bp = pct_rank(bp_vals, bp)
            composite.append((code, (r_ep + r_dp + r_bp) / 3.0))
        composite.sort(key=lambda x: -x[1])  # 高 value 在前
        n_total = len(composite)
        n_top = max(5, int(n_total * VALUE_LEG_PCT))
        n_bot = max(5, int(n_total * VALUE_LEG_PCT))
        long_codes = [c for c, _ in composite[:n_top]]
        short_codes = [c for c, _ in composite[-n_bot:]]
        # 持有期收益 (下个月)
        long_rets = [month_rets[c][next_m] for c in long_codes if next_m in month_rets.get(c, {})]
        short_rets = [month_rets[c][next_m] for c in short_codes if next_m in month_rets.get(c, {})]
        if len(long_rets) < 3 or len(short_rets) < 3:
            continue
        lr = statistics.mean(long_rets)
        sr = statistics.mean(short_rets)
        # index by next_m month-end timestamp
        hml[pd.Timestamp(canonical_kline.get(next_m, f"{next_m}-28"))] = lr - sr
        n_long_total += n_top
    print(f"  value HML: {len(hml)} 月, avg leg~{n_long_total // max(1, len(hml))}")
    s = pd.Series(hml, name="hml")
    return s.sort_index()


# ── 3. size SMB 月聚合 (factor_baselines.json 日频 → 月) ─────────────────────

def load_smb_monthly() -> pd.Series:
    d = json.loads(FACTOR_JSON.read_text())
    smb_daily = d["factor_series"]["smb"]  # {date_str: decimal}
    s = pd.Series(smb_daily, dtype=float)
    s.index = pd.to_datetime(s.index)
    s = s.sort_index()
    # 日 → 月复合: (1+r1)*(1+r2)*...-1
    monthly = (1 + s).resample("ME").prod() - 1
    monthly.name = "smb"
    return monthly.dropna()


# ── 4. OLS + NW-HAC (复用 residual 脚本) ─────────────────────────────────────

def nw_lag(n: int) -> int:
    return max(1, int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0))))


def run_ols_hac(y: pd.Series, X: pd.DataFrame, label: str = "") -> dict:
    Xc = sm.add_constant(X, has_constant="add")
    df = pd.concat([y, Xc], axis=1).dropna()
    if len(df) < Xc.shape[1] + 5:
        return {"label": label, "n": len(df), "status": "too_few_obs"}
    yv = df[y.name]
    Xv = df.drop(columns=[y.name])
    lag = nw_lag(len(df))
    model = OLS(yv, Xv).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    const = model.params["const"]
    se_const = model.bse["const"]
    t_const = model.tvalues["const"]
    p_two = 2 * (1 - norm.cdf(abs(t_const)))
    p_one = norm_sf_positive(t_const)
    loadings = {}
    for col in Xv.columns:
        loadings[col] = {
            "beta": float(model.params[col]),
            "t": float(model.tvalues[col]),
            "p_two": float(2 * (1 - norm.cdf(abs(model.tvalues[col])))),
        }
    return {
        "label": label,
        "n": int(len(df)),
        "nlag": lag,
        "alpha_decimal": float(const),
        "alpha_pct_monthly": float(const * 100),
        "alpha_annualized_pct": float(const * 12 * 100),
        "alpha_se": float(se_const),
        "alpha_t": float(t_const),
        "alpha_p_two": float(p_two),
        "alpha_p_one": float(p_one),
        "r_squared": float(model.rsquared),
        "loadings": loadings,
        "resid_std_pct": float(np.std(model.resid) * 100),
    }


def rolling_alpha(y: pd.Series, X: pd.DataFrame, window: int = ROLLING_WINDOW) -> dict:
    Xc = sm.add_constant(X, has_constant="add")
    df = pd.concat([y, Xc], axis=1).dropna()
    yv = df[y.name]
    Xv = df.drop(columns=[y.name])
    n = len(df)
    alphas: list[float] = []
    sig = 0
    valid = 0
    for i in range(window, n + 1):
        yw = yv.iloc[i - window : i]
        Xw = Xv.iloc[i - window : i]
        if len(yw) < Xw.shape[1] + 2:
            continue
        try:
            m = OLS(yw, Xw).fit()
            a = m.params["const"]
            se = m.bse["const"]
            t = a / se if se > 0 else 0
            alphas.append(float(a))
            valid += 1
            if abs(t) > 1.96:
                sig += 1
        except Exception:
            continue
    if not alphas:
        return {"status": "no_windows", "valid": 0}
    arr = np.array(alphas)
    return {
        "status": "ok",
        "n_windows": valid,
        "mean_alpha_pct_monthly": float(arr.mean() * 100),
        "std_alpha_pct": float(arr.std() * 100),
        "pct_positive": float((arr > 0).mean() * 100),
        "pct_sig_t2": float(sig / max(1, valid) * 100),
    }


def vif(x1: pd.Series, x2: pd.Series) -> float:
    df = pd.DataFrame({"x1": x1, "x2": x2}).dropna()
    if len(df) < 5:
        return float("nan")
    Xc = sm.add_constant(df["x2"])
    try:
        r2 = OLS(df["x1"], Xc).fit().rsquared
        return float(1.0 / (1.0 - r2)) if r2 < 1.0 else float("inf")
    except Exception:
        return float("nan")


def bh_fdr(pvals: list[float], q: float = 0.05) -> dict:
    n = len(pvals)
    if n == 0:
        return {"n": 0}
    order = sorted(range(n), key=lambda i: pvals[i])
    n_rej = 0
    crit = 0.0
    for rank, i in enumerate(order, start=1):
        thresh = (rank / n) * q
        if pvals[i] <= thresh:
            crit = pvals[i]
            n_rej = rank
    return {"n": n, "q": q, "n_rejected": n_rej, "max_p_rejected": crit}


# ── main ───────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 78)
    print("红利低波 512890 alpha 拆解: value proxy vs 独立 low-vol anomaly")
    print("1510.01679 验证: 控 E/P+D/P 后 alpha 是否 flat")
    print("=" * 78)

    # 1. ETF + market 月 return
    print("\n[1] 拉 512890 + 沪深300 月 return ...", flush=True)
    r_etf = fetch_etf_monthly()
    r_mkt = fetch_bench_monthly()
    print(f"  512890: {len(r_etf)} 月 {r_etf.index[0].date()}~{r_etf.index[-1].date()} 年化={(1+r_etf).prod()**(12/len(r_etf))-1:.4f}")
    print(f"  沪深300: {len(r_mkt)} 月 {r_mkt.index[0].date()}~{r_mkt.index[-1].date()} 年化={(1+r_mkt).prod()**(12/len(r_mkt))-1:.4f}")

    # 2. value HML
    print("\n[2] 构建 value HML 月频因子 (E/P+D/P 复合, 250 universe, PIT) ...", flush=True)
    universe = select_universe(250)
    funds = load_fundamentals_pit()
    raw_close, canonical_raw = load_raw_close()
    dividends = load_dividends()
    prices, canonical_kline = load_monthly_prices()
    month_rets = compute_monthly_returns(prices)
    print(f"  universe={len(universe)} funds={len(funds)} raw_close={len(raw_close)} divs={len(dividends)} prices={len(prices)}", flush=True)
    if len(raw_close) < 50 or len(dividends) < 50 or len(funds) < 50:
        print("  ⚠️ value proxy 数据不足 → BLOCKED")
        _dump_result({"status": "blocked_value_data"})
        return 1
    hml = build_value_hml(funds, raw_close, canonical_raw, dividends, month_rets, canonical_kline)
    if len(hml) < 24:
        print(f"  ⚠️ value HML 月数不足 ({len(hml)}<24) → BLOCKED")
        _dump_result({"status": "blocked_hml_too_short", "n_hml": len(hml)})
        return 1
    hml_mean = hml.mean()
    print(f"  HML mean={hml_mean*100:.4f}%/月 年化={hml_mean*12*100:.2f}% ({'value 惩罚(负)' if hml_mean < 0 else 'value premium(正)'})")

    # 3. size SMB 月聚合
    print("\n[3] size SMB 月聚合 (factor_baselines.json 日频) ...", flush=True)
    smb = load_smb_monthly()
    print(f"  SMB: {len(smb)} 月 mean={smb.mean()*100:.4f}%/月 年化={smb.mean()*12*100:.2f}%")

    # 4. 对齐
    print("\n[4] 对齐 ETF/mkt/HML/SMB 到共同月 ...", flush=True)
    df = pd.concat([r_etf, r_mkt, hml, smb], axis=1).dropna()
    df.columns = ["etf", "mkt", "hml", "smb"]
    print(f"  共同窗口: {df.index[0].date()}~{df.index[-1].date()} ({len(df)} 月)", flush=True)
    if len(df) < 30:
        print(f"  ⚠️ 共同月数不足 ({len(df)}<30) → BLOCKED")
        _dump_result({"status": "blocked_aligned_short", "n": len(df)})
        return 1

    # 描述性: 相关性 + VIF
    print("\n[5] 描述性: 相关性 + VIF ...")
    corr_mh = df["mkt"].corr(df["hml"])
    corr_ms = df["mkt"].corr(df["smb"])
    corr_hs = df["hml"].corr(df["smb"])
    vif_hs = vif(df["hml"], df["smb"])
    print(f"  corr(mkt,hml)={corr_mh:+.3f} corr(mkt,smb)={corr_ms:+.3f} corr(hml,smb)={corr_hs:+.3f}")
    print(f"  VIF(hml,smb)={vif_hs:.2f} (>5=多重共线严重)")

    # 回归
    y = df["etf"]
    X_m1 = df[["mkt"]]
    X_m2 = df[["mkt", "hml"]]
    X_m3 = df[["mkt", "hml", "smb"]]

    print(f"\n{'='*78}")
    print("M1 CAPM: r_etf ~ alpha + beta_mkt*mkt  (基线, 复现 +10.83%/yr alpha)")
    print(f"{'='*78}")
    m1 = run_ols_hac(y, X_m1, "M1 CAPM")
    _print_reg(m1)

    print(f"\n{'='*78}")
    print("M2 +value: r_etf ~ alpha + beta_mkt*mkt + beta_value*hml  (1510.01679 核心检验)")
    print(f"{'='*78}")
    m2 = run_ols_hac(y, X_m2, "M2 +value")
    _print_reg(m2)

    print(f"\n{'='*78}")
    print("M3 +value+size: r_etf ~ alpha + beta_mkt*mkt + beta_value*hml + beta_size*smb")
    print(f"{'='*78}")
    m3 = run_ols_hac(y, X_m3, "M3 3-factor")
    _print_reg(m3)

    # alpha 变化 (核心: M1→M2→M3 alpha 是否 drop 到不显著)
    print(f"\n{'='*78}")
    print("alpha 变化 (核心: 控 value/size 后 alpha 是否 flat)")
    print(f"{'='*78}")
    a1 = m1["alpha_annualized_pct"]
    a2 = m2["alpha_annualized_pct"]
    a3 = m3["alpha_annualized_pct"]
    t1, t2, t3 = m1["alpha_t"], m2["alpha_t"], m3["alpha_t"]
    p1, p2, p3 = m1["alpha_p_one"], m2["alpha_p_one"], m3["alpha_p_one"]
    drop_m1_m2 = (a1 - a2)
    drop_m1_m3 = (a1 - a3)
    print(f"  M1 CAPM:        alpha={a1:+.2f}%/yr  t={t1:.2f}  p_one={p1:.4f}  {'SIG' if p1<0.05 else 'ns'}")
    print(f"  M2 +value:      alpha={a2:+.2f}%/yr  t={t2:.2f}  p_one={p2:.4f}  {'SIG' if p2<0.05 else 'ns'}")
    print(f"  M3 +value+size: alpha={a3:+.2f}%/yr  t={t3:.2f}  p_one={p3:.4f}  {'SIG' if p3<0.05 else 'ns'}")
    print(f"  M1→M2 alpha 变化: {drop_m1_m2:+.2f}%/yr (控 value 后)")
    print(f"  M1→M3 alpha 变化: {drop_m1_m3:+.2f}%/yr (控 value+size 后)")

    # value loading 解读
    b_val_m2 = m2["loadings"].get("hml", {}).get("beta", 0)
    t_val_m2 = m2["loadings"].get("hml", {}).get("t", 0)
    b_val_m3 = m3["loadings"].get("hml", {}).get("beta", 0)
    t_val_m3 = m3["loadings"].get("hml", {}).get("t", 0)
    b_sz_m3 = m3["loadings"].get("smb", {}).get("beta", 0)
    t_sz_m3 = m3["loadings"].get("smb", {}).get("t", 0)
    print(f"\n  value loading (hml): M2 beta={b_val_m2:+.3f}(t={t_val_m2:.2f}) | M3 beta={b_val_m3:+.3f}(t={t_val_m3:.2f})")
    print(f"  size loading (smb):  M3 beta={b_sz_m3:+.3f}(t={t_sz_m3:.2f})")

    # Bonferroni ×3 + BH FDR
    print(f"\n[6] 多重检验校正 (Bonferroni ×{N_MODELS_PARALLEL} + BH FDR) ...")
    ps = [p1, p2, p3]
    for i, (lbl, p, a) in enumerate(zip(["M1", "M2", "M3"], ps, [a1, a2, a3])):
        pb = bonferroni_p(p, N_MODELS_PARALLEL)
        print(f"  {lbl}: raw p_one={p:.4f} → Bonf×{N_MODELS_PARALLEL}={pb:.4f} ({'PASS' if pb<ALPHA else 'FAIL'} @ {ALPHA}) alpha={a:+.2f}%/yr")
    bh = bh_fdr(ps, q=0.05)
    print(f"  BH FDR (q=0.05): n_rejected={bh['n_rejected']}/{len(ps)}")

    # rolling alpha 稳定性 (M2 核心 + M3)
    print(f"\n[7] Rolling {ROLLING_WINDOW}m alpha 稳定性 (M2/M3) ...")
    roll_m2 = rolling_alpha(y, X_m2, ROLLING_WINDOW)
    roll_m3 = rolling_alpha(y, X_m3, ROLLING_WINDOW)
    for lbl, roll in [("M2+value", roll_m2), ("M3 3-factor", roll_m3)]:
        if roll["status"] == "ok":
            print(f"  {lbl}: n_win={roll['n_windows']} mean={roll['mean_alpha_pct_monthly']:.4f}%/月 "
                  f"%pos={roll['pct_positive']:.1f}% %sig|t|>1.96={roll['pct_sig_t2']:.1f}%")
        else:
            print(f"  {lbl}: {roll['status']}")

    # ============ VERDICT ============
    print(f"\n{'='*78}")
    print("VERDICT: 512890 alpha 是 value proxy 还是独立 low-vol anomaly?")
    print(f"{'='*78}")
    # 核心判据: 控 value(M2) 后 alpha 是否显著
    p2_bonf = bonferroni_p(p2, N_MODELS_PARALLEL)
    p3_bonf = bonferroni_p(p3, N_MODELS_PARALLEL)
    m2_alpha_flat = (p2_bonf >= ALPHA) or (t2 < 1.96)
    m3_alpha_flat = (p3_bonf >= ALPHA) or (t3 < 1.96)
    # value 解释力: alpha drop 比例
    explained_by_value = drop_m1_m2 / a1 if abs(a1) > 0.01 else 0

    print(f"  控 value(M2) 后 alpha: {a2:+.2f}%/yr t={t2:.2f} Bonf={p2_bonf:.4f} → {'FLAT(不显著)' if m2_alpha_flat else '仍显著'}")
    print(f"  控 value+size(M3) 后 alpha: {a3:+.2f}%/yr t={t3:.2f} Bonf={p3_bonf:.4f} → {'FLAT(不显著)' if m3_alpha_flat else '仍显著'}")
    print(f"  value 解释 alpha 比例: {explained_by_value*100:+.1f}% (M1→M2 drop/a1)")

    # 判定级联
    if m2_alpha_flat and m3_alpha_flat:
        verdict = "FALSIFIED: 控 value(及+size) 后 alpha flat → 512890=value proxy, 印证 1510.01679 (无独立 low-vol alpha)"
        falsified = True
        actionable = "归档: 512890 底仓定位=资产配置层(value proxy+分红现金流), 非独立 alpha; value 三族死不影响底仓(它是 value 暴露非 value 选股 edge)"
    elif m2_alpha_flat and not m3_alpha_flat:
        verdict = "PARTIAL: 控 value 后 alpha flat 但加 size 后回归 — value 主导解释, size 边际"
        falsified = True
        actionable = "归档: value proxy 主导, 512890 非 low-vol 独立 anomaly"
    elif not m2_alpha_flat:
        # alpha 控 value 后仍显著
        verdict = "NOT FALSIFIED: 控 value 后 alpha 仍显著 → low-vol 独立 anomaly 迹象 (与 value 死矛盾, 须重框)"
        falsified = False
        # 看 alpha 大小+稳健性
        if a2 > 3.0 and roll_m2.get("pct_positive", 0) >= 60:
            actionable = "值得深做: low-vol 独立于 value 的 alpha 迹象, 须 (1)加 HML(B/P) 补全 value (2)独立低波因子 long-short 验证 (3)样本外/跨市场稳健性"
        else:
            actionable = "探索性: alpha 残存但幅度/稳定性有限, 标注 low-vol 可能独立须更多验证"
    else:
        verdict = "AMBIGUOUS"
        falsified = False
        actionable = "探索性: 结果模糊, 须扩样本/补因子"

    print(f"\n  → {verdict}")
    print(f"  → actionable: {actionable}")

    # 诚实 caveat
    print(f"\n  诚实 caveat (不降级 verdict, 但必须标注):")
    print(f"    - 250 股 universe 是 top-liquity survivors; value HML 受幸存者偏差")
    print(f"    - HML 用 E/P+D/P (1510.01679 口径) 非 B/P; B/P(value 第三族)未控 — value 控制可能不完整")
    print(f"    - 512890 持中证红利低波动指数(一篮子), 非 250 universe 子集; universe mismatch 是 proxy 偏差")
    print(f"    - A 股 value 2019-2026 显著负(value 惩罚); 512890 此期正 — 时段/样本特异性")
    print(f"    - 用 raw return(含 rf), alpha 含 rf 常数; 核心是控因子前后变化非绝对水平")
    print(f"    - 月频 n={len(df)}, 单 ETF; 不外推到 '低波因子有/无 alpha', 仅 512890 归因")
    print(f"    - SMB=factor_baselines.json(5255 股 panel, log amount 流动性代理非真市值)")

    # [8] 正-value-regime 子样本诊断(synthesis 推荐:切 hml>0 月份控 value 看 alpha flat?)
    # 关键洞察:512890 残差 alpha 升而非降可能是 A 股 value 负(-14.91%/yr)机械去拖累,
    # 非"低波独立"独证。切 hml>0(value 正的月份)控 value 后看 alpha:
    #   - 若 alpha flat → 坐实机械通胀(底仓=value 拖累去除+分红/指数方法论非低波 alpha)
    #   - 若 alpha 仍残存 → low-vol 独立 anomaly 迹象(与直接低波 falsification t=-2.5 矛盾须调和)
    print(f"\n{'='*78}")
    print("[8] 正-value-regime 子样本诊断 (切 hml>0 月份控 value 看 alpha flat?)")
    print(f"{'='*78}")
    pos_mask = df["hml"] > 0
    neg_mask = df["hml"] <= 0
    print(f"  全样本: {len(df)} 月 (hml mean={hml_mean*100:.4f}%/月 {'负=value惩罚' if hml_mean < 0 else '正=value溢价'})")
    print(f"  hml>0(value 正): {pos_mask.sum()} 月 | hml<=0(value 负): {neg_mask.sum()} 月")
    # hml>0 月份年份分布(理解 regime)
    pos_years = df.loc[pos_mask].index.year.value_counts().sort_index()
    print(f"  hml>0 月份年份分布: {dict(pos_years)}")
    print(f"  hml>0 月份 hml mean={df.loc[pos_mask, 'hml'].mean()*100:.4f}%/月, etf mean={df.loc[pos_mask, 'etf'].mean()*100:.4f}%/月")
    print(f"  hml<=0 月份 hml mean={df.loc[neg_mask, 'hml'].mean()*100:.4f}%/月, etf mean={df.loc[neg_mask, 'etf'].mean()*100:.4f}%/月")
    pos_regime_results: dict = {}
    regime_verdict = "BLOCKED_SUBSAMPLE_TOO_SMALL"
    for label, mask in [("hml>0 正value", pos_mask), ("hml<=0 负value", neg_mask)]:
        sub = df[mask]
        if len(sub) < 24:
            print(f"  {label}: n={len(sub)}<24 跳过(样本不足)")
            pos_regime_results[label] = {"status": "too_few", "n": len(sub)}
            continue
        r = run_ols_hac(sub["etf"], sub[["mkt", "hml"]], f"M2 {label}")
        _print_reg(r)
        pos_regime_results[label] = r
    pos_res = pos_regime_results.get("hml>0 正value", {})
    if isinstance(pos_res, dict) and pos_res.get("status") != "too_few":
        pos_alpha = pos_res.get("alpha_annualized_pct", 0)
        pos_t = pos_res.get("alpha_t", 0)
        pos_p = pos_res.get("alpha_p_one", 1)
        pos_flat = (pos_p >= 0.05) or (pos_t < 1.96)
        regime_verdict = "MECHANICAL_INFLATION" if pos_flat else "ANOMALY_RESIDUAL"
        print(f"\n  核心: 正-value-regime(hml>0)控 value 后 alpha={pos_alpha:+.2f}%/yr t={pos_t:.2f} p={pos_p:.4f}")
        print(f"  → {'FLAT(机械通胀坐实,底仓=value拖累去除+分红/指数方法论非低波alpha)' if pos_flat else '仍显著(low-vol anomaly迹象,与直接低波falsification t=-2.5矛盾须调和)'}")
    print(f"  regime_verdict: {regime_verdict}")

    _dump_result({
        "status": "ok",
        "n_months": len(df),
        "window": {"start": str(df.index[0].date()), "end": str(df.index[-1].date())},
        "descriptive": {
            "corr_mkt_hml": round(corr_mh, 4), "corr_mkt_smb": round(corr_ms, 4),
            "corr_hml_smb": round(corr_hs, 4), "vif_hml_smb": round(vif_hs, 3) if not math.isnan(vif_hs) else None,
            "hml_mean_monthly_pct": round(hml_mean * 100, 4),
            "smb_mean_monthly_pct": round(smb.mean() * 100, 4),
        },
        "M1_capm": m1, "M2_value": m2, "M3_3factor": m3,
        "alpha_change": {
            "M1_alpha_annual": round(a1, 2), "M2_alpha_annual": round(a2, 2), "M3_alpha_annual": round(a3, 2),
            "drop_M1_M2": round(drop_m1_m2, 2), "drop_M1_M3": round(drop_m1_m3, 2),
            "explained_by_value_pct": round(explained_by_value * 100, 1),
        },
        "bonferroni_x3": {"M1": bonferroni_p(p1, 3), "M2": p2_bonf, "M3": p3_bonf},
        "bh_fdr": bh,
        "rolling": {"M2": roll_m2, "M3": roll_m3},
        "regime_subsample": pos_regime_results,
        "regime_verdict": regime_verdict,
        "verdict": verdict,
        "falsified": falsified,
        "actionable": actionable,
    })
    return 0


def _print_reg(r: dict) -> None:
    if r.get("status") == "too_few_obs":
        print(f"  {r['label']}: too few obs (n={r['n']})")
        return
    print(f"  n={r['n']} NW lag={r['nlag']}")
    print(f"  alpha = {r['alpha_pct_monthly']:.5f}%/月 (年化 {r['alpha_annualized_pct']:+.2f}%/yr)")
    print(f"  t(NW-HAC) = {r['alpha_t']:.3f}  p_two={r['alpha_p_two']:.4f}  p_one={r['alpha_p_one']:.4f}")
    print(f"  R² = {r['r_squared']:.4f}  resid_std = {r['resid_std_pct']:.4f}%/月")
    for k, v in r["loadings"].items():
        print(f"    beta_{k} = {v['beta']:+.4f}  (t={v['t']:.3f}, p={v['p_two']:.4f})")


def _dump_result(obj: dict) -> None:
    out = Path(__file__).parent / "_divlowvol_alpha_decompose_result.json"
    out.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n[JSON] -> {out}")


if __name__ == "__main__":
    raise SystemExit(main())
