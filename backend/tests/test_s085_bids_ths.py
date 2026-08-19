# -*- coding: utf-8 -*-
"""S085 D2（五档 bids）+ D4（同花顺防封）单测。

D2：东财 push2/push2delay 五档买卖盘。push2(实时)易封 → push2delay 优先 + 双 host 降级。
    字段映射（probe 验证，与 akshare stock_bid_ask_em 一致）：
    buy1=f19/f20 ... buy5=f11/f12；sell1=f39/f40 ... sell5=f31/f32；vol×100=股（akshare f32*100 证实）。
    _BID_FIELDS 用 akshare 原汁 fields 串（含 f120/f262/f530 高位字段触发五档自动返回，最小/空 fields 返空）。

D4：ths_limit_up_pool 裸 requests → _ths_get 限流（独立 ths breaker + 0.5s 间隔 + 抖动）。
    返 dict 从 12 → {code, reason, high_days}（全消费方只读这 3：
    market high_days / first_board_filter code+reason / sector_cycle reason / build_concept_map code）。
"""
from __future__ import annotations

import time

import pytest

from data.sources import eastmoney


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


# 构造一份完整五档 data（f57/f58/f43/f60 + 买1-5 + 卖1-5）
_BID_DATA = {
    "f57": "600519",   # code
    "f58": "贵州茅台",  # name
    "f43": 1700,       # latest
    "f60": 1680,       # prev_close
    # 买1→买5: f19/f20, f17/f18, f15/f16, f13/f14, f11/f12
    "f19": 1700.0, "f20": 10,   # 买1: price=1700, vol=10手 → 1000股
    "f17": 1699.0, "f18": 20,   # 买2
    "f15": 1698.0, "f16": 30,   # 买3
    "f13": 1697.0, "f14": 40,   # 买4
    "f11": 1696.0, "f12": 50,   # 买5
    # 卖1→卖5: f39/f40, f37/f38, f35/f36, f33/f34, f31/f32
    "f39": 1701.0, "f40": 15,  # 卖1
    "f37": 1702.0, "f38": 25,  # 卖2
    "f35": 1703.0, "f36": 35,  # 卖3
    "f33": 1704.0, "f34": 45,  # 卖4
    "f31": 1705.0, "f32": 55,  # 卖5
}


# ── D2: bids ──────────────────────────────────────────────────────────────

def test_bids_parses_five_levels(monkeypatch):
    """mock em_get 返构造五档 dict → buy/sell 各 5 档 + latest/prev_close/code/name。"""
    monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: _FakeResp({"data": _BID_DATA}))
    r = eastmoney.bids("600519")
    assert r["code"] == "600519"
    assert r["name"] == "贵州茅台"
    assert r["latest"] == 1700.0
    assert r["prev_close"] == 1680.0
    # 买 5 档，level 1→5，price 递减
    assert len(r["buy"]) == 5
    assert [b["level"] for b in r["buy"]] == [1, 2, 3, 4, 5]
    assert r["buy"][0] == {"level": 1, "price": 1700.0, "vol": 1000}   # 10*100
    assert r["buy"][4] == {"level": 5, "price": 1696.0, "vol": 5000}  # 50*100
    # 卖 5 档，level 1→5，price 递增
    assert len(r["sell"]) == 5
    assert [s["level"] for s in r["sell"]] == [1, 2, 3, 4, 5]
    assert r["sell"][0] == {"level": 1, "price": 1701.0, "vol": 1500}  # 15*100
    assert r["sell"][4] == {"level": 5, "price": 1705.0, "vol": 5500}  # 55*100


def test_bids_push2delay_preferred_first(monkeypatch):
    """push2delay 优先（首 host 成功即用，不降级 push2）。"""
    hosts = []

    def fake_em_get(url, *a, **k):
        hosts.append(url)
        return _FakeResp({"data": _BID_DATA})

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    r = eastmoney.bids("600519")
    assert len(hosts) == 1
    assert "push2delay.eastmoney.com" in hosts[0]
    assert r["buy"][0]["price"] == 1700.0


def test_bids_fallback_to_push2(monkeypatch):
    """push2delay 断 → 降级 push2 成功（双 host 降级）。"""
    hosts = []

    def fake_em_get(url, *a, **k):
        hosts.append(url)
        if "push2delay." in url:
            raise ConnectionError("push2delay down")
        return _FakeResp({"data": _BID_DATA})

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    r = eastmoney.bids("600519")
    assert len(hosts) == 2
    assert "push2delay." in hosts[0]
    assert "push2.eastmoney.com" in hosts[1]
    assert r["latest"] == 1700.0


