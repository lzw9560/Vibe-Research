"""Sentiment feature specs — S018 sentiment group.

Limit-up emotion aggregation (no individual stock names) and
sector divergence score.

All data sourced from market._emotion() and market._sectors().
Pure computation functions have no side effects and no network access.
"""

from __future__ import annotations

from predict.features.registry import FeatureSpec, Registry


# ── Module-level immutable spec declarations ────────────────────────

SENTIMENT_SPECS: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        name="limitup_emotion",
        source="limitup_sti",
        category="sentiment",
        availability_offset=0,
        stage="s1",
        compliance_flag="aggregate_only",
        description="涨停四池聚合情绪（连板梯队/封板率/炸板率/晋级率/涨跌停家数），零个股名泄露",
    ),
    FeatureSpec(
        name="sector_divergence",
        source="astock.em_get",
        category="sentiment",
        availability_offset=0,
        stage="s1",
        compliance_flag="ok",
        description="板块分歧度（板块涨跌幅离散度，用极差）",
    ),
)


# ── Registration ────────────────────────────────────────────────────

def register_sentiment(registry: Registry) -> None:
    """Register all sentiment FeatureSpecs into the given Registry.

    Raises:
        KeyError: If any feature name is already registered.
    """
    for spec in SENTIMENT_SPECS:
        registry.register(spec)


# ── Pure computation (no side effects, no network) ──────────────────

# Mapping from raw _emotion() keys to flat feature keys.
_EMOTION_KEY_MAP = {
    "max_boards": "max_boards",
    "zt_count": "limit_up_count",
    "dt_count": "limit_down_count",
    "seal_rate": "seal_rate",
    "break_rate": "broken_rate",
    "promotion_rate": "advance_rate",
}


def aggregate_emotion(emotion: dict | None) -> dict:
    """Extract flat numeric aggregate fields from a market._emotion() dict.

    Parameters
    ----------
    emotion:
        Dict as returned by ``market._emotion()`` (or None).
        Expected keys: max_boards, zt_count, dt_count, seal_rate,
        break_rate, promotion_rate, plus optional nested fields like
        ladder, lianban_stocks, etc.

    Returns
    -------
    dict
        Flat dict with only the whitelisted numeric aggregate keys.
        All nested / individual-stock fields are stripped.
        Returns ``{}`` when *emotion* is None.
    """
    if emotion is None:
        return {}

    result: dict[str, object] = {}
    for raw_key, feature_key in _EMOTION_KEY_MAP.items():
        if raw_key in emotion:
            result[feature_key] = emotion[raw_key]
    return result


def sector_divergence_score(sectors: list[dict] | None) -> float | None:
    """Calculate sector divergence as the range of pct values.

    Parameters
    ----------
    sectors:
        List of sector dicts (shape from market._sectors):
        each dict must contain ``pct`` (float | None).

    Returns
    -------
    float | None
        max(pct) - min(pct) among valid pct values.
        Returns None when input is None, empty, or has fewer than
        2 valid pct values.
    """
    if sectors is None:
        return None

    valid: list[float] = []
    for s in sectors:
        pct = s.get("pct")
        if isinstance(pct, (int, float)):
            valid.append(float(pct))

    if len(valid) < 2:
        return None

    return max(valid) - min(valid)
