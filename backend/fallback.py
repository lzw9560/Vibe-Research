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


def _is_empty_leaf(value: Any) -> bool:
    """深空叶子判定：None / 空容器 / 纯 0 数值皆空。递归处理嵌套 dict/list。"""
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, (str, bytes)):
        return len(value) == 0  # 显式先行，避免落入通用 __len__ 递归（str 迭代=字符串无限递归）
    if isinstance(value, dict):
        return all(_is_empty_leaf(v) for v in value.values())  # all([])=True：空 dict 为空
    if hasattr(value, "__len__"):
        if len(value) == 0:
            return True
        return all(_is_empty_leaf(v) for v in value)
    return False


def _is_empty(data: Any) -> bool:
    """空数据判定（深递归）——东财限流/失败的典型表现是返空或"空骨架"。

    None / 空容器为空；**dict 深判：所有值皆深空（含纯 0 叶子）视为空骨架**——
    如龙虎榜限流返 {"records": [], "seats": {"buy": [], ...}, "institution": {0.0...}}，
    顶层非空但无任何信息，写盘会覆盖好缓存（2026-08-10 二次污染根因）。
    顶层标量 0/False 不算空（合法值，如单值缓存）。
    """
    if data is None:
        return True
    if isinstance(data, dict):
        return _is_empty_leaf(data)
    if hasattr(data, "__len__") and len(data) == 0:
        return True
    return False


def save_cache(key: str, data: Any, ttl: int = _MEM_TTL) -> None:
    """保存到本地缓存（内存 + 文件）。

    S046：空数据不写——避免东财限流返空时把空 data 覆盖既有好缓存（污染快照）。
    """
    if _is_empty(data):
        return
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
        if _is_empty(data):
            # 损坏快照（历史空写遗留）——自愈：删除文件、清内存，视为未命中，
            # 下次实时取数正常时由 save_cache 重建。
            try:
                path.unlink()
            except Exception:
                pass
            _MEM_CACHE.pop(key, None)
            return None
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
        if not _is_empty(data):
            save_cache(key, data, ttl)
            return data
        # 空数据（限流返空）——不写覆盖，降级到缓存，保护既有好数据
    except Exception:
        pass  # 实时获取失败，降级到缓存

    # 2. 降级到缓存
    cached = load_cache(key, ttl)
    if cached is not None:
        return cached

    # 3. 返回兜底值
    return fallback_value
