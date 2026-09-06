"""S161 §44v2 verifier package — design-agnostic statistical judge."""
from __future__ import annotations

from . import stats  # noqa: F401  (R3 merged methodology, re-exported)
from .verifier import EventMetrics, Verdict, verify
from .recorder import Recorder, VerifierRecord, compute_composite_snapshot_id, sha256_file

__all__ = [
    "stats",
    "EventMetrics",
    "Verdict",
    "verify",
    "Recorder",
    "VerifierRecord",
    "compute_composite_snapshot_id",
    "sha256_file",
]
