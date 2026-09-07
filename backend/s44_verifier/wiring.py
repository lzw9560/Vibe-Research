"""S161 wiring: adapter to vendor/skill-backtest-overfit scripts.

WHY the sys.path insert: the vendor dir is named ``skill-backtest-overfit`` —
the hyphen makes it a non-identifier, so it cannot be imported as a Python
module path. We instead insert scripts/ onto sys.path and import the script
modules directly (deflated_sharpe / pbo_cscv / purged_kfold / haircut are
valid module names). This also isolates any future vendor version drift from
verifier.py.
"""
from __future__ import annotations

import math
import pathlib
import sys

import numpy as np

_SCRIPTS_DIR = (
    pathlib.Path(__file__).resolve().parents[2]
    / "vendor" / "skill-backtest-overfit" / "scripts"
)
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from deflated_sharpe import (  # noqa: E402
    deflated_sharpe_ratio,
    minimum_track_record_length,
    sharpe_ratio,
)
from pbo_cscv import probability_of_backtest_overfitting  # noqa: E402
from purged_kfold import PurgedKFold  # noqa: E402
from haircut import haircut_sharpe  # noqa: E402


def _safe_min_trl(res) -> float | None:
    """MinTRL from a DSRResult. None when inapplicable.

    Spec R2 lists ``deflated_sharpe.py (DSR/PSR/MinTRL)`` — MinTRL answers
    "how many more observations for this Sharpe to be significant?" and
    informs the underpowered path (R6: days<60 → underpowered). Returns None
    when observed_sr <= benchmark (vendor returns inf) or numerically broken.
    """
    try:
        m = minimum_track_record_length(
            res.observed_sharpe,
            res.deflated_benchmark_sr0,
            res.skew,
            res.kurtosis,
        )
        if math.isnan(m) or math.isinf(m):
            return None
        return float(m)
    except (ValueError, ZeroDivisionError):
        return None


def compute_dsr(
    returns: np.ndarray,
    n_trials: int,
    trial_cols: list[np.ndarray] | None = None,
) -> tuple[float | None, str, float | None]:
    """Deflated Sharpe Ratio + MinTRL with an honest method flag.

    Returns ``(dsr, dsr_method, min_trl)``:
    - ``dsr_method``:
      - ``"cross_trial_variance"``: trial_cols supplied (>=2) -> real cross-trial
        variance (the honest path, Bailey & Lopez de Prado 2014).
      - ``"lenient_single_estimate"``: no trial_cols -> deflated_sharpe.py falls
        back to the asymptotic Var(SR) lower bound (lines 160-168), which makes
        DSR lenient. We flag this so the verdict never presents a lenient number
        as authoritative (spec-grill S161 methodology hole #3).
    - ``min_trl``: Minimum Track Record Length (spec R2 lists MinTRL). None
      when inapplicable (n<2, observed<=benchmark → inf, or numerically broken).
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2 or n_trials < 1:
        return None, "N/A", None

    if trial_cols and len(trial_cols) >= 2:
        sharpes = [float(sharpe_ratio(c)) for c in trial_cols]
        sharpes = [s for s in sharpes if not math.isnan(s)]
        if len(sharpes) >= 2:
            res = deflated_sharpe_ratio(r, n_trials=n_trials, all_trial_sharpes=sharpes)
            return (
                float(res.deflated_sharpe_ratio),
                "cross_trial_variance",
                _safe_min_trl(res),
            )

    res = deflated_sharpe_ratio(r, n_trials=n_trials)
    return (
        float(res.deflated_sharpe_ratio),
        "lenient_single_estimate",
        _safe_min_trl(res),
    )


def compute_pbo(trial_cols: list[np.ndarray] | None) -> float | None:
    """PBO via CSCV. None when inapplicable.

    pbo_cscv.py:88 raises ValueError on N<2; we catch -> None. PBO applies to
    multi-configuration factor mining (N>=10 meaningful), not single-edge tests
    like the gap run (spec-grill S161 methodology hole #1).
    """
    if not trial_cols or len(trial_cols) < 2:
        return None
    try:
        matrix = np.column_stack(trial_cols)
        res = probability_of_backtest_overfitting(matrix, n_blocks=16)
        return float(res.pbo)
    except ValueError:
        return None


def compute_purged_kfold_splits(
    label_times: "pd.Series | None",
    n_splits: int = 5,
    embargo_pct: float = 0.01,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """PurgedKFold splitter yielding (train_idx, test_idx) with purge + embargo.

    S161 R2 acceptance: this calls ``PurgedKFold.split()`` — the splitter that
    yields train/test index pairs with label-overlap PURGE and post-test
    EMBARGO (López de Prado, AFML ch.7). NOT ``cross_val_score_purged`` (which
    needs an sklearn estimator's fit/score — §44 has no ML model, so that
    convenience wrapper is unusable here; spec-grill S161 v2 hole #2).

    Complementary to ``stats.walk_forward_oos``: walk-forward is rolling
    train/test on contiguous days; PurgedKFold is K-fold with label-overlap
    purge. For daily-return labels (label determined same-day) purge/embargo
    have little effect, but the splitter is wired so holding-period labels
    (span N days) get proper de-overlap when that data arrives.

    Returns ``[]`` when inapplicable (label_times None, <2 samples, or
    non-monotonic index). Caller handles empty as graceful degradation.
    """
    if label_times is None:
        return []
    n = len(label_times)
    if n < 2:
        return []
    try:
        cv = PurgedKFold(
            n_splits=min(n_splits, n), label_times=label_times, embargo_pct=embargo_pct,
        )
        return [(np.asarray(tr), np.asarray(te)) for tr, te in cv.split()]
    except (ValueError, IndexError):
        # ValueError: non-monotonic label_times index.
        # IndexError: n_splits > n_samples produces empty folds (np.array_split
        #   on an empty array). min(n_splits, n) above prevents this in practice,
        #   but we catch defensively in case the cap is ever removed.
        return []


def compute_haircut(
    returns: np.ndarray,
    n_obs: int,
    n_tests: int,
    method: str = "bonferroni",
) -> float | None:
    """Multiple-testing haircut of the Sharpe Ratio (Harvey & Liu 2015).

    Returns the fraction of the Sharpe removed (0.0 = no haircut, ~1.0 =
    fully deflated). None when inapplicable: <2 returns, <1 test, zero/nan
    std, or zero Sharpe (haircut undefined; vendor returns nan).

    Uses per-period Sharpe (mean/std, daily) since ``haircut_sharpe`` expects
    per-period input (vendor __main__: ``sr_pp = annual / sqrt(252)``). The
    ``method`` should mirror spec R6 by-n: ``"BH"`` for small-n (days<60),
    ``"bonferroni"`` for mature results (days>=60). K=1 (single edge) → no
    multiplicity → haircut rounds to 0.0.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2 or n_tests < 1 or n_obs < 2:
        return None
    std = float(r.std(ddof=1))
    if std == 0 or math.isnan(std):
        return None
    sr_pp = float(r.mean() / std)
    if sr_pp == 0 or math.isnan(sr_pp):
        return None
    try:
        res = haircut_sharpe(
            sr_pp, n_obs=int(n_obs), n_tests=int(n_tests), method=method,
        )
        h = float(res.haircut)
        if math.isnan(h):
            return None
        # K=1 → no multiplicity → haircut ~0 (round tiny FP residual from
        # norm.isf(norm.sf(x)/2) inversion that produces ~1e-16 residual).
        if abs(h) < 1e-10:
            return 0.0
        return h
    except (ValueError, ZeroDivisionError):
        return None
