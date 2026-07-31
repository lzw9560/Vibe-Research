"""Feature registry — S018 T0 slice.

Declarative registry for multi-source features with look-ahead guard.
Each feature declares its unlock stage (s1..s4) and availability_offset;
list_for_stage() filters out features that would introduce look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


# Stage ordering for look-ahead guard.
# s1 = T-1 close, s2 = pre-open, s3 = auction, s4 = intraday
_STAGE_ORDER = {"s1": 1, "s2": 2, "s3": 3, "s4": 4}
_VALID_COMPLIANCE_FLAGS = {"ok", "aggregate_only"}


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Immutable specification for a single feature.

    Fields match the S018 spec / plan schema:
    - name: unique feature identifier
    - source: data origin (e.g. "gstock", "astock.em_get", "limitup_sti")
    - category: logical group (external, fund_flow, behaviour, etc.)
    - availability_offset: t+k when data becomes available
      (0 = same-day close, 1 = next-day pre-open, etc.)
    - stage: s1/s2/s3/s4 — which pipeline stage unlocks this feature
    - compliance_flag: "ok" or "aggregate_only" (aggregate_only = no
      individual stock names leaked, per CLAUDE.md §1)
    - description: human-readable explanation
    """

    name: str
    source: str
    category: str
    availability_offset: int
    stage: str
    compliance_flag: str
    description: str

    def __post_init__(self) -> None:
        if self.availability_offset < 0:
            raise ValueError(
                f"availability_offset must be >= 0, got {self.availability_offset}"
            )
        if self.stage not in _STAGE_ORDER:
            raise ValueError(
                f"stage must be one of {_STAGE_ORDER.keys()}, got '{self.stage}'"
            )
        if self.compliance_flag not in _VALID_COMPLIANCE_FLAGS:
            raise ValueError(
                f"compliance_flag must be one of {_VALID_COMPLIANCE_FLAGS}, "
                f"got '{self.compliance_flag}'"
            )


class Registry:
    """In-memory feature registry with look-ahead filtering.

    Typical usage:
        reg = Registry()
        reg.register(FeatureSpec(...))
        features = reg.list_for_stage("s2")
    """

    def __init__(self) -> None:
        self._store: Dict[str, FeatureSpec] = {}

    def register(self, spec: FeatureSpec) -> None:
        """Register a feature spec.  Raises on duplicate name."""
        if spec.name in self._store:
            raise KeyError(f"Feature '{spec.name}' already registered")
        self._store[spec.name] = spec

    def get_by_name(self, name: str) -> FeatureSpec | None:
        """Retrieve a single feature by its unique name."""
        return self._store.get(name)

    def list_for_stage(self, stage: str) -> List[FeatureSpec]:
        """Return all features unlocked at or before *stage*.

        This is the core look-ahead guard: a feature whose declared
        ``stage`` is later than the current pipeline stage is omitted,
        because its data would not yet be available and using it would
        leak future information.
        """
        if stage not in _STAGE_ORDER:
            raise ValueError(
                f"stage must be one of {_STAGE_ORDER.keys()}, got '{stage}'"
            )
        current = _STAGE_ORDER[stage]
        return [
            spec
            for spec in self._store.values()
            if _STAGE_ORDER[spec.stage] <= current
        ]

    def list_for_head(self, head: str) -> List[FeatureSpec]:
        """STUB — return all registered features regardless of stage.

        In S018 T12 (integration with S017) this will be replaced by
        per-head feature-subset filtering.  For now it acts as a
        pass-through so that downstream callers have a stable API.
        """
        return list(self._store.values())
