"""S048: 盘前快照持久化 + GET date 级联 + /dates 端点。TDD 红→绿。

契约（spec S048 §5.2/5.3）：
- _collect done → 写盘 .vibe-research/workflow/pre-market/<date>.json（含 funnel_layers/is_backfill）
- GET 级联：内存(data_date==d) → 盘上快照(from_snapshot) → 今日 idle → 历史 no_snapshot
- /dates 返有快照日期降序（非法文件名剔除）
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import types

import pytest
from fastapi import HTTPException

from routers import workflow as wf
from factors.base import FactorResult


def _fr(fid: str) -> FactorResult:
    return FactorResult(factor_id=fid, factor_name=fid, candidates=[], layers=[], config={})


def _reset_cache(monkeypatch, status="idle", run_id=None, factors=None, data_date=None):
    monkeypatch.setattr(
        wf,
        "_cache",
        {
            "run_id": run_id,
            "status": status,
            "factors": factors,
            "data_date": data_date,
            "as_of": None,
            "market_emotion": None,
            "sentiment_context": None,
            "error": None,
        },
    )


class _FunnelLayer:
    """测试辅助：_collect 直接调 run_funnel（S049 C4 后不走 _build_funnel_layers），
    需 mock result.layers 含 model_dump 的对象，否则 .layers 访问抛 AttributeError
    被 except 捕获 → funnel_layers=[]。"""
    def __init__(self, layer_id="R1"):
        self.layer_id = layer_id

    def model_dump(self, mode=None):
        return {"layer_id": self.layer_id}


@pytest.fixture(autouse=True)
def _clean_snapshot_dir():
    """每个测试前后清空快照目录——VR_DATA_DIR 是全 session 共享临时目录，
    前面测试写入的 <date>.json 会污染后续 GET//dates 断言（快照是文件态，必须按测试隔离）。"""
    shutil.rmtree(wf._snapshot_dir(), ignore_errors=True)
    yield
    shutil.rmtree(wf._snapshot_dir(), ignore_errors=True)


# ── 快照写盘 ──────────────────────────────────────────────────────────


def test_collect_done_writes_snapshot_file(monkeypatch):
    """done 采集 → 落盘 <date>.json，payload 含 schema/factors/funnel_layers/is_backfill。"""
    async def fake_afetch(date, config=None):
        return [_fr("f1"), _fr("f2")]

    monkeypatch.setattr(wf.factor_registry, "afetch_all", fake_afetch)
    monkeypatch.setattr(wf.factor_registry, "register_default_factors", lambda: None)
    monkeypatch.setattr(wf, "_fetch_market_emotion", lambda d, ctx=None: {"sentiment": "neutral"})
    # S048：funnel_layers 构建（真跑会碰外部源）与快照落盘均隔离
    monkeypatch.setattr(wf, "_build_funnel_layers", lambda d, ctx=None: [{"layer_id": "R1"}])
    # S049 C4：final_candidates 诊断卡构建隔离（真跑会碰外部源）
    # _collect 直接调 funnel_mod.run_funnel 并访问 .layers/.final_candidates（S049 C4 后
    # 不走 _build_funnel_layers），mock result 必须含 layers 属性 + 可 model_dump 的层对象。
    monkeypatch.setattr(wf.funnel_mod, "run_funnel", lambda stage, date, cfg, ctx=None: types.SimpleNamespace(final_candidates=[], layers=[_FunnelLayer("R1")]))
    monkeypatch.setattr(wf.funnel_mod, "clear_funnel_cache", lambda date=None: None)
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")
    _reset_cache(monkeypatch, status="running", run_id="rid1")

    asyncio.run(wf._collect("rid1", "2026-08-03"))

    assert wf._cache["status"] == "done"
    path = wf._snapshot_path("2026-08-03")
    assert path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == "v1"
    assert payload["data_date"] == "2026-08-03"
    assert payload["run_id"] == "rid1"
    assert [f["factor_id"] for f in payload["factors"]] == ["f1", "f2"]
    assert payload["funnel_layers"] == [{"layer_id": "R1"}]
    assert payload["market_emotion"] == {"sentiment": "neutral"}
    assert payload["is_backfill"] is True  # 08-03 < 最近交易日 08-07
    assert payload["as_of"]
    assert payload["final_candidates"] == []  # S049 C4
    assert "sentiment_context" in payload  # S063 T9


