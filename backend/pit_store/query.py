"""模块级便捷查询 API（委托默认 SnapshotStore 单例）。

设计文档：specs/S162-反前视引擎三层/PIT-store-design.md §2.3

用法：``from pit_store import query_as_of, recompute_input, latest_snapshot_id``
（conftest 已把 backend/ 加 sys.path，``import pit_store`` 即可）。

S161 Recorder 接 ``data_snapshot_id = latest_snapshot_id(source, data_date)``；
S162 engine 回测读 ``query_as_of(source, data_date, as_of=verdict_as_of)`` 替代
live kline_cache（复现性）。
"""
from __future__ import annotations

from .store import SnapshotStore

_default: SnapshotStore | None = None


def _store() -> SnapshotStore:
    """lazy 默认 store 单例（VR_DATA_DIR 隔离；测试 monkeypatch VR_DATA_DIR 后首次调生效）。"""
    global _default
    if _default is None:
        _default = SnapshotStore()
    return _default


def reset_default(store: SnapshotStore | None = None) -> None:
    """重置单例（测试隔离用）。"""
    global _default
    _default = store


def query_as_of(
    source: str, data_date: str | None, as_of: str | None = None
) -> bytes | None:
    """point-in-time 查询：≤ as_of 最近快照 raw（as_of=None → 最新）。无匹配返 None。"""
    return _store().query_as_of(source, data_date, as_of)


def recompute_input(snapshot_id: int) -> bytes | None:
    """复现取数：从 pinned snapshot 取 raw（不 re-fetch）。§2.6 复现判据 (b) 源。"""
    return _store().recompute_input(snapshot_id)


def latest_snapshot_id(source: str, data_date: str | None) -> int | None:
    """(source, data_date) 最新 snapshot_id——给 S161 Recorder 作 data_snapshot_id。"""
    return _store().latest_snapshot_id(source, data_date)
