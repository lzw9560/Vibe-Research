"""
Shared state and utilities for routers.
Extracted from backend/app.py to avoid circular imports.
"""

import os
import re
import json
import time
import threading
import sqlite3
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

from fastapi import HTTPException

# ============ Database ===========
_DB_PATH: str = os.path.join(os.path.dirname(__file__), "..", "data", "market_data.db")
_DB_LOCK: threading.Lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    """Get database connection (thread-safe)."""
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ============ Caching ===========
_DC_CACHE: Dict[str, Tuple[Any, float]] = {}
_PCT_CACHE: Dict[str, Tuple[Any, float]] = {}
_ANN_CACHE: Dict[str, Tuple[Any, float]] = {}
_FIN_CACHE: Dict[str, Tuple[Any, float]] = {}


def _cached(cache: Dict[str, Tuple[Any, float]], key: str, ttl: int = 300) -> Callable:
    """Simple cache decorator with TTL."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            now = time.time()
            if key in cache:
                data, ts = cache[key]
                if now - ts < ttl:
                    return data
            result = func(*args, **kwargs)
            cache[key] = (result, now)
            return result
        return wrapper
    return decorator


def _cached_async(cache: Dict[str, Tuple[Any, float]], key: str, ttl: int = 300) -> Callable:
    """Simple async cache decorator with TTL."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            now = time.time()
            if key in cache:
                data, ts = cache[key]
                if now - ts < ttl:
                    return data
            result = await func(*args, **kwargs)
            cache[key] = (result, now)
            return result
        return wrapper
    return decorator


# ============ Validation ===========
_CODE_RE: re.Pattern = re.compile(r"^\d{6}$")


def _validate(code: str) -> str:
    """Validate stock code format."""
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return code


# ============ LimitUp Params ===========
_LIMITUP_PARAMS_FILE: str = os.path.join(os.path.dirname(__file__), "..", "data", "limitup_params.json")


def _load_limitup_params() -> Dict[str, Any]:
    """Load limitup screener parameters from file."""
    if os.path.exists(_LIMITUP_PARAMS_FILE):
        with open(_LIMITUP_PARAMS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_limitup_params(params: Dict[str, Any]) -> None:
    """Save limitup screener parameters to file."""
    os.makedirs(os.path.dirname(_LIMITUP_PARAMS_FILE), exist_ok=True)
    with open(_LIMITUP_PARAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)


def load_json_params(file_path: str, defaults: Dict[str, Any]) -> Dict[str, Any]:
    """Generic JSON params loader with env fallback."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defaults


def save_json_params(file_path: str, params: Dict[str, Any]) -> None:
    """Generic JSON params saver."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=2)


__all__ = [
    "_validate",
    "_cached",
    "_load_limitup_params",
    "_save_limitup_params",
    "load_json_params",
    "save_json_params",
]
