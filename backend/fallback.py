# -*- coding: utf-8 -*-
"""多源降级 —— 东财故障时本地缓存兜底。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# 缓存目录
_CACHE_DIR = Path(__file__).parent / "data" / "fallback"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 内存缓存：key → (timestamp, data)
_MEM_CACHE: dict[str, tuple[float, Any]] = {}
_MEM_TTL = 3600  # 1 小时


def _cache_path(key: str) -> Path:
    """缓存文件路径。"""
    safe_key = key.replace("/", "_").replace(":", "_")
    return _CACHE_DIR / f"{safe_key}.json"


def save_cache(key: str, data: Any, ttl: int = _MEM_TTL) -> None:
    """保存到本地缓存（内存 + 文件）。"""
    now = time.time()
    _MEM_CACHE[key] = (now, data)
    try:
        path = _cache_path(key)
        path.write_text(json.dumps({"ts": now, "data": data}, ensure_ascii=False))
    except Exception:
        pass  # 缓存写入失败不影响主流程


def load_cache(key: str, ttl: int = _MEM_TTL) -> Any | None:
    """从本地缓存加载（优先内存，其次文件）。"""
    now = time.time()
    # 内存缓存
    hit = _MEM_CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    # 文件缓存
    try:
        path = _cache_path(key)
        if not path.exists():
            return None
        raw = json.loads(path.read_text())
        ts = raw.get("ts", 0)
        if now - ts > ttl:
            return None
        data = raw.get("data")
        _MEM_CACHE[key] = (ts, data)
        return data
    except Exception:
        return None


def get_with_fallback(
    key: str,
    fetch_fn,
    ttl: int = _MEM_TTL,
    fallback_value: Any = None,
) -> Any:
    """带降级的数据获取：优先实时获取，失败则返回缓存。

    Args:
        key: 缓存键
        fetch_fn: 实时数据获取函数（可能抛出异常）
        ttl: 缓存有效期（秒）
        fallback_value: 缓存也失效时的兜底值
    """
    # 1. 尝试实时获取
    try:
        data = fetch_fn()
        if data is not None:
            save_cache(key, data, ttl)
            return data
    except Exception:
        pass  # 实时获取失败，降级到缓存

    # 2. 降级到缓存
    cached = load_cache(key, ttl)
    if cached is not None:
        return cached

    # 3. 返回兜底值
    return fallback_value
