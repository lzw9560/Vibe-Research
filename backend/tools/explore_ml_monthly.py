# -*- coding: utf-8 -*-
"""explore_ml_monthly.py

散户简化 ML 月频 outward 验证——sklearn 随机森林/梯度提升能否从基本面+技术因子
中榨出单因子测不出的非线性 alpha。

背景（outward-verify memory）：
  - 机构 ML 月频有 alpha（arxiv XGBoost 3632 股 +2.38%/月 t5.94 Sharpe2.23）BUT 散户门槛高
  - 用户"终极架构"评估：GNN 不接（无 Level-2+无 ML 框架+冻结基建+YAGNI）
  - 简化 ML（sklearn RF/GBM）用 fundamentals+技术因子——未测空间
  - 同 250 股 universe 上基本面单因子 9/9 全 FALSIFIED（quality+growth+value）
    → ML 若能找非线性交互救活，是 clean test；若也死=散户 ML 结构性无 edge

数据：
  - 基本面：fundamentals_cache.db（250 股已 backfill，PIT 对齐——报告披露截止日）
  - 技术因子：baostock_kline_cache.db 日线复算（动量/反转/RSI/MACD/波动率/量比/乖离）
  - 月频 close-to-close 收益

ML 设计（严防过拟合）：
  1. 特征矩阵：基本面 6 维（gp/np/roe/debt/rev_growth/ni_growth）+ 技术 9 维（mom_1m/3m/6m,
     rsi_14, macd_hist, vol_20d, vol_ratio, bias_20, amount_log）= 15 特征
  2. 目标：下月收益率（raw decimal）
  3. walk-forward 滚动训练：train window W 个月（测 24/36/48 → 多重比较），predict 月 t
     → TRUE OOS：model 从未见月 t 的收益
  4. top decile long-only equal-weight vs universe equal-weight（cross-sectional alpha）
  5. PIT 对齐：rebalance 日 D 只用 pubdate < D 的最新季报（防 look-ahead）
  6. 技术因子只用 bars up to D（无未来信息）
  7. 成本 0.4% round-trip（月频换手）

过拟合检测（memory skill-backtest-overfit）：
  - DSR（Deflated Sharpe Ratio）：调多重比较（6 trials = 2 model × 3 window）+ 偏度/峰度
  - PBO（Probability of Backtest Overfitting）：CSCV 8 blocks，6 变体，PBO>0.5=过拟合
  - walk-forward train vs test 衰减
  - 多窗口稳定性

kill criteria：
  - DSR < 0.95（过拟合残留）→ falsified
  - PBO > 0.5（选最优 IS 不泛化）→ falsified
  - walk-forward test net_excess < +0.3%/月 OR t_nw < 2.9 → falsified
  - 即使 t>2 标 exploratory（ML 过拟合残留风险）

诚实盲点：
  - 250 股 universe 偏小（机构用 3632），扩 universe 须 backfill（1.9s/股）
  - ML 过拟合风险极高（特征多样本少）→ DSR/PBO 必过
  - A 股因子衰减快（基本面 9/9 已死，ML 若活也可能短期衰减）
  - 散户无机构数据（分析师预期/另类数据）+ 无算力做大规模 ensemble
  - 幸存者偏差：universe = ≥6yr 股（退市股截断，通胀收益）
  - 禁止外推：ML 月频 ≠ 整体散户有/无 edge ≠ 短线有/无 edge

环境：sklearn 1.9.0 已装（xgboost 未装，core-invariant 不擅自 pip install）。
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
import warnings
from collections import defaultdict
from math import erf, log, pi, sqrt
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")  # sklearn convergence warnings etc.

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _factor_helpers import bonferroni_p, norm_sf_positive  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vr_paths import resolve_data_dir  # noqa: E402

from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor  # noqa: E402

DATA = resolve_data_dir()
KLINE_DB = DATA / "baostock_kline_cache.db"
FUND_DB = DATA / "fundamentals_cache.db"
COST = 0.004  # 0.4% round-trip（月频换手）
ALPHA = 0.05

# ── PIT 对齐（复用 fundamental_quality 脚本逻辑）──────────────────────────────


def pit_pubdate(stat_date: str) -> str:
    """报告披露截止日（保守 PIT 估计）。
    Q1(03-31)→04-30, H1(06-30)→08-31, Q3(09-30)→10-31, 年报(12-31)→次年04-30."""
    y, m, d = int(stat_date[:4]), int(stat_date[5:7]), int(stat_date[8:10])
    if m == 3:
        return f"{y}-04-30"
    if m == 6:
        return f"{y}-08-31"
    if m == 9:
        return f"{y}-10-31"
    if m == 12:
        return f"{y + 1}-04-30"
    return stat_date


# ── 数据加载 ──────────────────────────────────────────────────────────────────


def load_fundamentals_pit() -> dict[str, list[dict]]:
    """返 code -> [(pit, stat, gp, np, roe, debt, rg, nig)] 按 pit 排序."""
    if not FUND_DB.exists():
        print("⚠️ fundamentals_cache.db 不存在，无法跑 ML")
        return {}
    conn = sqlite3.connect(str(FUND_DB))
    rows = conn.execute(
        """SELECT code, stat_date, gp_margin, np_margin, roe, debt_ratio, rev_growth, ni_growth
        FROM fundamentals WHERE stat_date >= '2017-01-01' ORDER BY code, stat_date"""
    ).fetchall()
    conn.close()
    by_code: dict[str, list[dict]] = defaultdict(list)
    for code, sd, gp, np_, roe, debt, rg, nig in rows:
        by_code[code].append(
            {
                "pit": pit_pubdate(sd),
                "stat": sd,
                "gp": gp,
                "np": np_,
                "roe": roe,
                "debt": debt,
                "rg": rg,
                "nig": nig,
            }
        )
    # sort each by pit
    for code in by_code:
        by_code[code].sort(key=lambda f: f["pit"])
    return dict(by_code)


def latest_fund_pit(funds: list[dict], rebalance_date: str) -> dict[str, float]:
    """rebalance_date 时点 PIT 可用的最新基本面因子 dict（缺的 None）."""
    avail = [f for f in funds if f["pit"] <= rebalance_date]
    if not avail:
        return {}
    latest = avail[-1]
    return {
        "gp": latest.get("gp"),
        "np": latest.get("np"),
        "roe": latest.get("roe"),
        "debt": latest.get("debt"),
        "rg": latest.get("rg"),
        "nig": latest.get("nig"),
    }


def load_daily_bars(universe: list[str]) -> dict[str, list[dict]]:
    """加载 universe 股的日线 bars（按 date asc）。返 code -> bars list."""
    conn = sqlite3.connect(str(KLINE_DB))
    placeholder = ",".join("?" * len(universe))
    bars_map: dict[str, list[dict]] = {}
    for code, bj in conn.execute(
        f"SELECT code, bars_json FROM kline WHERE code IN ({placeholder})", universe
    ):
        try:
            bars = json.loads(bj)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(bars, list) or not bars:
            continue
        bars.sort(key=lambda b: b.get("date", ""))
        bars_map[code] = bars
    conn.close()
    return bars_map


def compute_month_ends(bars_map: dict[str, list[dict]]) -> list[str]:
    """所有 universe 股的月末交易日日期（sorted）。月末 = 该月最后一个有 bar 的日期."""
    by_month: dict[str, str] = {}  # month(YYYY-MM) -> latest date
    for bars in bars_map.values():
        for b in bars:
            d = b.get("date", "")
            if not d or len(d) < 7:
                continue
            month = d[:7]
            prev = by_month.get(month)
            if prev is None or d > prev:
                by_month[month] = d
    return sorted(by_month.values())


# ── 技术因子（从日线 bars 复算，只用 rebalance_date 之前数据）──────────────────


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    out = [values[0]]
    for i in range(1, len(values)):
        out.append(values[i] * k + out[i - 1] * (1 - k))
    return out


def _rsi(closes: list[float], period: int) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = closes[i] - closes[i - 1]
        if diff > 0:
            gains += diff
        else:
            losses += -diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_tech_features(bars_up_to: list[dict]) -> dict[str, float]:
    """从日线 bars（截至 rebalance 日，含当日）算技术因子。缺数据返 None."""
    closes = [float(b.get("close", 0) or 0) for b in bars_up_to if b.get("close")]
    vols = [float(b.get("volume", 0) or 0) for b in bars_up_to if b.get("volume") is not None]
    amts = [float(b.get("amount", 0) or 0) for b in bars_up_to if b.get("amount") is not None]
    feats: dict[str, float | None] = {}

    if len(closes) < 20:
        return {k: None for k in (
            "mom_1m", "mom_3m", "mom_6m", "rsi_14", "macd_hist",
            "vol_20d", "vol_ratio", "bias_20", "amount_log",
        )}

    cur = closes[-1]
    # momentum（用 ~21/63/126 交易日 ≈ 1/3/6 月）
    feats["mom_1m"] = (cur / closes[-21] - 1) if len(closes) > 21 and closes[-21] > 0 else None
    feats["mom_3m"] = (cur / closes[-63] - 1) if len(closes) > 63 and closes[-63] > 0 else None
    feats["mom_6m"] = (cur / closes[-126] - 1) if len(closes) > 126 and closes[-126] > 0 else None

    feats["rsi_14"] = _rsi(closes, 14)

    # MACD histogram
    if len(closes) >= 26:
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        dif = [ema12[i] - ema26[i] for i in range(len(closes))]
        dea = _ema(dif, 9)
        feats["macd_hist"] = dif[-1] - dea[-1] if len(dea) > 0 else None
    else:
        feats["macd_hist"] = None

    # 20日实现波动率（日收益 std）
    if len(closes) > 21:
        rets_20 = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(-20, 0) if closes[i - 1] > 0]
        feats["vol_20d"] = statistics.pstdev(rets_20) if len(rets_20) > 1 else None
    else:
        feats["vol_20d"] = None

    # 量比（最近量 / 前5日均量）
    if len(vols) >= 6 and vols[-6:-1]:
        avg5 = sum(vols[-6:-1]) / 5
        feats["vol_ratio"] = vols[-1] / avg5 if avg5 > 0 else None
    else:
        feats["vol_ratio"] = None

    # 乖离率 vs MA20
    ma20 = _sma(closes, 20)
    feats["bias_20"] = (cur - ma20) / ma20 * 100 if ma20 and ma20 > 0 else None

    # log(amount_20d) — 流动性特征
    if len(amts) >= 20:
        avg_amt = sum(amts[-20:]) / 20
        feats["amount_log"] = log(avg_amt + 1) if avg_amt > 0 else None
    else:
        feats["amount_log"] = None

    return feats


TECH_FEATS = ["mom_1m", "mom_3m", "mom_6m", "rsi_14", "macd_hist",
              "vol_20d", "vol_ratio", "bias_20", "amount_log"]
FUND_FEATS = ["gp", "np", "roe", "debt", "rg", "nig"]
ALL_FEATS = FUND_FEATS + TECH_FEATS


# ── 构建面板 (code, month) → features + target ───────────────────────────────


def build_panel(
    universe: list[str],
    bars_map: dict[str, list[dict]],
    funds: dict[str, list[dict]],
    month_ends: list[str],
) -> list[dict]:
    """构建 ML 面板：每行 = (code, rebalance_month_end) → 15 特征 + next_month_return(target).

    target = 下月 close-to-close 收益（rebalance 月末 close → 下月末 close）。
    技术因子只用 rebalance 月末及之前 bars（无 look-ahead）。
    基本面 PIT 对齐（pubdate < rebalance_date）。
    """
    # code -> date_idx (bars sorted by date)
    code_date_idx: dict[str, dict[str, int]] = {}
    code_bars: dict[str, list[dict]] = {}
    for code in universe:
        bars = bars_map.get(code, [])
        if not bars:
            continue
        code_bars[code] = bars
        code_date_idx[code] = {b["date"]: i for i, b in enumerate(bars) if b.get("date")}

    # month_end close per code
    code_month_close: dict[str, dict[str, float]] = defaultdict(dict)
    for code, bars in code_bars.items():
        by_month: dict[str, tuple[str, float]] = {}
        for b in bars:
            d = b.get("date", "")
            if not d or len(d) < 7:
                continue
            c = b.get("close")
            try:
                c = float(c) if c else None
            except (ValueError, TypeError):
                c = None
            if c is None or c <= 0:
                continue
            month = d[:7]
            prev = by_month.get(month)
            if prev is None or d > prev[0]:
                by_month[month] = (d, c)
        for month, (d, c) in by_month.items():
            code_month_close[code][d] = c

    # month_ends sorted; need next month_end for target
    me_sorted = sorted(month_ends)
    me_idx = {d: i for i, d in enumerate(me_sorted)}

    panel: list[dict] = []
    for code in universe:
        bars = code_bars.get(code)
        if not bars:
            continue
        fl = funds.get(code)
        mc = code_month_close.get(code, {})
        sorted_mc = sorted(mc.keys())
        for i, me_date in enumerate(sorted_mc):
            if me_date < "2018-06-01":  # need warmup for 6m momentum
                continue
            # next month_end for target
            mi = me_idx.get(me_date)
            if mi is None or mi + 1 >= len(me_sorted):
                continue
            next_me = me_sorted[mi + 1]
            next_close = mc.get(next_me)
            cur_close = mc[me_date]
            if next_close is None or cur_close is None or cur_close <= 0:
                continue
            target = (next_close - cur_close) / cur_close

            # technical features: bars up to and including me_date
            di = code_date_idx[code].get(me_date)
            if di is None or di < 126:
                continue
            bars_up_to = bars[: di + 1]
            tech = compute_tech_features(bars_up_to)

            # fundamentals PIT
            fund_vals = latest_fund_pit(fl, me_date) if fl else {}

            row = {"code": code, "month": me_date, "target": target}
            for f in FUND_FEATS:
                row[f] = fund_vals.get(f)
            for f in TECH_FEATS:
                row[f] = tech.get(f)
            panel.append(row)

    return panel


# ── precompute feature matrix (once, then slice in walk-forward) ─────────────


def precompute_matrix(panel: list[dict]) -> dict:
    """Convert panel list-of-dicts → numpy arrays for fast slicing.

    Returns {months, feat_matrix, target_vec, month_idx, n_feats}.
    feat_matrix has NaN for missing features (imputed per-train-window later).
    """
    by_month: dict[str, list[dict]] = defaultdict(list)
    for row in panel:
        by_month[row["month"]].append(row)
    months = sorted(by_month.keys())
    month_pos = {m: i for i, m in enumerate(months)}

    n_feats = len(ALL_FEATS)
    feat_rows: list[list[float]] = []
    targets: list[float] = []
    month_indices: list[int] = []

    for m in months:
        mi = month_pos[m]
        for r in by_month[m]:
            row_feats: list[float] = []
            for f in ALL_FEATS:
                v = r.get(f)
                if v is None or (isinstance(v, float) and v != v):
                    row_feats.append(float("nan"))
                else:
                    row_feats.append(float(v))
            feat_rows.append(row_feats)
            targets.append(float(r["target"]))
            month_indices.append(mi)

    return {
        "months": months,
        "feat_matrix": np.array(feat_rows, dtype=float),
        "target_vec": np.array(targets, dtype=float),
        "month_idx": np.array(month_indices, dtype=int),
        "n_feats": n_feats,
    }


# ── walk-forward ML backtest ─────────────────────────────────────────────────


def walk_forward_ml(
    pmatrix: dict,
    model_name: str,
    train_window: int,
) -> dict:
    """滚动 walk-forward ML backtest (precomputed matrix, fast slicing).

    train_window: 训练窗口月数（用过去 train_window 月的面板训练，predict 下月）。
    model_name: 'rf' (RandomForest) 或 'gbm' (GradientBoosting).

    每 rebalance 月 t：
      - train 用 month in [t-train_window, t-1] 的面板行（features + target）
      - predict 月 t 所有可交易股的 score
      - top decile equal-weight → strategy return
      - universe equal-weight → benchmark return
    返回 monthly excess returns + dates。
    """
    months = pmatrix["months"]
    feat = pmatrix["feat_matrix"]
    tgt = pmatrix["target_vec"]
    midx = pmatrix["month_idx"]
    n_months = len(months)

    if n_months < train_window + 6:
        return {"status": "too_few", "n_months": n_months}

    strategy_rets: list[float] = []
    benchmark_rets: list[float] = []
    excess_rets: list[float] = []
    dates_used: list[str] = []

    for i in range(train_window, n_months - 1):
        me_date = months[i]
        # train mask: months [i-train_window, i-1]
        train_mask = (midx >= i - train_window) & (midx < i)
        test_mask = midx == i

        X_train = feat[train_mask].copy()
        y_train = tgt[train_mask]
        X_test = feat[test_mask].copy()
        y_test = tgt[test_mask]

        if len(X_train) < 200 or len(X_test) < 20:
            continue

        # median-impute from TRAIN only (no look-ahead)
        col_med = np.nanmedian(X_train, axis=0)
        col_med = np.where(np.isnan(col_med) | np.isinf(col_med), 0.0, col_med)
        # impute train
        for ci in range(X_train.shape[1]):
            col = X_train[:, ci]
            mask = np.isnan(col) | np.isinf(col)
            if mask.any():
                col[mask] = col_med[ci]
        # impute test with SAME train medians
        for ci in range(X_test.shape[1]):
            col = X_test[:, ci]
            mask = np.isnan(col) | np.isinf(col)
            if mask.any():
                col[mask] = col_med[ci]

        # model — reduced complexity for speed + anti-overfit
        if model_name == "rf":
            model = RandomForestRegressor(
                n_estimators=50, max_depth=4, min_samples_leaf=80,
                random_state=42, n_jobs=-1,
            )
        else:  # gbm
            model = GradientBoostingRegressor(
                n_estimators=60, max_depth=3, learning_rate=0.08,
                min_samples_leaf=80, random_state=42,
            )
        model.fit(X_train, y_train)

        scores = model.predict(X_test)

        # top decile by predicted score
        order = np.argsort(-scores)  # descending
        n_top = max(5, len(scores) // 10)
        top_idx = order[:n_top]

        strat_ret = float(np.mean(y_test[top_idx]))
        bench_ret = float(np.mean(y_test))  # equal-weight all
        strat_net = strat_ret - COST
        excess = strat_net - bench_ret

        strategy_rets.append(strat_net * 100)
        benchmark_rets.append(bench_ret * 100)
        excess_rets.append(excess * 100)
        dates_used.append(me_date)

    if len(excess_rets) < 24:
        return {"status": "too_few", "n_months": len(excess_rets)}

    return {
        "status": "ok",
        "model": model_name,
        "train_window": train_window,
        "n_months": len(excess_rets),
        "dates": dates_used,
        "excess": excess_rets,
        "strategy": strategy_rets,
        "benchmark": benchmark_rets,
    }


# ── stats（NW t for monthly）─────────────────────────────────────────────────


def nw_t_monthly(rets: list[float], max_lag: int = 3) -> dict:
    """Newey-West t for monthly returns (Bartlett weights, lag ~3)."""
    n = len(rets)
    if n < 5:
        return {"mean": 0, "t": 0, "p": 1, "n": n}
    m = statistics.mean(rets)
    mean_centered = [x - m for x in rets]
    gamma0 = sum(x * x for x in mean_centered) / n
    rho_sum = 0.0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_lag = sum(mean_centered[i] * mean_centered[i - lag] for i in range(lag, n)) / n
        rho_sum += w * gamma_lag / gamma0 if gamma0 > 0 else 0
    n_eff = n / (1 + 2 * rho_sum) if (1 + 2 * rho_sum) > 0 else n
    se = sqrt(gamma0) / sqrt(n_eff) if gamma0 > 0 else 0
    t = m / se if se > 0 else 0
    p = norm_sf_positive(t)
    return {"mean": round(m, 4), "t": round(t, 3), "p": round(p, 6), "n": n, "n_eff": round(n_eff, 1)}


# ── DSR（Deflated Sharpe Ratio）───────────────────────────────────────────────

EULER_GAMMA = 0.5772156649015329


def deflated_sharpe_ratio(monthly_rets: list[float], n_trials: int) -> dict:
    """Deflated Sharpe Ratio（Bailey & López de Prado 2014）.

    调多重比较（n_trials）+ 偏度/峰度。DSR = P(true SR > deflated benchmark SR_0).
    DSR < 0.95 → 过拟合残留风险（kill criteria）。
    """
    from scipy.stats import kurtosis as sp_kurtosis, norm as sp_norm, skew as sp_skew

    arr = np.array(monthly_rets, dtype=float)
    T = len(arr)
    if T < 3:
        return {"dsr": 0.0, "sr_monthly": 0, "sr_annual": 0, "sr_0": 0, "T": T}
    mu = float(np.mean(arr))
    sd = float(np.std(arr, ddof=1))
    if sd <= 0:
        return {"dsr": 0.5, "sr_monthly": 0, "sr_annual": 0, "sr_0": 0, "T": T}
    sr = mu / sd  # monthly Sharpe
    sr_annual = sr * sqrt(12)
    sk = float(sp_skew(arr))
    kt = float(sp_kurtosis(arr, fisher=True))  # excess kurtosis (normal=0)

    # variance of SR estimator: (1 - skew*SR + (kurt4-1)/4 * SR^2) / (T-1)
    # kurt4 (4th standardized moment, normal=3) = excess + 3
    kurt4 = kt + 3
    var_sr = (1 - sk * sr + (kurt4 - 1) / 4 * sr * sr) / (T - 1)
    if var_sr <= 0:
        var_sr = 1e-12

    # deflated benchmark SR_0 = expected max of n_trials iid SR estimates under null
    # E[max_N standard normals] ≈ z* - (γ + ln(4π ln N)) / (2z*), z* = sqrt(2 ln N)
    if n_trials > 1:
        z_star = sqrt(2 * log(n_trials))
        sr_0_unit = z_star - (EULER_GAMMA + log(4 * pi * log(n_trials))) / (2 * z_star)
    else:
        sr_0_unit = 0.0
    sr_0 = sr_0_unit * sqrt(var_sr)  # deflated benchmark in SR units

    # DSR = PSR(SR_hat | SR_0) = Φ((SR_hat - SR_0) / sqrt(var_sr))
    dsr = float(sp_norm.cdf((sr - sr_0) / sqrt(var_sr)))

    return {
        "dsr": round(dsr, 4),
        "sr_monthly": round(sr, 4),
        "sr_annual": round(sr_annual, 4),
        "sr_0": round(sr_0, 4),
        "sr_0_unit": round(sr_0_unit, 4),
        "var_sr": round(var_sr, 8),
        "T": T,
        "n_trials": n_trials,
        "skew": round(sk, 3),
        "kurt_excess": round(kt, 3),
    }


# ── PBO（Probability of Backtest Overfitting, CSCV）──────────────────────────


def pbo_cscv(variant_rets: dict[str, list[float]], n_blocks: int = 8) -> dict:
    """Probability of Backtest Overfitting via Combinatorial Symmetric CV.

    variant_rets: {variant_name: monthly_excess_returns}（各变体等长同日期）.
    n_blocks: split into n_blocks blocks, choose half IS / half OOS.

    PBO = P(IS-optimal variant ranks in bottom half OOS). PBO > 0.5 → overfitting.
    """
    from itertools import combinations

    names = list(variant_rets.keys())
    M = len(names)
    if M < 2:
        return {"pbo": 0.0, "n_combos": 0}
    # align lengths
    min_len = min(len(v) for v in variant_rets.values())
    if min_len < n_blocks * 2:
        return {"pbo": 0.0, "n_combos": 0, "note": f"too few months {min_len} for {n_blocks} blocks"}
    # truncate to min_len
    matrix = np.array([variant_rets[n][:min_len] for n in names])  # shape (M, T)

    # split into n_blocks equal blocks
    block_size = min_len // n_blocks
    usable = block_size * n_blocks
    matrix = matrix[:, :usable]
    blocks = [matrix[:, i * block_size:(i + 1) * block_size] for i in range(n_blocks)]

    half = n_blocks // 2
    combos = list(combinations(range(n_blocks), half))
    n_combos = len(combos)
    overfit_count = 0
    rank_counts = []

    for is_blocks in combos:
        oos_blocks = [b for b in range(n_blocks) if b not in is_blocks]
        # IS Sharpe per variant
        is_rets = np.concatenate([blocks[b] for b in is_blocks], axis=1)  # (M, T_is)
        oos_rets = np.concatenate([blocks[b] for b in oos_blocks], axis=1)  # (M, T_oos)

        is_sr = np.zeros(M)
        oos_sr = np.zeros(M)
        for v in range(M):
            is_arr = is_rets[v]
            oos_arr = oos_rets[v]
            is_sd = np.std(is_arr, ddof=1)
            oos_sd = np.std(oos_arr, ddof=1)
            is_sr[v] = np.mean(is_arr) / is_sd if is_sd > 0 else 0
            oos_sr[v] = np.mean(oos_arr) / oos_sd if oos_sd > 0 else 0

        best_is = int(np.argmax(is_sr))
        # rank of best_is in OOS (1=best, M=worst)
        oos_rank = int(np.argsort(-oos_sr).tolist().index(best_is)) + 1
        rank_counts.append(oos_rank)
        # overfit if best IS is in bottom half of OOS
        if oos_rank > M // 2:
            overfit_count += 1

    pbo = overfit_count / n_combos if n_combos > 0 else 0
    return {
        "pbo": round(pbo, 4),
        "n_combos": n_combos,
        "n_variants": M,
        "n_blocks": n_blocks,
        "mean_oos_rank": round(statistics.mean(rank_counts), 2) if rank_counts else 0,
        "median_oos_rank": round(statistics.median(rank_counts), 2) if rank_counts else 0,
    }


# ── main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    # 1. load data
    print("=== load data ===")
    funds = load_fundamentals_pit()
    print(f"fundamentals: {len(funds)} stocks cached (PIT aligned)")
    if len(funds) < 50:
        print(f"⚠️ fundamentals {len(funds)} < 50，无法跑 ML")
        return

    universe = [c for c in funds.keys()]
    bars_map = load_daily_bars(universe)
    # keep only stocks with enough bars
    universe = [c for c in universe if len(bars_map.get(c, [])) >= 126]
    print(f"universe: {len(universe)} stocks (fundamentals + >=126 daily bars)")

    month_ends = compute_month_ends(bars_map)
    print(f"month_ends: {len(month_ends)} ({month_ends[0]} ~ {month_ends[-1]})")

    # 2. build panel
    print("\n=== build ML panel ===")
    panel = build_panel(universe, bars_map, funds, month_ends)
    months_in_panel = sorted(set(r["month"] for r in panel))
    codes_in_panel = sorted(set(r["code"] for r in panel))
    print(f"panel: {len(panel)} rows, {len(codes_in_panel)} codes, {len(months_in_panel)} months")
    print(f"panel months: {months_in_panel[0]} ~ {months_in_panel[-1]}")

    # feature coverage
    print("\n--- feature coverage (non-null %) ---")
    for f in ALL_FEATS:
        n_valid = sum(1 for r in panel if r.get(f) is not None and not (isinstance(r[f], float) and r[f] != r[f]))
        print(f"  {f}: {n_valid}/{len(panel)} ({n_valid / len(panel) * 100:.1f}%)")

    # precompute feature matrix once (fast numpy slicing in walk-forward)
    print("\n=== precompute feature matrix ===", flush=True)
    pmatrix = precompute_matrix(panel)
    print(f"matrix: {pmatrix['feat_matrix'].shape} feats, {len(pmatrix['months'])} months", flush=True)

    # 3. walk-forward ML — multiple model × window combos
    print(f"\n{'=' * 70}")
    print("=== walk-forward ML backtest (TRUE OOS, rolling train window) ===", flush=True)
    print(f"{'=' * 70}")

    configs = [
        ("rf", 24), ("rf", 36), ("rf", 48),
        ("gbm", 24), ("gbm", 36), ("gbm", 48),
    ]
    results: dict[str, dict] = {}
    for model_name, tw in configs:
        label = f"{model_name}_w{tw}"
        print(f"\n--- {label} (train_window={tw}m) ---", flush=True)
        r = walk_forward_ml(pmatrix, model_name, tw)
        if r["status"] != "ok":
            print(f"  {r['status']} (n={r.get('n_months', 0)})", flush=True)
            continue
        results[label] = r
        nw = nw_t_monthly(r["excess"])
        wr = sum(1 for x in r["excess"] if x > 0) / len(r["excess"]) * 100
        strat_mean = statistics.mean(r["strategy"])
        bench_mean = statistics.mean(r["benchmark"])
        print(f"  n={nw['n']} months")
        print(f"  strategy(net): {strat_mean:.4f}%/月 | benchmark: {bench_mean:.4f}%/月")
        print(f"  excess(net): mean={nw['mean']:.4f}%/月 WR={wr:.1f}% t_nw={nw['t']} p={nw['p']}", flush=True)

        # walk-forward train/test split (50/50)
        mid = len(r["excess"]) // 2
        train = r["excess"][:mid]
        test = r["excess"][mid:]
        tr_nw = nw_t_monthly(train)
        te_nw = nw_t_monthly(test)
        print(f"  train(前半): {tr_nw['mean']:.4f}% t_nw={tr_nw['t']}")
        print(f"  test(后半):  {te_nw['mean']:.4f}% t_nw={te_nw['t']}")
        if tr_nw["mean"] != 0:
            decay = (tr_nw["mean"] - te_nw["mean"]) / abs(tr_nw["mean"]) * 100
            print(f"  衰减: {decay:.0f}% (train→test)", flush=True)

    if not results:
        print("\n⚠️ 所有 config 都 too_few，无法跑 ML verdict")
        return

    # 4. DSR + PBO overfitting checks
    N_TRIALS = len(results)  # multiple testing = number of configs tried
    print(f"\n{'=' * 70}")
    print(f"=== 过拟合检测 (DSR + PBO, n_trials={N_TRIALS}) ===")
    print(f"{'=' * 70}")

    print("\n--- DSR (Deflated Sharpe Ratio) per variant ---")
    for label, r in results.items():
        dsr_r = deflated_sharpe_ratio(r["excess"], N_TRIALS)
        r["dsr"] = dsr_r
        print(f"  {label}: SR_m={dsr_r['sr_monthly']} SR_a={dsr_r['sr_annual']} "
              f"SR_0(deflated)={dsr_r['sr_0']} DSR={dsr_r['dsr']} "
              f"skew={dsr_r['skew']} kurt={dsr_r['kurt_excess']} T={dsr_r['T']}")

    # PBO across all variants (align to min length)
    print("\n--- PBO (Probability of Backtest Overfitting, CSCV 8 blocks) ---")
    # use excess returns of each variant
    variant_excess = {label: r["excess"] for label, r in results.items()}
    pbo_r = pbo_cscv(variant_excess, n_blocks=8)
    print(f"  PBO={pbo_r['pbo']} n_combos={pbo_r['n_combos']} n_variants={pbo_r['n_variants']}")
    print(f"  mean OOS rank of IS-best: {pbo_r['mean_oos_rank']} / {pbo_r['n_variants']} "
          f"(median {pbo_r['median_oos_rank']})")
    if "note" in pbo_r:
        print(f"  note: {pbo_r['note']}")

    # 5. pick best variant by full-period excess mean (in-sample selection — this is what we'd do)
    # but report DSR-adjusted
    best_label = max(results.keys(), key=lambda l: statistics.mean(results[l]["excess"]))
    best = results[best_label]
    print(f"\n{'=' * 70}")
    print(f"=== VERDICT (best variant by full-period excess: {best_label}) ===")
    print(f"{'=' * 70}")

    bw = nw_t_monthly(best["excess"])
    mid = len(best["excess"]) // 2
    test_excess = best["excess"][mid:]
    test_nw = nw_t_monthly(test_excess)
    dsr_best = best.get("dsr", {})

    print(f"\n  best variant: {best_label}")
    print(f"  full: excess={bw['mean']:.4f}%/月 t_nw={bw['t']} p={bw['p']} WR={sum(1 for x in best['excess'] if x>0)/len(best['excess'])*100:.1f}%")
    print(f"  test(后半): excess={test_nw['mean']:.4f}%/月 t_nw={test_nw['t']}")
    print(f"  SR_monthly={dsr_best.get('sr_monthly')} SR_annual={dsr_best.get('sr_annual')}")
    print(f"  DSR={dsr_best.get('dsr')} (n_trials={N_TRIALS}, threshold 0.95)")
    print(f"  PBO={pbo_r['pbo']} (threshold 0.5)")

    # kill criteria cascade
    print(f"\n  --- kill criteria ---")
    verdict = "exploratory"  # default for ML even if passes (overfitting residual risk)
    falsified_reasons = []

    # 1. DSR < 0.95
    if dsr_best.get("dsr", 0) < 0.95:
        print(f"  ⚠ DSR={dsr_best.get('dsr')} < 0.95 → 过拟合残留风险")
        falsified_reasons.append(f"DSR={dsr_best.get('dsr')}<0.95")

    # 2. PBO > 0.5
    if pbo_r["pbo"] > 0.5:
        print(f"  ⚠ PBO={pbo_r['pbo']} > 0.5 → IS-optimal 不泛化（过拟合）")
        falsified_reasons.append(f"PBO={pbo_r['pbo']}>0.5")

    # 3. walk-forward test net_excess < +0.3%/月
    if test_nw["mean"] < 0.3:
        print(f"  ⚠ test net_excess={test_nw['mean']:.4f}% < +0.3%/月 threshold")
        falsified_reasons.append(f"test_excess={test_nw['mean']:.4f}%<0.3%")

    # 4. t_nw < 2.9 (Harvey-style)
    if bw["t"] < 2.9:
        print(f"  ⚠ t_nw={bw['t']} < 2.9 (Harvey threshold)")
        falsified_reasons.append(f"t_nw={bw['t']}<2.9")

    # 5. test half negative
    if test_nw["mean"] <= 0:
        print(f"  ⚠ test(后半) net_excess={test_nw['mean']:.4f}% <= 0 → OOS 无 edge")
        falsified_reasons.append("test_half_negative")

    if falsified_reasons:
        verdict = "falsified"
        print(f"\n  → FALSIFIED: {'; '.join(falsified_reasons)}")
    elif bw["t"] >= 2.9 and dsr_best.get("dsr", 0) >= 0.95 and pbo_r["pbo"] <= 0.5 and test_nw["mean"] > 0.3:
        print(f"\n  → EXPLORATORY: 统计通过但 ML 过拟合残留风险，标 exploratory 非 confirmed")
        verdict = "exploratory"
    else:
        print(f"\n  → EXPLORATORY: 边缘，统计未完全通过")

    # honest blindspots
    print(f"\n  --- 诚实盲点 ---")
    print(f"  1. universe={len(universe)} 股偏小（机构 ML 用 3632），扩 universe 须 backfill（1.9s/股）")
    print(f"  2. ML 过拟合残留：15 特征 × {len(universe)} 股 × 月频，参数/样本比高")
    print(f"  3. 基本面 9/9 单因子在这 250 股已 FALSIFIED——ML 若活=非线性交互救活，若死=结构性")
    print(f"  4. 散户无机构数据（分析师预期/另类数据）+ 无算力 ensemble")
    print(f"  5. 幸存者偏差：universe=≥6yr 股（退市截断通胀收益）")
    print(f"  6. 禁止外推：ML 月频 ≠ 整体散户有/无 edge")

    # save result
    out = {
        "verdict": verdict,
        "best_variant": best_label,
        "n_universe": len(universe),
        "n_trials": N_TRIALS,
        "best_dsr": dsr_best.get("dsr"),
        "pbo": pbo_r["pbo"],
        "best_full": {"mean": bw["mean"], "t_nw": bw["t"], "p": bw["p"]},
        "best_test": {"mean": test_nw["mean"], "t_nw": test_nw["t"]},
        "falsified_reasons": falsified_reasons,
        "all_variants": {
            label: {
                "n": r["n_months"],
                "excess_mean": round(statistics.mean(r["excess"]), 4),
                "t_nw": nw_t_monthly(r["excess"])["t"],
                "dsr": r.get("dsr", {}).get("dsr"),
                "sr_annual": r.get("dsr", {}).get("sr_annual"),
            }
            for label, r in results.items()
        },
    }
    p = Path(__file__).parent / "explore_ml_monthly_result.txt"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nresult JSON -> {p}")


if __name__ == "__main__":
    main()
