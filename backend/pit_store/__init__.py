"""PIT (point-in-time) 快照存储——反前视引擎三层复现基建。

设计文档：specs/S162-反前视引擎三层/PIT-store-design.md

三层职责：
- ``store.SnapshotStore``：SQLite append-only 快照表（put/get/query_as_of/
  latest_snapshot_id/recompute_input）。不可变——无 UPDATE/DELETE。
- ``ingest_hook.wrap_fetch``：非侵入 PIT 包装器，VR_PIT_STORE=1 时在 fetch
  返回后存快照（默认关，不拖慢非复现 fetch）。
- ``query``：模块级便捷查询 API（query_as_of/recompute_input/latest_snapshot_id）。

存储：``<VR_DATA_DIR>/pit_store/pit_store.db``（.vibe-research 子目录，gitignored，
绝不进 git）。

两复现判据 wired（§2.6）：
- (a) verdict-reproducibility：从 S161 Recorder 存的完整 return series 重算 verdict。
- (b) data-revalidation：从 PIT pinned as_of snapshot 重导 series + content_hash 比；
  不匹配 → 诚实标"前复权重算（corporate action 后）"非假绿。
"""
from __future__ import annotations

from .store import SnapshotStore, run_migrations
from .ingest_hook import (
    install_hooks,
    pit_enabled,
    reset_default_store,
    wrap_fetch,
)
from .query import (
    latest_snapshot_id,
    query_as_of,
    recompute_input,
    reset_default,
)

__all__ = [
    "SnapshotStore",
    "run_migrations",
    "wrap_fetch",
    "pit_enabled",
    "install_hooks",
    "reset_default_store",
    "query_as_of",
    "recompute_input",
    "latest_snapshot_id",
    "reset_default",
]