def test_collect_today_not_backfill(monkeypatch):
    """target_date == 最近交易日 → is_backfill False。"""
    async def fake_afetch(date, config=None):
        return [_fr("f1")]

    monkeypatch.setattr(wf.factor_registry, "afetch_all", fake_afetch)
    monkeypatch.setattr(wf.factor_registry, "register_default_factors", lambda: None)
    monkeypatch.setattr(wf, "_fetch_market_emotion", lambda d, ctx=None: {})
    monkeypatch.setattr(wf, "_build_funnel_layers", lambda d, ctx=None: [])
    monkeypatch.setattr(wf.funnel_mod, "run_funnel", lambda stage, date, cfg, ctx=None: types.SimpleNamespace(final_candidates=[], layers=[]))
    monkeypatch.setattr(wf.funnel_mod, "clear_funnel_cache", lambda date=None: None)
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")
    _reset_cache(monkeypatch, status="running", run_id="rid2")

    asyncio.run(wf._collect("rid2", "2026-08-07"))

    payload = json.loads(wf._snapshot_path("2026-08-07").read_text(encoding="utf-8"))
    assert payload["is_backfill"] is False


def test_collect_snapshot_write_failure_still_done(monkeypatch):
    """写盘失败不影响内存 done（降级：内存态仍可用）。"""
    async def fake_afetch(date, config=None):
        return [_fr("f1")]

    def boom(payload):
        raise OSError("disk full")

    monkeypatch.setattr(wf.factor_registry, "afetch_all", fake_afetch)
    monkeypatch.setattr(wf.factor_registry, "register_default_factors", lambda: None)
    monkeypatch.setattr(wf, "_fetch_market_emotion", lambda d, ctx=None: {})
    monkeypatch.setattr(wf, "_build_funnel_layers", lambda d, ctx=None: [])
    monkeypatch.setattr(wf.funnel_mod, "run_funnel", lambda stage, date, cfg, ctx=None: types.SimpleNamespace(final_candidates=[], layers=[]))
    monkeypatch.setattr(wf.funnel_mod, "clear_funnel_cache", lambda date=None: None)
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")
    monkeypatch.setattr(wf, "_save_snapshot", boom)
    _reset_cache(monkeypatch, status="running", run_id="rid3")

    asyncio.run(wf._collect("rid3", "2026-08-03"))

    assert wf._cache["status"] == "done"


def test_build_funnel_layers_uses_live_config(monkeypatch):
    """_build_funnel_layers：run_funnel("all", date, live config) → layers 序列化。"""
    captured = {}

    class _Layer:
        def __init__(self, lid):
            self.lid = lid

        def model_dump(self, mode=None):
            return {"layer_id": self.lid, "mode": mode}

    class _Result:
        layers = [_Layer("R1"), _Layer("R2")]

    def fake_run_funnel(scope, date, config, ctx=None):
        captured["args"] = (scope, date, config)
        return _Result()

    fake_cand = types.ModuleType("routers.candidates")
    fake_cand._store = {"config": {"min_score": 7}}
    monkeypatch.setitem(sys.modules, "routers.candidates", fake_cand)
    monkeypatch.setattr(wf.funnel_mod, "run_funnel", fake_run_funnel)

    layers = wf._build_funnel_layers("2026-08-03")

    assert captured["args"] == ("all", "2026-08-03", {"min_score": 7})
    assert [l["layer_id"] for l in layers] == ["R1", "R2"]


def test_build_funnel_layers_failure_returns_empty(monkeypatch):
    """run_funnel 抛错 → 空 list（不阻塞采集主流程）。"""
    def boom(scope, date, config, ctx=None):
        raise RuntimeError("外部源挂了")

    fake_cand = types.ModuleType("routers.candidates")
    fake_cand._store = {"config": {}}
    monkeypatch.setitem(sys.modules, "routers.candidates", fake_cand)
    monkeypatch.setattr(wf.funnel_mod, "run_funnel", boom)

    assert wf._build_funnel_layers("2026-08-03") == []


# ── 快照存取 roundtrip ────────────────────────────────────────────────


def test_snapshot_roundtrip_and_missing():
    """_save_snapshot/_load_snapshot roundtrip；不存在返 None。"""
    payload = {"schema": "v1", "data_date": "2026-07-01", "factors": []}
    wf._save_snapshot(payload)
    loaded = wf._load_snapshot("2026-07-01")
    assert loaded == payload
    assert wf._load_snapshot("1999-01-01") is None


# ── GET date 级联 ─────────────────────────────────────────────────────


