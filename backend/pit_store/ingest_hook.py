"""非侵入 PIT ingest hook——fetch 返回后存快照。

设计文档：specs/S162-反前视引擎三层/PIT-store-design.md §2.4

非侵入契约（关键）：
- ``VR_PIT_STORE != 1`` 时 ``wrap_fetch`` **原样返回**被包函数（不加 wrapper 层，
  零开销——不拖慢非复现 fetch 路径）。
- ``VR_PIT_STORE == 1`` 时返回同签名 wrapper——fetch 成功后 hook 存 snapshot；
  hook 内任何异常**绝不抛给 caller**（fetch 路径不被拖垮，防封底线：hook 只存返回值，
  不额外请求）。

接线方式：
- 显式：caller 用 ``wrap_fetch(my_fetch, source=...)`` 包自己的 fetch。
- 透明（best-effort）：``install_hooks()`` 就地 monkeypatch
  ``data.transport.eastmoney_get``（caller 代码不改；注意 astock.em_get 别名是
  import 时绑定的引用，完整覆盖须在 import astock 前安装，或 caller 直接用
  data.transport.eastmoney_get 源头）。
"""
from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any, Callable

from .store import SnapshotStore, _now_iso

logger = logging.getLogger(__name__)

#: 模块级默认 store 单例（VR_PIT_STORE=1 时 lazy 构造；复用 VR_DATA_DIR 隔离）。
_default_store: SnapshotStore | None = None


def pit_enabled() -> bool:
    """VR_PIT_STORE=1 才启用 PIT 快照（默认关，不拖慢非复现 fetch）。"""
    return os.environ.get("VR_PIT_STORE") == "1"


def _get_store() -> SnapshotStore:
    """lazy 默认 store 单例（重复 fetch 复用同一连接池句柄，避免每 fetch 建库）。"""
    global _default_store
    if _default_store is None:
        _default_store = SnapshotStore()
    return _default_store


def reset_default_store(store: SnapshotStore | None = None) -> None:
    """重置默认 store 单例（测试隔离用：monkeypatch 后清缓存）。"""
    global _default_store
    _default_store = store


def _to_raw_bytes(result: Any) -> bytes:
    """从 fetch 返回值提原始 bytes。

    - requests.Response / httpx.Response → ``.content``（raw bytes）。
    - bytes/bytearray → 直用。
    - str → utf-8 编码。
    - 其余（DataFrame / list / dict / None）→ JSON 序列化（default=str 宽容）。
    """
    content = getattr(result, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if isinstance(result, (bytes, bytearray)):
        return bytes(result)
    if isinstance(result, str):
        return result.encode("utf-8")
    return json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")


def wrap_fetch(
    fetch_fn: Callable,
    source: str,
    *,
    query_spec_builder: Callable[[tuple, dict], dict] | None = None,
    data_date_builder: Callable[[tuple, dict], str | None] | None = None,
    store: SnapshotStore | None = None,
) -> Callable:
    """非侵入 PIT 包装器。

    - ``VR_PIT_STORE != 1``：**原样返回** ``fetch_fn``（零开销，不加 wrapper 层）。
    - ``VR_PIT_STORE == 1``：返回同签名 wrapper——fetch 成功后存 snapshot；
      hook 异常**绝不抛给 caller**（fetch 路径不被拖垮）。

    Args:
        fetch_fn: 被包的 fetch 函数（如 ``data.transport.eastmoney_get``）。
        source: 快照 source 标签（如 ``"em_get"`` / ``"baostock_kline"``）。
        query_spec_builder: ``(args, kwargs) -> dict``，从调用参数构 query_spec；
            缺省 ``{"args": [...], "kwargs": {...}}``。
        data_date_builder: ``(args, kwargs) -> str | None``，从参数提 data_date（YYYYMMDD）；
            缺省 None。
        store: 指定 store（测试隔离用）；缺省 lazy 默认单例。
    """
    if not pit_enabled():
        return fetch_fn  # 零开销：非复现路径不加 wrapper 层

    @functools.wraps(fetch_fn)
    def wrapper(*args, **kwargs):
        result = fetch_fn(*args, **kwargs)
        try:
            spec = (
                query_spec_builder(args, kwargs)
                if query_spec_builder is not None
                else {"args": list(args), "kwargs": dict(kwargs)}
            )
            data_date = (
                data_date_builder(args, kwargs)
                if data_date_builder is not None
                else None
            )
            raw = _to_raw_bytes(result)
            target = store if store is not None else _get_store()
            target.put(
                as_of=_now_iso(),
                data_date=data_date,
                source=source,
                query_spec=spec,
                raw_bytes=raw,
            )
        except Exception as exc:  # noqa: BLE001 — hook 绝不拖垮 fetch
            logger.warning("[pit] ingest hook 失败 source=%s: %s", source, exc)
        return result

    return wrapper


def install_hooks() -> bool:
    """VR_PIT_STORE=1 时就地包装 ``data.transport.eastmoney_get``（caller 代码不改）。

    显式调用（**非 import 时自动**——避免 import 副作用，CLAUDE.md §4 backend 非
    package import 时接线坏）。供 app startup 或测试显式调用。

    注意（best-effort 透明包装的局限）：``astock.em_get`` 是 import 时的别名引用，
    本函数包 ``data.transport.eastmoney_get`` 源头后，**已 import astock 的 caller
    仍走旧别名**。完整覆盖须在 import astock 前安装，或 caller 直接用
    ``data.transport.eastmoney_get``。``wrap_fetch`` 是可测的核心单元；
    本函数提供 best-effort 透明层。

    Returns:
        True 已安装；False（VR_PIT_STORE != 1）未安装。
    """
    if not pit_enabled():
        return False
    import data.transport as t  # noqa: PLC0415

    def _em_spec(args: tuple, kwargs: dict) -> dict:
        url = args[0] if args else kwargs.get("url")
        params = kwargs.get("params") or (args[1] if len(args) > 1 else None)
        return {"url": url, "params": params, "headers": kwargs.get("headers")}

    t.eastmoney_get = wrap_fetch(
        t.eastmoney_get, source="em_get", query_spec_builder=_em_spec
    )
    return True
