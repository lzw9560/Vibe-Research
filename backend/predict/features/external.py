"""External feature specs — S018 T0b slice.

Overnight returns for global indices (SPX / NDX / HSTECH / A50).
All data sourced from gstock.py (East Money push2, em_get throttled).

T0b verified: A50 secid `100.XIN9` is fetchable via push2.
Missing (not registered): US 10Y yield, DXY — push2 candidate secids empty,
availability_offset marked N/A until Fred API wired.
"""

from __future__ import annotations

from predict.features.registry import FeatureSpec, Registry


# ── Module-level immutable spec declarations ────────────────────────

EXTERNAL_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="overnight_spx_ret",
        source="gstock",
        category="external",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="标普500隔夜涨跌幅，T开盘前(S2)可得，走gstock push2",
    ),
    FeatureSpec(
        name="overnight_ndx_ret",
        source="gstock",
        category="external",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="纳斯达克100隔夜涨跌幅，T开盘前(S2)可得，走gstock push2",
    ),
    FeatureSpec(
        name="overnight_hstech_ret",
        source="gstock",
        category="external",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="恒生科技隔夜涨跌幅，T开盘前(S2)可得，走gstock push2",
    ),
    FeatureSpec(
        name="overnight_a50_ret",
        source="gstock",
        category="external",
        availability_offset=1,
        stage="s2",
        compliance_flag="ok",
        description="富时A50夜盘涨跌幅，T开盘前(S2)可得，走gstock push2 (secid 100.XIN9)",
    ),
)

# key → feature_name 映射（immutable, no network access）
_KEY_TO_FEATURE = {
    "spx": "overnight_spx_ret",
    "ndx": "overnight_ndx_ret",
    "hstech": "overnight_hstech_ret",
    "a50": "overnight_a50_ret",
}


# ── Registration ────────────────────────────────────────────────────

def register_external(registry: Registry) -> None:
    """Register all external FeatureSpecs into the given Registry.

    Raises:
        KeyError: If any feature name is already registered.
    """
    for spec in EXTERNAL_SPECS:
        registry.register(spec)


# ── Pure computation (no side effects, no network) ──────────────────

def compute_overnight_returns(indices: list[dict]) -> dict[str, float | None]:
    """Map a list of index dicts (as returned by global_indices()) to
    overnight-return feature values.

    Parameters
    ----------
    indices:
        Each dict must contain at least ``key`` (str) and ``change_pct``
        (float | None).  Typical source: ``gstock.global_indices()``.

    Returns
    -------
    dict[str, float | None]
        Keys: ``overnight_spx_ret``, ``overnight_ndx_ret``,
        ``overnight_hstech_ret``, ``overnight_a50_ret``.
        Missing keys or ``None`` change_pct → ``None``.
    """
    # Build a lookup from index key → change_pct
    lookup: dict[str, float | None] = {}
    for idx in indices:
        key = idx.get("key")
        if isinstance(key, str):
            lookup[key] = idx.get("change_pct")

    # Return all four features, defaulting to None when missing
    return {
        feature_name: lookup.get(key)
        for key, feature_name in _KEY_TO_FEATURE.items()
    }
