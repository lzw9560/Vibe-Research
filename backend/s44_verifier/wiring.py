"""S161 wiring: adapter to vendor/skill-backtest-overfit scripts.

WHY the sys.path insert: the vendor dir is named ``skill-backtest-overfit`` —
the hyphen makes it a non-identifier, so it cannot be imported as a Python
module path. We instead insert scripts/ onto sys.path and import the script
modules directly (deflated_sharpe / pbo_cscv are valid module names). This also
isolates any future vendor version drift from verifier.py.
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

from deflated_sharpe import deflated_sharpe_ratio, sharpe_ratio  # noqa: E402
from pbo_cscv import probability_of_backtest_overfitting  # noqa: E402


def compute_dsr(
    returns: np.ndarray,
    n_trials: int,
    trial_cols: list[np.ndarray] | None = None,
) -> tuple[float | None, str]:
    """Deflated Sharpe Ratio with an honest method flag.

    Returns ``(dsr, dsr_method)``:
    - ``"cross_trial_variance"``: trial_cols supplied (>=2) -> real cross-trial
      variance (the honest path, Bailey & Lopez de Prado 2014).
    - ``"lenient_single_estimate"``: no trial_cols -> deflated_sharpe.py falls
      back to the asymptotic Var(SR) lower bound (lines 160-168), which makes DSR
      lenient. We flag this so the verdict never presents a lenient number as
      authoritative (spec-grill S161 methodology hole #3).
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2 or n_trials < 1:
        return None, "N/A"

    if trial_cols and len(trial_cols) >= 2:
        sharpes = [float(sharpe_ratio(c)) for c in trial_cols]
        sharpes = [s for s in sharpes if not math.isnan(s)]
        if len(sharpes) >= 2:
            res = deflated_sharpe_ratio(r, n_trials=n_trials, all_trial_sharpes=sharpes)
            return float(res.deflated_sharpe_ratio), "cross_trial_variance"

    res = deflated_sharpe_ratio(r, n_trials=n_trials)
    return float(res.deflated_sharpe_ratio), "lenient_single_estimate"


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
