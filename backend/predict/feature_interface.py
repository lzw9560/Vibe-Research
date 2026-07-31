"""Feature interface — S018 T12 integration with S017.

Provides the stable entry-point that S017 heads consume.
Actual data-fetching implementations will be plugged in during S008.
"""

from __future__ import annotations

import pandas as pd

from predict.features.alt import ALT_SPECS, register_alt
from predict.features.behavior import BEHAVIOR_SPECS, register_behavior
from predict.features.calendar import CALENDAR_SPECS, register_calendar
from predict.features.external import EXTERNAL_SPECS, register_external
from predict.features.fund_flow import FUND_FLOW_SPECS, register_fund_flow
from predict.features.macro import MACRO_SPECS, register_macro
from predict.features.registry import Registry
from predict.features.sentiment import SENTIMENT_SPECS, register_sentiment
from predict.features.text import TEXT_SPECS, register_text


# ── Module-level constants ────────────────────────────────────────────

# Head name → feature name subset (stable contract for S017).
# Names are taken directly from each module's SPECS tuple.

HEAD_FEATURE_SUBSETS: dict[str, tuple[str, ...]] = {
    "short_sector": (
        # fund_flow (7 features, s1)
        *(s.name for s in FUND_FLOW_SPECS),
        # behavior s1 only (4 features — exclude auction_signal which is s3)
        "short_term_reversal",
        "abnormal_turnover",
        "yesterday_limit_today",
        "day_trip_risk",
        # sentiment (2 features, s1)
        *(s.name for s in SENTIMENT_SPECS),
        # external (4 features, s2)
        *(s.name for s in EXTERNAL_SPECS),
        # calendar (3 features, s2)
        *(s.name for s in CALENDAR_SPECS),
        # text (1 feature, s1)
        *(s.name for s in TEXT_SPECS),
        # macro (2 features, s2) — DXY/美债10Y，Fred key 到位后入短线头 (S019 R5)
        *(s.name for s in MACRO_SPECS),
    ),
    "mid_long": (
        # sentiment (2 features, s1)
        *(s.name for s in SENTIMENT_SPECS),
        # external (4 features, s2)
        *(s.name for s in EXTERNAL_SPECS),
        # text (1 feature, s1)
        *(s.name for s in TEXT_SPECS),
    ),
}

# ── Registry cache ───────────────────────────────────────────────────

_DEFAULT_REGISTRY: Registry | None = None


def build_default_registry() -> Registry:
    """Create and populate the default feature registry.

    Registers all 22 features from the six S018 feature modules.
    The returned Registry is cached at module level so repeated
    calls return the same instance, but tests can build fresh
    instances by calling ``Registry()`` directly.
    """
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is not None:
        return _DEFAULT_REGISTRY

    reg = Registry()
    register_external(reg)
    register_fund_flow(reg)
    register_behavior(reg)
    register_sentiment(reg)
    register_calendar(reg)
    register_text(reg)
    register_macro(reg)
    register_alt(reg)  # S020 worldmonitor alt features — NOT in HEAD_FEATURE_SUBSETS until live smoke (R10)

    _DEFAULT_REGISTRY = reg
    return reg


# ── Public API ──────────────────────────────────────────────────────

def list_available_features(head: str, stage: str) -> list[str]:
    """Return the feature names unlocked for *head* at *stage*.

    Looks up the head's declared feature subset, intersects it with
    the features unlocked at or before *stage* (via
    ``Registry.list_for_stage``), and returns the names in the
    subset's original order.

    Parameters
    ----------
    head:
        Prediction head identifier, e.g. ``"short_sector"``.
    stage:
        Pipeline stage: ``"s1"``, ``"s2"``, ``"s3"``, or ``"s4"``.

    Returns
    -------
    list[str]
        Feature names that are both in the head's subset and
        unlocked at the given stage.

    Raises
    ------
    KeyError
        If *head* is not a known head identifier.
    """
    if head not in HEAD_FEATURE_SUBSETS:
        raise KeyError(f"Unknown head: '{head}'")

    subset = HEAD_FEATURE_SUBSETS[head]
    reg = build_default_registry()
    unlocked_names = {spec.name for spec in reg.list_for_stage(stage)}

    return [name for name in subset if name in unlocked_names]


def get_features(head: str, stage: str, t: str) -> pd.DataFrame:
    """Return the feature matrix for *head* at pipeline *stage* on date *t*.

    Parameters
    ----------
    head:
        Prediction head identifier, e.g. ``"short_sector"``.
    stage:
        Pipeline stage: ``"s1"``, ``"s2"``, ``"s3"``, or ``"s4"``.
    t:
        Trade date in ISO format (``YYYY-MM-DD``).

    Returns
    -------
    pd.DataFrame
        Empty DataFrame with columns = ``list_available_features(head, stage)``.
        Row data will be populated once S008 live data-fetching lands.

    Raises
    ------
    KeyError
        If *head* is not a known head identifier.
    """
    # TODO: S008 接 live 取数填充行
    cols = list_available_features(head, stage)
    return pd.DataFrame(columns=cols)
