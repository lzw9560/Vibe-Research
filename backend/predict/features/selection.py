"""Feature selection harness — S018 R8.

Pure data-science logic: accepts feature matrices + names, returns
stable feature subsets via permutation-importance bootstrapping.
No dependency on ``feature_interface``.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
from sklearn.inspection import permutation_importance


MAX_SHORT_FEATURES = 25


@dataclass(frozen=True)
class SelectionResult:
    """Immutable result of a feature-selection run."""

    kept: tuple[str, ...]
    dropped: tuple[str, ...]
    importance: dict[str, float]
    method: str
    rationale: str


def _pick_model(y):
    """Return a default model (classifier or regressor) based on *y*.

    Defaults to sklearn RandomForest for cross-platform stability.
    LightGBM can be passed explicitly via the *model* argument.
    """
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

    is_classification = len(np.unique(y)) <= 10
    if is_classification:
        return RandomForestClassifier(n_estimators=20, random_state=42, n_jobs=1)
    return RandomForestRegressor(n_estimators=20, random_state=42, n_jobs=1)


def rank_by_permutation(
    X,
    y,
    feature_names: list[str],
    model=None,
) -> dict[str, float]:
    """Compute permutation importance for each feature.

    Parameters
    ----------
    X : array-like of shape (n_samples, n_features)
        Feature matrix (DataFrame or ndarray).
    y : array-like of shape (n_samples,)
        Target vector.
    feature_names : list[str]
        Ordered list of feature names matching *X* columns.
    model : estimator, optional
        Pre-trained or default model. If None, a sklearn RandomForest model
        is chosen automatically based on *y*.

    Returns
    -------
    dict[str, float]
        Mapping feature name → mean permutation-importance score.
    """
    if model is None:
        model = _pick_model(y)
        model.fit(X, y)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = permutation_importance(model, X, y, n_repeats=3, random_state=42, n_jobs=1)

    return {name: float(result.importances_mean[i]) for i, name in enumerate(feature_names)}


def _bootstrap_importance(
    X,
    y,
    feature_names: list[str],
    n_bootstrap: int,
    random_state: int,
) -> dict[str, list[float]]:
    """Return raw importance scores per feature across bootstrap samples."""
    rng = np.random.default_rng(random_state)
    n_samples = len(y)
    scores: dict[str, list[float]] = {name: [] for name in feature_names}

    for seed in range(random_state, random_state + n_bootstrap):
        indices = rng.integers(0, n_samples, size=n_samples)
        X_boot = X[indices] if hasattr(X, "__array__") else X.iloc[indices].values
        y_boot = y[indices]

        imp = rank_by_permutation(X_boot, y_boot, feature_names)
        for name, val in imp.items():
            scores[name].append(val)

    return scores


def select_stable_features(
    X,
    y,
    feature_names: list[str],
    max_features: int = MAX_SHORT_FEATURES,
    n_bootstrap: int = 5,
    random_state: int = 42,
) -> SelectionResult:
    """Select stable features via bootstrap permutation importance.

    For each bootstrap sample permutation importance is computed.
    Features are ranked by their mean importance across samples.
    The top ``max_features`` are kept; the rest are dropped.
    """
    scores = _bootstrap_importance(X, y, feature_names, n_bootstrap, random_state)

    mean_importance = {name: float(np.mean(vals)) for name, vals in scores.items()}
    sorted_names = sorted(
        mean_importance, key=mean_importance.get, reverse=True  # type: ignore[arg-type]
    )

    kept = tuple(sorted_names[:max_features])
    dropped = tuple(sorted_names[max_features:])

    rationale = (
        f"按 permutation importance bootstrap 均值降序取 top{max_features}，"
        f"n_bootstrap={n_bootstrap}, random_state={random_state}"
    )

    return SelectionResult(
        kept=kept,
        dropped=dropped,
        importance=mean_importance,
        method="permutation_bootstrap",
        rationale=rationale,
    )


def try_shap_importance(
    X,
    y,
    feature_names: list[str],
    model,
) -> dict[str, float] | None:
    """Try to compute mean absolute SHAP values; return None if shap unavailable.

    Best-effort enhancement over permutation importance: returns None on any
    shap failure (missing, unexpected output shape, model incompatibility) so
    callers fall back to ``rank_by_permutation`` without raising.
    """
    try:
        import shap  # type: ignore[import-untyped]
    except ImportError:
        return None

    try:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X)
    except Exception:
        # shap varies across model types/versions; treat as unavailable.
        return None

    # shap output shapes vary by version/model:
    #   - list[class0_arr, class1_arr]  (older shap, binary clf)
    #   - ndarray (n_samples, n_features)         (regressor / single-output)
    #   - ndarray (n_samples, n_features, n_cls)  (shap >=0.42 binary clf)
    if isinstance(shap_values, list):
        shap_values = shap_values[1] if len(shap_values) > 1 else shap_values[0]
    if isinstance(shap_values, np.ndarray) and shap_values.ndim == 3:
        # binary/multi-class: take the positive (last) class slice
        shap_values = shap_values[:, :, -1]

    mean_abs = np.abs(shap_values).mean(axis=0)
    return {name: float(mean_abs[i]) for i, name in enumerate(feature_names)}