def test_get_memory_running_preferred_over_disk(monkeypatch):
    """内存 data_date==d 且 running → 返内存态（不看盘）。"""
    _reset_cache(monkeypatch, status="running", run_id="rid-live", data_date="2026-08-03")
    r = asyncio.run(wf.get_pre_market_workflow(date="2026-08-03"))
    assert r["status"] == "running"
    assert r["run_id"] == "rid-live"


def test_get_history_snapshot_from_disk(monkeypatch):
    """内存 idle + 盘上有该日快照 → done + from_snapshot + 盘上 factors/funnel_layers。"""
    _reset_cache(monkeypatch, status="idle")
    wf._save_snapshot({
        "schema": "v1",
        "data_date": "2026-07-01",
        "as_of": "2026-07-01T08:30:00",
        "run_id": "oldsnap",
        "market_emotion": {"phase": "bullish"},
        "factors": [{"factor_id": "hist1"}],
        "funnel_layers": [{"layer_id": "R1"}],
        "is_backfill": False,
    })
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")

    r = asyncio.run(wf.get_pre_market_workflow(date="2026-07-01"))

    assert r["status"] == "done"
    assert r["from_snapshot"] is True
    assert [f["factor_id"] for f in r["factors"]] == ["hist1"]
    assert r["funnel_layers"] == [{"layer_id": "R1"}]
    assert r["data_date"] == "2026-07-01"


def test_get_today_snapshot_after_restart(monkeypatch):
    """A6：重启后（内存 data_date=None）今日 GET → 走盘上快照 done + from_snapshot，无需重采。"""
    _reset_cache(monkeypatch, status="idle")  # data_date=None 模拟重启后全新内存
    wf._save_snapshot({
        "schema": "v1", "data_date": "2026-08-07", "as_of": "2026-08-07T08:30:00",
        "run_id": "r-today", "market_emotion": {}, "factors": [{"factor_id": "t1"}],
        "funnel_layers": [], "is_backfill": False,
    })
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")

    r = asyncio.run(wf.get_pre_market_workflow(date="2026-08-07"))

    assert r["status"] == "done"
    assert r["from_snapshot"] is True
    assert [f["factor_id"] for f in r["factors"]] == ["t1"]


def test_get_snapshot_zero_external_requests(monkeypatch):
    """A3：快照分支纯读盘——factor_registry/漏斗链路一律不得触达。"""
    def _boom(*_a, **_kw):
        raise AssertionError("快照分支不应触发外部采集")

    _reset_cache(monkeypatch, status="idle")
    wf._save_snapshot({"schema": "v1", "data_date": "2026-07-01", "factors": [], "funnel_layers": []})
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")
    monkeypatch.setattr(wf.factor_registry, "afetch_all", _boom)
    monkeypatch.setattr(wf, "_build_funnel_layers", _boom)

    r = asyncio.run(wf.get_pre_market_workflow(date="2026-07-01"))

    assert r["status"] == "done" and r["from_snapshot"] is True


# ── R7 后端历史不可变守卫（I2）──────────────────────────────────────────


def test_refresh_rejects_overwrite_of_history_snapshot(monkeypatch):
    """I2：盘上已有历史快照 + target_date < 最近交易日 → refresh 返 409，不覆写。"""
    _reset_cache(monkeypatch, status="idle")
    wf._save_snapshot({"schema": "v1", "data_date": "2026-07-01", "factors": [], "funnel_layers": []})
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")

    with pytest.raises(HTTPException) as ei:
        asyncio.run(wf.refresh_pre_market(date="2026-07-01"))
    assert ei.value.status_code == 409
    assert "2026-07-01" in ei.value.detail
    assert wf._cache["status"] == "idle"  # 未进入 running 态


def test_refresh_allows_today_even_with_snapshot(monkeypatch):
    """I2：今日（target_date == 最近交易日）有快照仍可重采——今日不可变守卫不触发。"""
    _reset_cache(monkeypatch, status="idle")
    wf._save_snapshot({"schema": "v1", "data_date": "2026-08-07", "factors": [], "funnel_layers": []})
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")

    # 守卫不触发；进 running 后 asyncio.create_task 挂后台不 await，直接返 running
    def _noop_create_task(*_a, **_kw):
        # S068 R2 后 create_task 返的 Task 须支持 add_done_callback；原 async def 返 coroutine 无此方法致 AttributeError
        if _a and hasattr(_a[0], "close"):
            _a[0].close()  # 测试不真跑 _collect；关闭传入协程防 "never awaited" warning
        class _FakeTask:
            def add_done_callback(self, _cb) -> None: pass
        return _FakeTask()

    monkeypatch.setattr(wf.asyncio, "create_task", _noop_create_task)
    r = asyncio.run(wf.refresh_pre_market(date="2026-08-07"))
    assert r["status"] == "running"


