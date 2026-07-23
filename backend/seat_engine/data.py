# -*- coding: utf-8 -*-
"""seat_engine 数据层 —— 持久化。"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from seat_engine.models import SeatProfile

_PROFILES_PATH = Path(__file__).parent.parent / "seat_profiles.json"
_LOCK = threading.Lock()


def load_profiles_from_disk() -> dict:
    """Load persisted seat profiles from JSON file."""
    if _PROFILES_PATH.exists():
        try:
            with open(_PROFILES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_profiles_to_disk(profiles: dict) -> None:
    """Persist seat profiles to JSON file."""
    try:
        with open(_PROFILES_PATH, "w", encoding="utf-8") as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
    except IOError:
        pass
