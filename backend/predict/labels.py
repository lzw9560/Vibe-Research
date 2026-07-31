"""Label construction — S017 T1.

Provides frozen dataclass for label configuration and pure functions to build
binary labels from a price series.  All functions are deterministic and have no
side effects (no network, no I/O).

Label definition (to avoid lookahead):
    Given a historical price series ``prices`` (ascending by date), the label at
the last known point is computed from the *past* ``horizon`` days of returns:

    label = 1 if (prices[-1] - prices[-1-horizon]) / prices[-1-horizon] > 0 else 0

This is a proxy for ``future_return > 0`` that can be computed without any
future information, making it safe for training.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Module constants ────────────────────────────────────────────────────

SHORT_HORIZON_DAYS = 3
MID_HORIZON_DAYS = 20

_VALID_HORIZONS = {"short", "mid"}
_VALID_DIRECTIONS = {"up", "down"}

# ── LabelConfig ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LabelConfig:
    """Immutable specification for label construction.

    Parameters
    ----------
    target:
        Identifier for what is being labelled.  ``"sector_idx"`` for a
        sector index, or a stock code (e.g. ``"600001.SH"``) for an individual
        stock.
    horizon:
        ``"short"`` (1-3 days, default 3) or ``"mid"`` (5-20 days, default 20).
    direction:
        ``"up"`` (default) means label=1 when cumulative return over the
        horizon is **strictly** positive.  ``"down"`` means label=1 when the
        cumulative return is **strictly** negative.
    """

    target: str
    horizon: str
    direction: str = "up"

    def __post_init__(self) -> None:
        if self.horizon not in _VALID_HORIZONS:
            raise ValueError(
                f"horizon must be one of {_VALID_HORIZONS}, got '{self.horizon}'"
            )
        if self.direction not in _VALID_DIRECTIONS:
            raise ValueError(
                f"direction must be one of {_VALID_DIRECTIONS}, "
                f"got '{self.direction}'"
            )


# ── Pure functions ─────────────────────────────────────────────────────

def _horizon_days(config: LabelConfig) -> int:
    """Return the number of calendar days for *config*'s horizon."""
    return SHORT_HORIZON_DAYS if config.horizon == "short" else MID_HORIZON_DAYS


def build_label(prices: list[float], config: LabelConfig) -> int | None:
    """Build a single binary label from *prices* according to *config*.

    The label is computed from the **past** ``horizon`` days of cumulative
    return (no future information):

        return_t = (prices[-1] - prices[-1-horizon]) / prices[-1-horizon]

    Parameters
    ----------
    prices:
        Ascending closing-price sequence (adjusted close or index close).
    config:
        Label configuration (target, horizon, direction).

    Returns
    -------
    int | None
        * ``1`` if the directional condition is met.
        * ``0`` if the directional condition is **not** met (including the
          boundary case where the return is exactly zero).
        * ``None`` if *prices* has fewer than ``horizon + 1`` elements.
    """
    h = _horizon_days(config)
    if len(prices) < h + 1:
        return None

    past_return = (prices[-1] - prices[-1 - h]) / prices[-1 - h]
    is_positive = past_return > 0

    if config.direction == "up":
        return 1 if is_positive else 0
    # config.direction == "down"
    return 1 if not is_positive else 0


def build_labels_series(prices: list[float], config: LabelConfig) -> list[int | None]:
    """Build a label for every feasible time-step in *prices*.

    Produces a list of the same length as *prices*.  The first ``horizon``
    entries are ``None`` (insufficient history), and each subsequent entry is
    the label computed from the subsequence ``prices[:t+1]``.

    Parameters
    ----------
    prices:
        Ascending closing-price sequence.
    config:
        Label configuration.

    Returns
    -------
    list[int | None]
        Labels aligned with *prices*.  Same length as *prices*.
    """
    h = _horizon_days(config)
    if not prices:
        return []

    labels: list[int | None] = []
    for t in range(len(prices)):
        if t < h:
            labels.append(None)
            continue
        sub = prices[: t + 1]
        past_return = (sub[-1] - sub[-1 - h]) / sub[-1 - h]
        is_positive = past_return > 0
        if config.direction == "up":
            labels.append(1 if is_positive else 0)
        else:
            labels.append(1 if not is_positive else 0)
    return labels
