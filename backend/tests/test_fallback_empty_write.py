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
