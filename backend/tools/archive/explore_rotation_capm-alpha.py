# -*- coding: utf-8 -*-
"""CAPM / Jensen's alpha test for sector-rotation strategy (alpha-isolated from beta).

METHOD (per workflow assignment):
  Long-only top-3 sector rotation. Rank 25 dense-core industries by past-N-week
  momentum, hold top-3 equal-weight for 2 weeks, rebalance every 2 weeks.
  Regress strategy returns on market:  r_strat = alpha + beta * r_mkt + e
  alpha (intercept) = risk-adjusted alpha, ISOLATED from market beta.

WHY THIS ISOLATES ALPHA (the original flaw's fix):
  Original methodology judged the strategy by absolute EV > 0 — but a long-only
  strategy's absolute return = beta*r_market + alpha, so in a bull market any
  long-only strategy looks "profitable" purely from beta, not from timing/skill.
  The CAPM regression strips out beta*r_market (the slope coefficient), leaving
  alpha (the intercept) as the pure timing/skill component. Unlike long-short
  (which needs 融券/margin), CAPM isolates beta ANALYTICALLY — long-only top-3
  is fully retail-implementable via sector ETFs or constituent stocks.

STRICT GUARDS (preserved):
  - realistic T+1: form at close of day t (momentum uses returns up to t),
    hold t+1..t+10 — no look-ahead (holding returns never enter the signal)
  - non-overlapping 2-week blocks (rebalance every 10 trading days) => N = n_rebalances
    clean per-rebalance-block inference (independent blocks, no overlap inflation)
  - daily HAC (Newey-West, maxlag = holding) as cross-check on the same alpha
  - Bonferroni x4 (4 parallel alpha-isolation methods) x3 (formation search 2/3/4 wk) = x12
  - walk-forward OOS: first-half train (require train_alpha > 0) -> second-half test
  - turnover cost deducted for net alpha (realistic tradeability)
  - NO extrapolation: sector-rotation CAPM alpha != "rotation has/has-no edge" !=
    "short-term has/has-no edge" — this is one method, one window, one signal family.

DATA:
  .vibe-research/sector_rotation_data.json  (built by build_sector_returns.py)
  - 25 dense-core industries (>=10 codes with >=5yr history); banks/insurance ABSENT
  - returns: equal-weight industry-aggregate daily, decimal, close-to-close (raw unadjusted)
  - benchmark: sh.000001 上证指数 pctChg/100, aligned
  - clean window: 2018-01-03 .. 2025-11-28 (cut before recent-wave 2025-12-01 to keep
    cross-section composition stable; recent wave adds ~4293 thin-history codes)

USAGE:
  cd backend && .venv/bin/python tools/explore_rotation_capm-alpha.py
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
from scipy import stats  # noqa: F401  (available; norm cdf for one-sided p)

# statsmodels installed for this task (OLS + HAC SE)
import statsmodels.api as sm

# shared helpers (DRY: ev_stats / day_paired_t / bonferroni_p / walk_forward)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools._factor_helpers import bonferroni_p, ev_stats  # noqa: E402

# ---------- config ----------

# 数据路径统一走 vr_paths.resolve_data_dir()（S037 收口）

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vr_paths import resolve_data_dir


ROOT = Path(__file__).resolve().parents[2]
DATA_JSON = resolve_data_dir() / "sector_rotation_data.json"

# 25 dense-core industries (>=10 codes with >=5yr / 1218-bar history).
# NOTE: 银行Ⅱ (banks, 42 codes) and 保险Ⅱ (insurance) have ZERO long-history
# codes => major financial sectors ABSENT from this 2018-2025 rotation.
DENSE_INDUSTRIES = [
    "电网设备",
    "电力",
    "化学制药",
    "通用设备",
    "IT服务Ⅱ",
    "化学制品",
    "专用设备",
    "软件开发",
    "房地产开发",
    "半导体",
    "汽车零部件",
    "通信设备",
    "计算机设备",
    "元件",
    "消费电子",
    "光学光电子",
    "中药Ⅱ",
    "塑料",
    "医疗服务",
    "工业金属",
    "煤炭开采",
    "一般零售",
    "电池",
    "环境治理",
    "化学原料",
]

TRADING_DAYS_PER_WEEK = 5
HOLDING_WEEKS = 2  # hold 2 weeks = 10 trading days, rebalance every 10 days
FORMATION_WEEKS_GRID = [2, 3, 4]  # search formation lookback
TOP_K = 3
N_METHODS = 4  # Bonferroni: 4 parallel alpha-isolation methods
N_FORMATION_SEARCH = 3  # Bonferroni: 3 formation periods searched
N_BONF = N_METHODS * N_FORMATION_SEARCH  # = 12
ALPHA_LEVEL = 0.05
ROUND_TRIP_COST = 0.003  # 0.3% round-trip (commission+stamp+slippage), per project COST
HOLD_DAYS = HOLDING_WEEKS * TRADING_DAYS_PER_WEEK  # 10
HAC_MAXLAG = HOLD_DAYS  # Newey-West lag >= holding period (within-block autocorrelation)
BLOCKS_PER_YEAR = 252 / HOLD_DAYS  # ~25.2 two-week blocks per year
TRADING_DAYS_PER_YEAR = 252
MIN_BLOCKS = 60  # power floor (n_rebalances >= 60)


# ---------- data loading ----------


def load_clean_window() -> tuple[list[str], list[str], np.ndarray, np.ndarray]:
    """Load sector_rotation_data.json, restrict to 25 dense industries, cut to
    2018-2025 clean window (before recent wave 2025-12-01)."""
    d = json.load(open(DATA_JSON))
    dates_all = d["dates"]
    bench_all = d["benchmark"]["returns"]
    sr = d["sector_returns"]

    inds = [i for i in DENSE_INDUSTRIES if i in sr]
    missing = [i for i in DENSE_INDUSTRIES if i not in sr]
    if missing:
        print(f"WARNING: {len(missing)} dense industries missing from data: {missing}")

    n_all = len(dates_all)
    m = len(inds)
    R_all = np.full((n_all, m), np.nan)
    for j, ind in enumerate(inds):
        col = sr[ind]
        for i, v in enumerate(col):
            if v is not None:
                R_all[i, j] = float(v)
    bench_all_arr = np.array([float(b) if b is not None else np.nan for b in bench_all], dtype=float)

    # cut at 2025-12-01 (recent-wave onset) to keep cross-section composition stable
    cut_idx = next((i for i, dt in enumerate(dates_all) if dt >= "2025-12-01"), n_all)
    # also drop any trailing degenerate dates (dense coverage < 20) inside the window
    dense_cov = np.sum(~np.isnan(R_all[:cut_idx]), axis=1)
    good = dense_cov >= 20
    last_good = np.where(good)[0][-1] if good.any() else cut_idx - 1
    end = min(cut_idx, last_good + 1)

    dates = dates_all[:end]
    R = R_all[:end]
    bench = bench_all_arr[:end]
    return dates, inds, R, bench


# ---------- strategy construction ----------


def sector_momentum(R: np.ndarray, t_idx: int, form_days: int) -> np.ndarray:
    """Cumulative return over past `form_days` returns ending at t_idx (inclusive).
    Returns nan for industries with any gap in the window (excluded from top-k)."""
    if t_idx - form_days + 1 < 0:
        return np.full(R.shape[1], np.nan)
    seg = R[t_idx - form_days + 1 : t_idx + 1]  # form_days x n_inds
    # fill nan with 0.0 (missing day = no contribution) for prod, BUT mark
    # industries whose WHOLE window is nan as nan
    seg_filled = np.where(np.isnan(seg), 0.0, seg)
    mom = np.prod(1.0 + seg_filled, axis=0) - 1.0
    # if an industry had NO valid return in the window, mark nan
    any_valid = np.any(~np.isnan(seg), axis=0)
    mom = np.where(any_valid, mom, np.nan)
    return mom


def build_rotation(
    dates: list[str],
    R: np.ndarray,
    bench: np.ndarray,
    formation_weeks: int,
    holding_weeks: int = HOLDING_WEEKS,
    top_k: int = TOP_K,
) -> dict:
    """Long-only top-K sector rotation. Non-overlapping 2-week blocks.

    Realistic T+1: momentum formed at close of day t (returns up to t),
    hold t+1..t+hold_days. Blocks are non-overlapping (rebalance every hold_days).

    Returns dict with:
      strat_daily / mkt_daily   : aligned arrays over all holding days
      blocks                     : list of per-block {date, top_sectors, strat_block,
                                  mkt_block, turnover, n_new}
      n_rebalances
    """
    n = len(dates)
    form_days = formation_weeks * TRADING_DAYS_PER_WEEK
    hold_days = holding_weeks * TRADING_DAYS_PER_WEEK

    strat_daily: list[float] = []
    mkt_daily: list[float] = []
    blocks: list[dict] = []
    prev_top: set[int] = set()

    # first rebalance at t=form_days (need form_days returns to compute momentum)
    t = form_days
    while t + hold_days < n:
        mom = sector_momentum(R, t, form_days)
        valid = ~np.isnan(mom)
        n_valid = int(valid.sum())
        if n_valid < top_k:
            t += hold_days
            continue
        # rank valid by momentum descending
        order = np.argsort(np.where(valid, mom, -np.inf))[::-1]
        top_idx = [int(i) for i in order[:top_k]]
        top_set = set(top_idx)
        n_new = len(top_set - prev_top)
        turnover = n_new / top_k  # fraction of portfolio rotated

        # hold t+1 .. t+hold_days
        hold = R[t + 1 : t + 1 + hold_days]  # hold_days x n_inds
        sub = hold[:, top_idx]  # hold_days x top_k
        strat = np.nanmean(sub, axis=1)  # equal-weight, nan-safe
        mkt = bench[t + 1 : t + 1 + hold_days]

        for i in range(hold_days):
            strat_daily.append(float(strat[i]) if not np.isnan(strat[i]) else 0.0)
            mkt_daily.append(float(mkt[i]) if not np.isnan(mkt[i]) else 0.0)

        # block compound returns (gross)
        with np.errstate(invalid="ignore"):
            strat_block = float(np.nanprod(1.0 + strat) - 1.0)
            mkt_block = float(np.nanprod(1.0 + mkt) - 1.0)
        # net block: deduct turnover cost at rebalance (one-way turnover * round-trip)
        cost = turnover * ROUND_TRIP_COST
        strat_block_net = strat_block - cost

        blocks.append(
            {
                "rebalance_date": dates[t],
                "top_sectors_idx": top_idx,
                "n_new": n_new,
                "turnover": round(turnover, 4),
                "strat_block_gross": strat_block,
                "strat_block_net": strat_block_net,
                "mkt_block": mkt_block,
            }
        )
        prev_top = top_set
        t += hold_days

    return {
        "strat_daily": np.array(strat_daily),
        "mkt_daily": np.array(mkt_daily),
        "blocks": blocks,
        "n_rebalances": len(blocks),
    }


# ---------- alpha-isolated implementations ----------


def capm_regression(strat_rets: np.ndarray, mkt_rets: np.ndarray, hac: bool = False, maxlag: int = 0) -> dict:
    """OLS  r_strat = alpha + beta * r_mkt + e.
    hac=True => Newey-West SE with `maxlag`; else standard OLS SE (non-overlapping).
    Returns alpha, beta, t(alpha) [two-sided], p_two_sided, p_one_sided_pos, n, r2.
    p_one_sided_pos: P(alpha > 0) — small if alpha significantly positive.
    """
    mask = ~(np.isnan(strat_rets) | np.isnan(mkt_rets))
    y = strat_rets[mask]
    x = mkt_rets[mask]
    n = len(y)
    if n < 5:
        return {
            "alpha": np.nan,
            "beta": np.nan,
            "t_alpha": np.nan,
            "p_two": np.nan,
            "p_one_pos": np.nan,
            "n": n,
            "r2": np.nan,
        }
    X = sm.add_constant(x)  # [1, r_mkt]
    if hac:
        res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlag})
    else:
        res = sm.OLS(y, X).fit()
    alpha = float(res.params[0])
    beta = float(res.params[1])
    t_a = float(res.tvalues[0])
    p_two = float(res.pvalues[0])
    # one-sided positive: if t>0, p_one = p_two/2; if t<0, p_one = 1 - p_two/2 (~1)
    p_one = p_two / 2.0 if t_a > 0 else 1.0 - p_two / 2.0
    return {
        "alpha": alpha,
        "beta": beta,
        "t_alpha": t_a,
        "p_two": p_two,
        "p_one_pos": p_one,
        "n": n,
        "r2": float(res.rsquared),
    }


def annualize_block_alpha(alpha_block: float) -> float:
    """(1+alpha_block)^blocks_per_year - 1."""
    return (1.0 + alpha_block) ** BLOCKS_PER_YEAR - 1.0


def annualize_daily_alpha(alpha_daily: float) -> float:
    return (1.0 + alpha_daily) ** TRADING_DAYS_PER_YEAR - 1.0


def walk_forward_capm(blocks: list[dict], net: bool = False) -> dict:
    """First-half train -> second-half test (by rebalance date). Block-level CAPM.
    Require train_alpha > 0 (analog of train_ev > 0)."""
    if len(blocks) < 8:
        return {"status": "too_few_blocks", "n": len(blocks)}
    mid = len(blocks) // 2
    train = blocks[:mid]
    test = blocks[mid:]
    field = "strat_block_net" if net else "strat_block_gross"
    tr = capm_regression(
        np.array([b[field] for b in train]),
        np.array([b["mkt_block"] for b in train]),
    )
    te = capm_regression(
        np.array([b[field] for b in test]),
        np.array([b["mkt_block"] for b in test]),
    )
    return {
        "status": "ok",
        "n_train": len(train),
        "n_test": len(test),
        "train_alpha": tr["alpha"],
        "train_t": tr["t_alpha"],
        "train_p_one": tr["p_one_pos"],
        "test_alpha": te["alpha"],
        "test_t": te["t_alpha"],
        "test_p_one": te["p_one_pos"],
        "train_beta": tr["beta"],
        "test_beta": te["beta"],
    }


def strategy_sharpe(strat_daily: np.ndarray) -> float:
    """Annualized Sharpe of daily strategy returns (gross, no rf)."""
    if len(strat_daily) < 2:
        return float("nan")
    mu = float(np.mean(strat_daily))
    sd = float(np.std(strat_daily, ddof=1))
    if sd == 0:
        return float("nan")
    return mu / sd * np.sqrt(TRADING_DAYS_PER_YEAR)


# ---------- verdict ----------


def verdict_capm(
    alpha_gross: float,
    alpha_net: float,
    t_block: float,
    p_one_block: float,
    n_blocks: int,
    wf: dict,
    n_bonf: int = N_BONF,
) -> tuple[str, float, str]:
    """Honest verdict cascade. Returns (verdict, p_bonf, reason).

    Distinguishes:
      falsified    = alpha negative, OR positive-in-sample but negative-OOS (overfit),
                     OR gross edge eaten by turnover cost (net < 0, not tradeable)
      exploratory  = alpha POSITIVE in-sample AND OOS-direction-consistent (train>0,
                     test>0) but fails Bonferroni or OOS significance — a positive
                     beta-isolated residual not robust to multiple testing.
                     Per §44 v2: do not label a positive, directionally-consistent
                     signal 'falsified'/'worse than random' — call it exploratory.
      edge-confirmed = passes Bonferroni + OOS significance + cost.
    """
    p_bonf = bonferroni_p(p_one_block, n_bonf)
    wf_ok = wf.get("status") == "ok"
    test_alpha = wf.get("test_alpha", float("nan")) if wf_ok else float("nan")
    train_alpha = wf.get("train_alpha", float("nan")) if wf_ok else float("nan")

    if alpha_gross < 0:
        return "falsified", p_bonf, f"gross alpha={alpha_gross * 100:.3f}%/block < 0 (no positive risk-adjusted edge)"
    if n_blocks < MIN_BLOCKS:
        return "underpowered", p_bonf, f"n_rebalances={n_blocks} < {MIN_BLOCKS}"
    if alpha_net < 0:
        return (
            "falsified",
            p_bonf,
            f"net alpha={alpha_net * 100:.3f}%/block < 0 (gross edge eaten by turnover cost — not tradeable)",
        )
    # Bonferroni fail: split on OOS directional consistency
    if p_bonf >= ALPHA_LEVEL:
        if wf_ok and test_alpha > 0 and train_alpha > 0:
            return (
                "exploratory",
                p_bonf,
                f"alpha POSITIVE in-sample (gross {alpha_gross * 100:.3f}%/blk, net {alpha_net * 100:.3f}%/blk) "
                f"and OOS-direction-consistent (train {train_alpha * 100:.3f}, test {test_alpha * 100:.3f}%/blk both >0), "
                f"but Bonferroni p={p_bonf:.4f} (x{n_bonf}) >= {ALPHA_LEVEL} — positive beta-isolated residual "
                f"NOT robust to multiple-testing; likely partly survivorship-inflated (long-only does not "
                f"cross-sectionally mitigate)",
            )
        return (
            "falsified",
            p_bonf,
            f"Bonferroni p={p_bonf:.4f} (x{n_bonf}) >= {ALPHA_LEVEL} and no OOS support (test_alpha={test_alpha * 100:.3f}%/blk)",
        )
    # Bonferroni passes -> require OOS confirmation
    if not wf_ok:
        return "exploratory", p_bonf, "in-sample Bonferroni PASS but walk-forward unavailable"
    if train_alpha <= 0:
        return (
            "exploratory",
            p_bonf,
            f"Bonferroni PASS but train_alpha={train_alpha * 100:.3f}%/blk <= 0 (edge not in train half -> test may be regime overfit)",
        )
    if test_alpha <= 0:
        return (
            "falsified",
            p_bonf,
            f"walk-forward test_alpha={test_alpha * 100:.3f}%/blk <= 0 (in-sample edge did not survive OOS)",
        )
    wf_p_bonf = bonferroni_p(wf["test_p_one"], n_bonf)
    if wf_p_bonf >= ALPHA_LEVEL:
        return (
            "exploratory",
            p_bonf,
            f"in-sample Bonferroni PASS but OOS test alpha={test_alpha * 100:.3f}%/blk not significant "
            f"(test p Bonf x{n_bonf}={wf_p_bonf:.4f} >= {ALPHA_LEVEL})",
        )
    return (
        "edge-confirmed",
        p_bonf,
        f"gross+net alpha>0, Bonferroni PASS, OOS test alpha={test_alpha * 100:.3f}%/blk significant",
    )


# ---------- main ----------


def main() -> None:
    dates, inds, R, bench = load_clean_window()
    print(f"Clean window: {dates[0]} -> {dates[-1]}  ({len(dates)} trading days, {len(inds)} dense industries)")
    print(
        f"  NOTE: 银行Ⅱ (banks) & 保险Ⅱ (insurance) ABSENT (zero long-history codes) — major financial sectors missing from this rotation."
    )
    print(f"  Bonferroni: x{N_METHODS} (methods) x{N_FORMATION_SEARCH} (formation search) = x{N_BONF}")
    print(f"  Holding: {HOLDING_WEEKS} wk ({HOLD_DAYS} days), rebalance every {HOLD_DAYS} days. Top-{TOP_K} equal-weight long.")

    results: list[dict] = []
    for fw in FORMATION_WEEKS_GRID:
        print(f"\n{'=' * 72}\nFORMATION = {fw} weeks ({fw * TRADING_DAYS_PER_WEEK}-day momentum)\n{'=' * 72}")
        strat = build_rotation(dates, R, bench, formation_weeks=fw)
        blocks = strat["blocks"]
        n_blk = strat["n_rebalances"]
        sd = strat["strat_daily"]
        md = strat["mkt_daily"]

        # ---- block-level CAPM (primary: per-rebalance-block, non-overlapping) ----
        blk_gross = capm_regression(
            np.array([b["strat_block_gross"] for b in blocks]),
            np.array([b["mkt_block"] for b in blocks]),
        )
        blk_net = capm_regression(
            np.array([b["strat_block_net"] for b in blocks]),
            np.array([b["mkt_block"] for b in blocks]),
        )
        # ---- daily HAC cross-check ----
        daily_gross = capm_regression(sd, md, hac=True, maxlag=HAC_MAXLAG)

        # ---- walk-forward OOS (block-level, net) ----
        wf_gross = walk_forward_capm(blocks, net=False)
        wf_net = walk_forward_capm(blocks, net=True)

        # ---- turnover / cost diagnostics ----
        turnovers = [b["turnover"] for b in blocks]
        avg_turn = float(np.mean(turnovers)) if turnovers else 0.0
        avg_cost = avg_turn * ROUND_TRIP_COST
        # annualized cost drag
        annual_cost = (1.0 + avg_cost) ** BLOCKS_PER_YEAR - 1.0

        sharpe = strategy_sharpe(sd)

        alpha_gross_blk = blk_gross["alpha"]
        alpha_net_blk = blk_net["alpha"]
        alpha_gross_ann = annualize_block_alpha(alpha_gross_blk)
        alpha_net_ann = annualize_block_alpha(alpha_net_blk)
        alpha_daily_ann = annualize_daily_alpha(daily_gross["alpha"])

        print(f"\n  n_rebalances (blocks) = {n_blk}  (>= {MIN_BLOCKS}? {'OK' if n_blk >= MIN_BLOCKS else 'UNDERPOWERED'})")
        print(
            f"  avg turnover/block = {avg_turn * 100:.1f}%  "
            f"avg cost/block = {avg_cost * 100:.3f}%  annual cost drag ~= {annual_cost * 100:.2f}%"
        )
        print(f"\n  --- BLOCK-level CAPM (primary, per-rebalance-block) ---")
        print(
            f"  GROSS: alpha={alpha_gross_blk * 100:.4f}%/block  "
            f"(annual {alpha_gross_ann * 100:.2f}%)  beta={blk_gross['beta']:.3f}  "
            f"t={blk_gross['t_alpha']:.3f}  p_one_pos={blk_gross['p_one_pos']:.5f}  "
            f"R2={blk_gross['r2']:.3f}  n={blk_gross['n']}"
        )
        print(
            f"  NET  : alpha={alpha_net_blk * 100:.4f}%/block  "
            f"(annual {alpha_net_ann * 100:.2f}%)  beta={blk_net['beta']:.3f}  "
            f"t={blk_net['t_alpha']:.3f}  p_one_pos={blk_net['p_one_pos']:.5f}"
        )
        print(f"\n  --- DAILY-level CAPM (HAC cross-check, Newey-West maxlag={HAC_MAXLAG}) ---")
        print(
            f"  GROSS: alpha={daily_gross['alpha'] * 100 * TRADING_DAYS_PER_YEAR:.4f}%/yr (daily annualized) "
            f"= {daily_gross['alpha'] * 100:.5f}%/day  beta={daily_gross['beta']:.3f}  "
            f"t={daily_gross['t_alpha']:.3f}  p_one_pos={daily_gross['p_one_pos']:.5f}  "
            f"n={daily_gross['n']}"
        )
        print(f"\n  --- walk-forward OOS (block-level) ---")
        print(
            f"  GROSS: train_alpha={wf_gross.get('train_alpha', float('nan')) * 100:.4f}%/blk "
            f"(t={wf_gross.get('train_t', float('nan')):.3f}) | "
            f"test_alpha={wf_gross.get('test_alpha', float('nan')) * 100:.4f}%/blk "
            f"(t={wf_gross.get('test_t', float('nan')):.3f}, p_one={wf_gross.get('test_p_one', float('nan')):.5f})"
        )
        print(
            f"  NET  : train_alpha={wf_net.get('train_alpha', float('nan')) * 100:.4f}%/blk | "
            f"test_alpha={wf_net.get('test_alpha', float('nan')) * 100:.4f}%/blk "
            f"(p_one={wf_net.get('test_p_one', float('nan')):.5f})"
        )
        print(f"\n  strategy Sharpe (gross, annualized) = {sharpe:.3f}")

        verdict, p_bonf, reason = verdict_capm(
            alpha_gross_blk,
            alpha_net_blk,
            blk_gross["t_alpha"],
            blk_gross["p_one_pos"],
            n_blk,
            wf_net,
            n_bonf=N_BONF,
        )
        print(f"\n  VERDICT: {verdict.upper()}")
        print(f"    Bonferroni p (x{N_BONF}) = {p_bonf:.5f}")
        print(f"    reason: {reason}")

        results.append(
            {
                "formation_weeks": fw,
                "n_rebalances": n_blk,
                "alpha_block_gross": alpha_gross_blk,
                "alpha_block_net": alpha_net_blk,
                "alpha_annual_gross": alpha_gross_ann,
                "alpha_annual_net": alpha_net_ann,
                "alpha_daily_annual": alpha_daily_ann,
                "beta_block": blk_gross["beta"],
                "t_block": blk_gross["t_alpha"],
                "p_one_block": blk_gross["p_one_pos"],
                "p_bonf_block": p_bonf,
                "sharpe": sharpe,
                "avg_turnover": avg_turn,
                "annual_cost_drag": annual_cost,
                "walk_forward": wf_net,
                "verdict": verdict,
                "reason": reason,
            }
        )

    # ---- pick best formation (lowest one-sided p = strongest evidence) ----
    print(f"\n{'#' * 72}\n# FORMATION SEARCH SUMMARY (pick best, Bonferroni-corrected)\n{'#' * 72}")
    best = min(results, key=lambda r: r["p_one_block"])
    for r in results:
        flag = "  <== BEST" if r is best else ""
        print(
            f"  form={r['formation_weeks']}wk: alpha_gross_ann={r['alpha_annual_gross'] * 100:6.2f}%  "
            f"alpha_net_ann={r['alpha_annual_net'] * 100:6.2f}%  t={r['t_block']:6.3f}  "
            f"p_one={r['p_one_block']:.5f}  p_bonf(x{N_BONF})={r['p_bonf_block']:.5f}  "
            f"sharpe={r['sharpe']:.3f}  verdict={r['verdict']}{flag}"
        )

    wf = best["walk_forward"]
    print(f"\nBEST formation = {best['formation_weeks']} weeks:")
    print(f"  block-level GROSS alpha = {best['alpha_block_gross'] * 100:.4f}%/block (annual {best['alpha_annual_gross'] * 100:.2f}%)")
    print(
        f"  block-level NET   alpha = {best['alpha_block_net'] * 100:.4f}%/block "
        f"(annual {best['alpha_annual_net'] * 100:.2f}%)  [after {best['annual_cost_drag'] * 100:.2f}%/yr turnover cost]"
    )
    print(f"  beta = {best['beta_block']:.3f}  (beta isolated: alpha is residual after beta*r_mkt)")
    print(
        f"  t(alpha) = {best['t_block']:.3f}  p_one_sided = {best['p_one_block']:.5f}  Bonferroni(x{N_BONF}) = {best['p_bonf_block']:.5f}"
    )
    print(f"  Sharpe = {best['sharpe']:.3f} (annualized, gross)")
    if wf.get("status") == "ok":
        print(
            f"  walk-forward: train_alpha={wf['train_alpha'] * 100:.4f}%/blk  "
            f"test_alpha={wf['test_alpha'] * 100:.4f}%/blk  test_p_one={wf['test_p_one']:.5f}"
        )
    print(f"  n_rebalances = {best['n_rebalances']}")
    print(f"  VERDICT: {best['verdict'].upper()} — {best['reason']}")

    print(f"\n{'=' * 72}\nHONEST ASSESSMENT")
    print(f"{'=' * 72}")
    print(f"  Alpha-isolation check (CORE): CAPM regression strips beta*r_mkt from")
    print(f"    strategy returns; the intercept (alpha) is the pure timing/skill residual.")
    print(f"    beta={best['beta_block']:.3f} means the strategy carries {best['beta_block']:.3f} of market")
    print(f"    exposure; alpha is what remains AFTER removing that. This is the fix for the")
    print(f"    original flaw (long-only absolute EV conflating alpha+beta).")
    print(f"  Retail feasibility: long-only top-3 sectors — NO shorting/融券 needed.")
    print(f"    Implementable via sector ETFs or constituent stocks. CAPM isolates beta")
    print(f"    analytically (regression), not by shorting the market.")
    print(f"  Data caveat: 25 dense industries exclude banks & insurance (zero long-history")
    print(f"    codes) => financial-sector rotation NOT tested. Survivorship bias inflates")
    print(f"    absolute returns (long-short would mitigate; CAPM alpha is cross-sectionally")
    print(f"    less affected but not immune). Returns are raw (unadjusted) close-to-close.")
    print(f"  NO extrapolation: this measures sector-rotation CAPM alpha for long-only")
    print(f"    top-3 momentum, 2018-2025, 25 industries. It does NOT prove/disprove")
    print(f"    rotation-in-general, short-term edges, or other alpha-isolation methods.")

    # ---- write JSON result ----
    out_path = Path(__file__).resolve().parent / "_rotation_capm_alpha_result.json"
    out = {
        "method": "capm-alpha",
        "clean_window": [dates[0], dates[-1]],
        "n_trading_days": len(dates),
        "n_industries": len(inds),
        "industries_absent": ["银行Ⅱ", "保险Ⅱ"],
        "bonferroni_factor": N_BONF,
        "best_formation_weeks": best["formation_weeks"],
        "best": best,
        "all_formations": results,
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nresult JSON -> {out_path}")


if __name__ == "__main__":
    main()