def test_bids_empty_data_degrades(monkeypatch):
    """data 为 None / 空 → 空五档结构（不臆造）。"""
    monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: _FakeResp({"data": None}))
    r = eastmoney.bids("600519")
    assert r == {"code": "600519", "name": "", "latest": None,
                 "prev_close": None, "buy": [], "sell": []}


def test_bids_both_hosts_fail_degrades(monkeypatch):
    """双 host 都断 → 空五档（不抛，不臆造）。"""
    monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))
    r = eastmoney.bids("600519")
    assert r["buy"] == [] and r["sell"] == []
    assert r["code"] == "600519"


def test_bids_secid_market_code(monkeypatch):
    """6 开头 → secid=1.code（沪）；否则 0.code（深/创）。"""
    seen = []

    def fake_em_get(url, params=None, headers=None, timeout=10):
        seen.append(params["secid"])
        return _FakeResp({"data": _BID_DATA})

    monkeypatch.setattr(eastmoney, "em_get", fake_em_get)
    eastmoney.bids("600519")
    eastmoney.bids("000001")
    assert seen == ["1.600519", "0.000001"]


def test_bid_fields_contains_high_trigger_fields():
    """_BID_FIELDS 含 f120/f262/f530（触发五档自动返回的高位字段，勿自造精简集）+
    f57/f58/f43/f60（code/name/latest/prev_close）。

    买卖档位字段 f11-f40 **不在串中**——由高位字段触发服务器自动返回（probe 结论：
    最小/空 fields 返空，故用 akshare 原汁全串不精简）。
    """
    f = eastmoney._BID_FIELDS
    # 高位触发字段
    assert "f120" in f and "f262" in f and "f530" in f
    # code/name/latest/prev_close（解析直接读取）
    for fld in ("f57", "f58", "f43", "f60"):
        assert fld in f, f"_BID_FIELDS 缺 {fld}"


def test_bid_pairs_order():
    """买1→买5 / 卖1→卖5 顺序（akshare 口径）。"""
    assert eastmoney._BID_BUY_PAIRS[0] == ("f19", "f20")    # 买1
    assert eastmoney._BID_BUY_PAIRS[4] == ("f11", "f12")     # 买5
    assert eastmoney._BID_SELL_PAIRS[0] == ("f39", "f40")     # 卖1
    assert eastmoney._BID_SELL_PAIRS[4] == ("f31", "f32")     # 卖5


def test_bids_vol_none_when_missing(monkeypatch):
    """某档 vol 缺失（'-'）→ vol=None（不臆造 0）。"""
    data = dict(_BID_DATA)
    data["f20"] = "-"  # 买1 量缺失
    monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: _FakeResp({"data": data}))
    r = eastmoney.bids("600519")
    assert r["buy"][0]["vol"] is None
    assert r["buy"][0]["price"] == 1700.0


# ── D4: _ths_get + ths_limit_up_pool ──────────────────────────────────────

class _FakeBreaker:
    def __init__(self):
        self.allowed = 0
        self.successes = 0
        self.failures = 0

    def allow_request(self):
        self.allowed += 1
        return True

    def record_success(self):
        self.successes += 1

    def record_failure(self):
        self.failures += 1


class _FakeReqResp:
    def json(self):
        return {"data": {"info": []}}


def test_ths_get_uses_ths_breaker_and_records_success(monkeypatch):
    """_ths_get 走 get_breaker('ths')（独立计数）+ 成功记 success。"""
    breaker = _FakeBreaker()
    monkeypatch.setattr(eastmoney, "get_breaker", lambda name: breaker)
    monkeypatch.setattr(eastmoney.requests, "get", lambda *a, **k: _FakeReqResp())
    # 避免真实 sleep：把上次调用时间设到很久以前（wait<0 不 sleep）
    eastmoney._ths_last_call[0] = 0.0
    r = eastmoney._ths_get("http://x", params={}, headers={"User-Agent": "ua"})
    assert breaker.allowed == 1
    assert breaker.successes == 1
    assert breaker.failures == 0
    assert r is not None


