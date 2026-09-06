# -*- coding: utf-8 -*-
"""PIT (point-in-time) 快照存储单测。

设计文档：specs/S162-反前视引擎三层/PIT-store-design.md

覆盖：
1. snapshot put/get 回读一致。
2. query_as_of point-in-time（≤ as_of 取最近；as_of=None 取最新）。
3. recompute_input content_hash 匹配（复现判据 §2.6b 核心）。
4. append-only 不可变（同 key 再 put 创建新行，不覆盖旧行）。
5. ingest_hook 非侵入（VR_PIT_STORE=0 → 原样返回 + 无快照；=1 → 包装 + 存快照；
   hook 异常绝不拖垮 fetch）。
6. migration 幂等（run_migrations 连跑两遍 + store 自建 schema 双保险）。

所有写入经 tmp db——绝不碰用户真实 .vibe-research/pit_store/pit_store.db。
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from pit_store import (
    SnapshotStore,
    run_migrations,
    wrap_fetch,
)
from pit_store import ingest_hook as ih


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def store(tmp_path) -> SnapshotStore:
    """tmp pit_store.db（隔离用户真实库）。"""
    return SnapshotStore(db_path=tmp_path / "pit_store.db")


class _FakeResponse:
    """模拟 requests.Response（含 .content raw bytes）。"""

    def __init__(self, content: bytes):
        self.content = content


def _fake_fetch(url: str, params: dict | None = None) -> _FakeResponse:
    """假 fetch（无网络，返回固定 Response）。"""
    return _FakeResponse(b'{"code":"600519","rows":[1,2,3]}')


# ── 1. put/get ───────────────────────────────────────────────────────────


def test_put_get_roundtrip(store: SnapshotStore):
    """put → get 回读：source/data_date/raw_blob/query_spec/generator_commit 一致。"""
    # Arrange
    raw = b'{"k":1,"v":2}'
    # Act
    sid = store.put(
        as_of="2026-09-06T10:00:00+08:00",
        data_date="20260906",
        source="baostock_kline",
        query_spec={"code": "600519", "adjustflag": "2", "start": "2026-01-01"},
        raw_bytes=raw,
        generator_commit="abc123",
    )
    # Assert
    assert sid >= 1
    row = store.get(sid)
    assert row is not None
    assert row["source"] == "baostock_kline"
    assert row["data_date"] == "20260906"
    assert row["as_of"] == "2026-09-06T10:00:00+08:00"
    assert row["fetched_at"] == row["as_of"]
    assert row["generator_commit"] == "abc123"
    assert bytes(row["raw_blob"]) == raw
    assert row["content_hash"] == hashlib.sha256(raw).hexdigest()
    # query_spec JSON 回读
    import json

    spec = json.loads(row["query_spec"])
    assert spec["code"] == "600519"
    assert spec["adjustflag"] == "2"


def test_put_str_raw_bytes_accepted(store: SnapshotStore):
    """raw_bytes 接受 str（utf-8 编码）+ as_of 缺省取当前时刻。"""
    sid = store.put(
        source="em_get",
        query_spec={"url": "http://x"},
        raw_bytes='{"a":1}',  # str
    )
    row = store.get(sid)
    assert row is not None
    assert bytes(row["raw_blob"]) == b'{"a":1}'
    assert row["as_of"]  # 自动取当前时刻
    assert row["fetched_at"] == row["as_of"]


def test_put_rejects_non_bytes_str(store: SnapshotStore):
    """raw_bytes 非 bytes/str → TypeError（输入校验 fail fast）。"""
    with pytest.raises(TypeError):
        store.put(source="x", query_spec={}, raw_bytes=123)  # type: ignore[arg-type]


# ── 2. query_as_of point-in-time ──────────────────────────────────────────


def test_query_as_of_returns_latest_when_no_as_of(store: SnapshotStore):
    """as_of=None → 返回最新快照 raw。"""
    store.put(as_of="2026-09-01T09:00:00+08:00", data_date="20260901",
              source="baostock_kline", query_spec={}, raw_bytes=b"old")
    store.put(as_of="2026-09-06T09:00:00+08:00", data_date="20260901",
              source="baostock_kline", query_spec={}, raw_bytes=b"new")
    # Act
    raw = store.query_as_of("baostock_kline", "20260901", as_of=None)
    # Assert
    assert raw == b"new"


def test_query_as_of_point_in_time_le_as_of(store: SnapshotStore):
    """as_of 给定 → 返回 ≤ as_of 的最近快照（point-in-time：不见未来）。"""
    store.put(as_of="2026-09-01T09:00:00+08:00", data_date="20260901",
              source="baostock_kline", query_spec={}, raw_bytes=b"v1")
    store.put(as_of="2026-09-03T09:00:00+08:00", data_date="20260901",
              source="baostock_kline", query_spec={}, raw_bytes=b"v2")
    store.put(as_of="2026-09-05T09:00:00+08:00", data_date="20260901",
              source="baostock_kline", query_spec={}, raw_bytes=b"v3")
    # Act: as_of 在 v2 和 v3 之间 → 应见 v2（不见 v3 未来）
    raw = store.query_as_of("baostock_kline", "20260901", as_of="2026-09-04T00:00:00+08:00")
    assert raw == b"v2"
    # as_of 恰好等于 v3 时刻 → 见 v3
    raw = store.query_as_of("baostock_kline", "20260901", as_of="2026-09-05T09:00:00+08:00")
    assert raw == b"v3"
    # as_of 早于所有 → None
    raw = store.query_as_of("baostock_kline", "20260901", as_of="2026-08-31T00:00:00+08:00")
    assert raw is None


def test_query_as_of_no_match_returns_none(store: SnapshotStore):
    """无匹配 source/data_date → None。"""
    store.put(as_of="2026-09-01", data_date="20260901",
              source="baostock_kline", query_spec={}, raw_bytes=b"x")
    assert store.query_as_of("other_source", "20260901") is None
    assert store.query_as_of("baostock_kline", "20261231") is None


def test_query_as_of_null_data_date(store: SnapshotStore):
    """data_date=None 能匹配 NULL 行（IS NULL 语义）。"""
    store.put(as_of="2026-09-01", data_date=None,
              source="em_get", query_spec={"url": "u"}, raw_bytes=b"r")
    raw = store.query_as_of("em_get", None)
    assert raw == b"r"
    sid = store.latest_snapshot_id("em_get", None)
    assert sid is not None


# ── 3. recompute_input content_hash ───────────────────────────────────────


def test_recompute_input_hash_match(store: SnapshotStore):
    """recompute_input 返回 raw，sha256 == 存储 content_hash（复现判据 §2.6b 核心）。"""
    raw = b'{"close":[10.0,10.5,11.0]}'
    sid = store.put(as_of="2026-09-06T15:00:00+08:00", data_date="20260906",
                    source="baostock_kline", query_spec={"code": "600519"},
                    raw_bytes=raw)
    # Act
    recomputed = store.recompute_input(sid)
    stored_hash = store.content_hash(sid)
    # Assert
    assert recomputed == raw
    assert hashlib.sha256(recomputed).hexdigest() == stored_hash


def test_recompute_input_missing_returns_none(store: SnapshotStore):
    """不存在 snapshot_id → None。"""
    assert store.recompute_input(99999) is None
    assert store.content_hash(99999) is None


# ── 4. append-only immutability ──────────────────────────────────────────


def test_append_only_same_key_creates_new_row_not_overwrite(store: SnapshotStore):
    """同 (source, data_date, as_of) 再 put 创建新行——旧行不被覆盖（前复权 mutation 锁定）。"""
    # Arrange: 同 key 两次 put（as_of 相同）
    sid1 = store.put(as_of="2026-09-06T10:00:00+08:00", data_date="20260906",
                     source="baostock_kline", query_spec={"ver": 1}, raw_bytes=b"old_data")
    sid2 = store.put(as_of="2026-09-06T10:00:00+08:00", data_date="20260906",
                     source="baostock_kline", query_spec={"ver": 2}, raw_bytes=b"new_data")
    # Assert: 两行都在，sid 不同
    assert sid1 != sid2
    assert store.count("baostock_kline") == 2
    # 旧行 raw 未被覆盖
    assert store.recompute_input(sid1) == b"old_data"
    assert store.recompute_input(sid2) == b"new_data"
    # latest_snapshot_id 返回最新（sid2）
    assert store.latest_snapshot_id("baostock_kline", "20260906") == sid2
    # query_as_of(None) 返回最新 raw
    assert store.query_as_of("baostock_kline", "20260906") == b"new_data"


def test_no_update_delete_methods_exposed(store: SnapshotStore):
    """不可变：SnapshotStore 不暴露 update/delete 方法（append-only 约束）。"""
    for forbidden in ("update", "delete", "remove", "drop"):
        assert not hasattr(store, forbidden), f"SnapshotStore 不应有 {forbidden}（append-only）"


# ── 5. ingest_hook non-invasive ──────────────────────────────────────────


def test_wrap_fetch_disabled_when_env_off(store: SnapshotStore, monkeypatch):
    """VR_PIT_STORE 未设 → wrap_fetch 原样返回 fetch_fn（零开销，不加 wrapper 层）。"""
    # Arrange
    monkeypatch.delenv("VR_PIT_STORE", raising=False)
    ih.reset_default_store()  # 清单例缓存
    # Act
    wrapped = wrap_fetch(_fake_fetch, source="em_get", store=store)
    # Assert: 原样返回（identity），无 wrapper 层
    assert wrapped is _fake_fetch
    # 调用不产生快照
    r = wrapped("http://x", params={"a": 1})
    assert r.content == b'{"code":"600519","rows":[1,2,3]}'
    assert store.count("em_get") == 0


def test_wrap_fetch_enabled_stores_snapshot(store: SnapshotStore, monkeypatch):
    """VR_PIT_STORE=1 → wrap_fetch 包装，fetch 返回后存快照，返回值不变。"""
    # Arrange
    monkeypatch.setenv("VR_PIT_STORE", "1")
    ih.reset_default_store()
    # Act
    wrapped = wrap_fetch(
        _fake_fetch,
        source="em_get",
        query_spec_builder=lambda a, k: {"url": a[0], "params": k.get("params")},
        data_date_builder=lambda a, k: "20260906",
        store=store,
    )
    # Assert: 被包了（非 identity）
    assert wrapped is not _fake_fetch
    r = wrapped("http://x", params={"a": 1})
    # 返回值原样（透明）
    assert r.content == b'{"code":"600519","rows":[1,2,3]}'
    # 快照已存
    assert store.count("em_get") == 1
    sid = store.latest_snapshot_id("em_get", "20260906")
    assert sid is not None
    raw = store.recompute_input(sid)
    assert raw == b'{"code":"600519","rows":[1,2,3]}'
    # query_spec 含 url/params（builder 生效）
    import json
    row = store.get(sid)
    spec = json.loads(row["query_spec"])
    assert spec["url"] == "http://x"
    assert spec["params"] == {"a": 1}


def test_wrap_fetch_hook_failure_never_breaks_fetch(store: SnapshotStore, monkeypatch):
    """hook 存快照失败（store.put 抛异常）→ fetch 仍正常返回（防封底线：hook 绝不拖垮 fetch）。"""
    # Arrange
    monkeypatch.setenv("VR_PIT_STORE", "1")
    ih.reset_default_store()

    class _BrokenStore:
        def put(self, **_kwargs):
            raise RuntimeError("simulated store failure")

    # Act
    wrapped = wrap_fetch(_fake_fetch, source="em_get", store=_BrokenStore())
    r = wrapped("http://x")  # 不得 raise
    # Assert: fetch 返回值正常（hook 异常被吞 + warning）
    assert r.content == b'{"code":"600519","rows":[1,2,3]}'


def test_wrap_fetch_default_spec_when_no_builder(store: SnapshotStore, monkeypatch):
    """query_spec_builder 缺省 → spec = {args, kwargs}（足够复现查询输入）。"""
    monkeypatch.setenv("VR_PIT_STORE", "1")
    ih.reset_default_store()
    wrapped = wrap_fetch(_fake_fetch, source="em_get", store=store)
    wrapped("http://x", params={"a": 1})
    import json
    sid = store.latest_snapshot_id("em_get", None)
    assert sid is not None
    spec = json.loads(store.get(sid)["query_spec"])
    assert spec["args"][0] == "http://x"
    assert spec["kwargs"]["params"] == {"a": 1}


def test_to_raw_bytes_variants():
    """_to_raw_bytes 提 raw：Response.content / bytes / str / JSON 序列化。"""
    assert ih._to_raw_bytes(_FakeResponse(b"raw")) == b"raw"
    assert ih._to_raw_bytes(b"bytes") == b"bytes"
    assert ih._to_raw_bytes("text") == b"text"
    assert ih._to_raw_bytes({"k": 1}) == b'{"k": 1}'
    assert ih._to_raw_bytes([1, 2]) == b"[1, 2]"


# ── 6. migration idempotent + self-create ─────────────────────────────────


def test_run_migrations_idempotent(tmp_path):
    """run_migrations 连跑两遍不报错（MigrationManager 版本表保证幂等）。"""
    db = tmp_path / "pit.db"
    run_migrations(db_path=db)
    run_migrations(db_path=db)  # 第二遍：已应用版本跳过
    # 表存在
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(snapshots)").fetchall()}
    conn.close()
    for col in (
        "snapshot_id", "as_of", "data_date", "source", "query_spec",
        "content_hash", "raw_blob", "fetched_at", "generator_commit",
    ):
        assert col in cols, f"列 {col} 未创建"


def test_store_self_creates_schema_without_migration(tmp_path):
    """store 构造即建表（防御性自建，不依赖显式 run_migrations）。"""
    db = tmp_path / "self_create.db"
    assert not db.exists()
    s = SnapshotStore(db_path=db)
    assert db.exists()
    # put 能用（表已建）
    sid = s.put(source="em_get", query_spec={}, raw_bytes=b"ok")
    assert s.recompute_input(sid) == b"ok"