def test_refresh_allows_backfill_for_missing_history(monkeypatch):
    """I2：历史日期无快照 → refresh 正常触发（no_snapshot → 补采链路）。"""
    _reset_cache(monkeypatch, status="idle")
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")
    assert wf._load_snapshot("2026-06-01") is None

    def _noop_create_task(*_a, **_kw):
        # S068 R2 后 create_task 返的 Task 须支持 add_done_callback；原 async def 返 coroutine 无此方法致 AttributeError
        if _a and hasattr(_a[0], "close"):
            _a[0].close()  # 测试不真跑 _collect；关闭传入协程防 "never awaited" warning
        class _FakeTask:
            def add_done_callback(self, _cb) -> None: pass
        return _FakeTask()

    monkeypatch.setattr(wf.asyncio, "create_task", _noop_create_task)
    r = asyncio.run(wf.refresh_pre_market(date="2026-06-01"))
    assert r["status"] == "running"


def test_get_today_no_snapshot_idle(monkeypatch):
    """无快照 + d == 最近交易日 → idle（提示 refresh）。"""
    _reset_cache(monkeypatch, status="idle")
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")
    r = asyncio.run(wf.get_pre_market_workflow(date="2026-08-07"))
    assert r["status"] == "idle"
    assert "refresh" in r["msg"]


def test_get_old_date_no_snapshot(monkeypatch):
    """无快照 + d != 最近交易日 → no_snapshot（前端提示补采）。"""
    _reset_cache(monkeypatch, status="idle")
    monkeypatch.setattr(wf, "last_trading_date_str", lambda: "2026-08-07")
    r = asyncio.run(wf.get_pre_market_workflow(date="2026-06-01"))
    assert r["status"] == "no_snapshot"
    assert r["data_date"] == "2026-06-01"


def test_get_invalid_date_400(monkeypatch):
    """非法日期格式 → 400。"""
    _reset_cache(monkeypatch, status="idle")
    with pytest.raises(HTTPException) as ei:
        asyncio.run(wf.get_pre_market_workflow(date="2026-13-99"))
    assert ei.value.status_code == 400


# ── /dates 端点 ───────────────────────────────────────────────────────


def test_dates_empty_dir(monkeypatch):
    _reset_cache(monkeypatch)
    r = wf.get_pre_market_dates()  # sync 函数直接调（原 asyncio.run 调 sync 返 dict 致 TypeError）
    assert r == {"dates": []}


def test_dates_lists_snapshot_dates_desc(monkeypatch):
    """有快照日期降序；非法文件名剔除。"""
    _reset_cache(monkeypatch)
    wf._save_snapshot({"schema": "v1", "data_date": "2026-07-01"})
    wf._save_snapshot({"schema": "v1", "data_date": "2026-08-03"})
    wf._save_snapshot({"schema": "v1", "data_date": "2026-07-15"})
    # 干扰文件：非日期名
    (wf._snapshot_dir() / "not-a-date.json").write_text("{}", encoding="utf-8")

    r = wf.get_pre_market_dates()  # sync 函数直接调（原 asyncio.run 调 sync 返 dict 致 TypeError）
    assert r["dates"] == ["2026-08-03", "2026-07-15", "2026-07-01"]


def test_save_snapshot_with_dataclass_payload(tmp_path, monkeypatch):
    """payload 含裸 dataclass 实例时 _save_snapshot 不崩，落盘为 dict。

    regression for PositionParams serialization bug (log-patrol 告警)。
    """
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class _FakeParams:
        stop_loss_pct: float
        take_profit_pct: float

    monkeypatch.setattr(wf, "_snapshot_dir", lambda: tmp_path)
    # _is_valid_date 若在模块级，按既有测试范式 mock；参考文件内其他用例怎么 mock 的
    payload = {"data_date": "2026-08-20", "position_params": _FakeParams(-3.0, 8.0)}
    wf._save_snapshot(payload)  # 改前会抛 TypeError，改后应成功
    import json
    loaded = json.loads((tmp_path / "2026-08-20.json").read_text(encoding="utf-8"))
    assert loaded["position_params"] == {"stop_loss_pct": -3.0, "take_profit_pct": 8.0}
