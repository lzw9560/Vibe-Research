# -*- coding: utf-8 -*-
"""S046：fallback 空写防护——限流返空不覆盖好缓存 + 损坏快照自愈。"""
import json

import fallback
import pytest


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """每个用例用独立缓存目录 + 干净内存缓存。"""
    monkeypatch.setattr(fallback, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(fallback, "_MEM_CACHE", {})
    return tmp_path


# ============ R1：_is_empty 判定 ============


class TestIsEmpty:
    def test_空容器为空(self):
        assert fallback._is_empty([]) is True
        assert fallback._is_empty({}) is True
        assert fallback._is_empty("") is True
        assert fallback._is_empty(()) is True
        assert fallback._is_empty(set()) is True

    def test_None为空(self):
        assert fallback._is_empty(None) is True

    def test_标量不算空(self):
        assert fallback._is_empty(0) is False
        assert fallback._is_empty(False) is False
        assert fallback._is_empty(0.0) is False

    def test_非空容器不算空(self):
        assert fallback._is_empty([1, 2, 3]) is False
        assert fallback._is_empty({"a": 1}) is False
        assert fallback._is_empty([{}]) is False  # len=1


# ============ R2：save_cache 空数据不覆盖好缓存 ============


def test_save_cache_空list不覆盖好缓存(isolated_cache):
    fallback.save_cache("k", [{"main_net": 100}])
    fallback.save_cache("k", [])  # 限流返空——不应覆盖
    good = fallback.load_cache("k")
    assert good == [{"main_net": 100}]
    # 文件内容仍是好数据
    raw = json.loads((isolated_cache / "k.json").read_text())
    assert raw["data"] == [{"main_net": 100}]


def test_save_cache_空dict不覆盖好缓存(isolated_cache):
    fallback.save_cache("k", {"signal": 0.5})
    fallback.save_cache("k", {})
    assert fallback.load_cache("k") == {"signal": 0.5}


def test_save_cache_空数据不创建文件(isolated_cache):
    fallback.save_cache("k", [])
    assert not (isolated_cache / "k.json").exists()
    assert fallback.load_cache("k") is None


# ============ R3：load_cache 损坏空快照自愈 ============


def test_load_cache_损坏空快照返None并删除(isolated_cache):
    path = isolated_cache / "k.json"
    path.write_text(json.dumps({"ts": 99999999999, "data": []}))  # 空 data 损坏
    assert fallback.load_cache("k") is None
    assert not path.exists()  # 自愈删除


def test_load_cache_正常快照正常返回(isolated_cache):
    path = isolated_cache / "k.json"
    path.write_text(json.dumps({"ts": 99999999999, "data": [{"x": 1}]}))
    assert fallback.load_cache("k") == [{"x": 1}]


# ============ R4：get_with_fallback 空数据降级缓存 ============


def test_get_with_fallback_空fetch用好缓存兜底(isolated_cache):
    fallback.save_cache("k", [{"main_net": 100}])  # 既有好缓存
    # fetch 返空（限流）——应降级到好缓存，而非写空覆盖
    result = fallback.get_with_fallback("k", lambda: [], ttl=600, fallback_value=[])
    assert result == [{"main_net": 100}]
    # 缓存未被空覆盖
    assert fallback.load_cache("k") == [{"main_net": 100}]


def test_get_with_fallback_空fetch无缓存回fallback(isolated_cache):
    result = fallback.get_with_fallback("k", lambda: [], ttl=600, fallback_value=[])
    assert result == []


def test_get_with_fallback_异常降级缓存(isolated_cache):
    fallback.save_cache("k", [{"main_net": 100}])

    def boom():
        raise RuntimeError("throttled")

    result = fallback.get_with_fallback("k", boom, ttl=600, fallback_value=[])
    assert result == [{"main_net": 100}]


def test_get_with_fallback_正常fetch正常缓存(isolated_cache):
    result = fallback.get_with_fallback("k", lambda: [{"main_net": 7}], ttl=600, fallback_value=[])
    assert result == [{"main_net": 7}]
    assert fallback.load_cache("k") == [{"main_net": 7}]


# ============ A4：标量不被当空 ============


def test_save_cache_标量0正常缓存(isolated_cache):
    fallback.save_cache("k", 0)
    assert fallback.load_cache("k") == 0


# ============ S046 二次污染：嵌套空骨架（2026-08-10 dragon_tiger 事故） ============

_DT_SKELETON = {
    "records": [],
    "seats": {"buy": [], "sell": []},
    "institution": {"buy_amt": 0.0, "sell_amt": 0.0, "net_amt": 0.0},
}
_DT_GOOD = {"records": [{"date": "2026-07-23", "net_buy": 2467.5}],
            "seats": {"buy": [{"name": "X", "buy_amt": 1.0}], "sell": []},
            "institution": {"buy_amt": 1.0, "sell_amt": 0.0, "net_amt": 1.0}}


def test_is_empty_嵌套空骨架为空():
    assert fallback._is_empty(_DT_SKELETON) is True
    assert fallback._is_empty({"top": [], "bottom": []}) is True
    assert fallback._is_empty({"zt": [], "dt": [], "zb": []}) is True


def test_is_empty_有实数据骨架不为空():
    assert fallback._is_empty(_DT_GOOD) is False
    assert fallback._is_empty({"records": [{"a": 1}]}) is False
    assert fallback._is_empty([{"main_net": 100}]) is False  # 顶层 list 非空即非空


def test_save_cache_空骨架不覆盖好缓存(isolated_cache):
    fallback.save_cache("k", _DT_GOOD)
    fallback.save_cache("k", _DT_SKELETON)  # 限流空骨架——不应覆盖
    assert fallback.load_cache("k") == _DT_GOOD


def test_get_with_fallback_空骨架用好缓存兜底(isolated_cache):
    fallback.save_cache("k", _DT_GOOD)
    result = fallback.get_with_fallback("k", lambda: _DT_SKELETON, ttl=600, fallback_value={"records": []})
    assert result == _DT_GOOD
    assert fallback.load_cache("k") == _DT_GOOD


def test_load_cache_损坏空骨架自愈(isolated_cache):
    path = isolated_cache / "k.json"
    path.write_text(json.dumps({"ts": 99999999999, "data": _DT_SKELETON}))
    assert fallback.load_cache("k") is None
    assert not path.exists()


# ============ S131 R8：data_status='missing' 失败标记 dict 视为空 ============
# industry_comparison 默认失败返 {"top":[],...,"data_status":"missing"}，
# "missing" 字符串使旧 _is_empty 漏网（dict 非空）→ get_with_fallback_meta
# 缓存失败 dict 覆盖好缓存（[fallback-empty-write-corrupts-snapshots] 同款 bug）。


def test_is_empty_data_status_missing_dict为空():
    """data_status='missing' 的 dict 视为空（源断失败标记，不缓存覆盖好缓存）。"""
    assert fallback._is_empty({"top": [], "bottom": [], "total": 0, "data_status": "missing"}) is True
    assert fallback._is_empty({"data_status": "missing"}) is True
    assert fallback._is_empty({"top": [], "data_status": "missing", "extra": {}}) is True


def test_is_empty_data_status_ok_有实数据不为空():
    """data_status='ok'/'degraded' 伴实数据不算空（只有 'missing' 触发空判定）。"""
    assert fallback._is_empty({"top": [{"name": "白酒"}], "data_status": "ok"}) is False
    assert fallback._is_empty({"top": [{"name": "白酒"}], "data_status": "degraded"}) is False


def test_save_cache_data_status_missing不覆盖好缓存(isolated_cache):
    """失败标记 dict 不写缓存——好缓存保留。"""
    good = {"top": [{"name": "白酒", "change_pct": 2.5}], "bottom": [], "total": 1}
    fallback.save_cache("k", good)
    failure = {"top": [], "bottom": [], "total": 0, "data_status": "missing"}
    fallback.save_cache("k", failure)  # 限流失败 dict——不应覆盖
    assert fallback.load_cache("k") == good


def test_get_with_fallback_meta_失败dict不覆盖好缓存(isolated_cache):
    """get_with_fallback_meta：fetch 返 data_status='missing' dict → 不缓存，
    降级到好缓存（stale），不覆盖。模拟 industry_comparison 默认失败路径。
    """
    good = {"top": [{"name": "白酒", "change_pct": 2.5}], "bottom": [], "total": 1}
    fallback.save_cache("industry_comparison:20260901", good)
    failure = {"top": [], "bottom": [], "total": 0, "data_status": "missing"}

    data, meta = fallback.get_with_fallback_meta(
        "industry_comparison:20260901",
        lambda: failure,  # 源断返失败 dict（非 raise，fetch_ok=True）
        ttl=600,
        fallback_value={"top": [], "bottom": []},
    )

    # 好缓存未被覆盖
    assert fallback.load_cache("industry_comparison:20260901") == good
    # 降级到好缓存（stale）——非返失败 dict 当 live
    assert data == good
    assert meta["from_cache"] is True
    assert meta["is_stale"] is True
    assert meta["fetch_ok"] is True  # fetch_fn 未 raise（内部 swallow）


def test_get_with_fallback_meta_失败dict无缓存返fallback标missing(isolated_cache):
    """无好缓存时 fetch 返 data_status='missing' dict → 不缓存，返 fallback_value。"""
    failure = {"top": [], "bottom": [], "total": 0, "data_status": "missing"}
    data, meta = fallback.get_with_fallback_meta(
        "industry_comparison:20260901",
        lambda: failure,
        ttl=600,
        fallback_value={"top": [], "bottom": []},
    )
    # 无缓存 → 返 fallback_value（无 data_status，下游据 meta+空判 missing）
    assert data == {"top": [], "bottom": []}
    assert meta["from_cache"] is False
    assert meta["fetch_ok"] is True
    # 失败 dict 未写缓存
    assert fallback.load_cache("industry_comparison:20260901") is None