def test_ths_get_records_failure_and_reraises(monkeypatch):
    """_ths_get 请求失败 → 记 failure 并 re-raise（消费方已有 try/except 兜 []）。"""
    breaker = _FakeBreaker()
    monkeypatch.setattr(eastmoney, "get_breaker", lambda name: breaker)

    def _boom(*a, **k):
        raise ConnectionError("ths down")

    monkeypatch.setattr(eastmoney.requests, "get", _boom)
    eastmoney._ths_last_call[0] = 0.0
    with pytest.raises(ConnectionError):
        eastmoney._ths_get("http://x", params={}, headers={})
    assert breaker.failures == 1
    assert breaker.successes == 0


def test_ths_get_passes_ua_header(monkeypatch):
    """_ths_get 复用 UA 作 User-Agent（同花顺防封基础）。"""
    monkeypatch.setattr(eastmoney, "get_breaker", lambda name: _FakeBreaker())
    captured = {}
    monkeypatch.setattr(eastmoney.requests, "get",
                        lambda url, params=None, headers=None, timeout=10:
                        captured.update(url=url, headers=headers) or _FakeReqResp())
    eastmoney._ths_last_call[0] = 0.0
    eastmoney._ths_get("http://x", params={}, headers={"User-Agent": eastmoney.UA})
    assert captured["headers"]["User-Agent"] == eastmoney.UA


def test_ths_get_enforces_min_interval(monkeypatch):
    """上次调用刚发生 → wait>0 → time.sleep 被调（最小间隔防封节流）。"""
    monkeypatch.setattr(eastmoney, "get_breaker", lambda name: _FakeBreaker())
    monkeypatch.setattr(eastmoney.random, "uniform", lambda a, b: 0.0)
    sleeps = []
    monkeypatch.setattr(eastmoney.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(eastmoney.requests, "get", lambda *a, **k: _FakeReqResp())
    eastmoney._ths_last_call[0] = time.time()  # 刚调过 → wait≈0.5
    eastmoney._ths_get("http://x", params={}, headers={})
    assert sleeps, "最小间隔未触发 sleep"
    assert 0 < sleeps[0] <= eastmoney._THS_MIN_INTERVAL + 0.01


def test_ths_limit_up_pool_uses_ths_get_not_raw_requests(monkeypatch):
    """ths_limit_up_pool 走 _ths_get（限流），不裸调 requests.get。"""
    ths_calls = []
    raw_get_calls = []

    def fake_ths_get(*a, **k):
        ths_calls.append(1)
        return _FakeResp({"data": {"info": []}})

    monkeypatch.setattr(eastmoney, "_ths_get", fake_ths_get)
    orig_get = eastmoney.requests.get
    monkeypatch.setattr(eastmoney.requests, "get",
                        lambda *a, **k: raw_get_calls.append(1) or _FakeReqResp())
    eastmoney.ths_limit_up_pool("20260819")
    assert len(ths_calls) == 1
    assert raw_get_calls == [], "ths_limit_up_pool 不应裸调 requests.get"


def test_ths_limit_up_pool_returns_three_fields(monkeypatch):
    """返 dict 从 12 → {code, reason, high_days}（9 死字段精简）。"""
    raw = {"data": {"info": [
        {"code": "600519", "reason_type": "白酒+消费升级", "high_days": "3天3板",
         "name": "贵州茅台", "latest": 1700, "limit_up_suc_rate": 0.9},
    ]}}
    monkeypatch.setattr(eastmoney, "_ths_get", lambda *a, **k: _FakeResp(raw))
    out = eastmoney.ths_limit_up_pool("20260819")
    assert len(out) == 1
    assert out[0] == {"code": "600519", "reason": "白酒+消费升级", "high_days": "3天3板"}
    # 9 死字段已精简
    for dead in ("name", "price", "pct", "board_type", "seal_rate",
                 "break_times", "seal_amount", "first_time", "is_again"):
        assert dead not in out[0], f"死字段 {dead} 未精简"


def test_ths_limit_up_pool_failure_returns_empty(monkeypatch):
    """_ths_get 抛 → ths_limit_up_pool 兜 []（不崩主流程）。"""
    def _raise(*a, **k):
        raise ConnectionError("ths down")

    monkeypatch.setattr(eastmoney, "_ths_get", _raise)
    assert eastmoney.ths_limit_up_pool("20260819") == []


def test_ths_limit_up_pool_empty_info(monkeypatch):
    """info 为空 → []。"""
    monkeypatch.setattr(eastmoney, "_ths_get",
                        lambda *a, **k: _FakeResp({"data": {"info": []}}))
    assert eastmoney.ths_limit_up_pool("20260819") == []
