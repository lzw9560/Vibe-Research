# -*- coding: utf-8 -*-
"""S008 T13a：C 组 tencent 消费者读侧迁 Quote 模型。

锁住：
- ``quote_from_tencent`` 映射出 T13a 新增字段（open/high/low/vol_ratio/pe_static）；
- ``bidding_monitor`` 拿到非 0 的 ``vol_ratio`` / ``open_premium``（plan-stage1 警告的
  丢字段风险——raw 有 vol_ratio/open 但初版 Quote 漏收，迁模型后不得再丢）；
- ``activity`` 输出 dict shape 不变（下游兼容）且 vol_ratio 非 None；
- 单位转换集中到 mapper：``market_cap == mcap_yi*1e8``、``turnover == amount_wan*1e4``，
  消费者不再写死换算。
"""
import asyncio

import astock
import bidding_monitor
import portfolio
from candidate_funnel.sources import activity
from data.mappers import quote_from_tencent


def _raw_quote(code: str = "600519") -> dict:
    """模拟 astock.tencent_quote 的全字段 raw 输出（单一事实源，含 T13a 新增字段）。"""
    return {code: {
        "name": "贵州茅台", "price": 1700.0, "last_close": 1680.0, "open": 1690.0,
        "high": 1720.0, "low": 1675.0,
        "change_pct": 2.3, "change_amt": 38.0, "amount_wan": 123456.0,
        "turnover_pct": 0.5, "pe_ttm": 30.0, "pe_static": 29.0, "amplitude_pct": 3.2,
        "mcap_yi": 21000.0, "float_mcap_yi": 20900.0, "pb": 10.0,
        "limit_up": 1870.0, "limit_down": 1530.0, "vol_ratio": 2.1,
    }}


# ── mapper 投射新字段 ────────────────────────────────────────────────────

def test_quote_from_tencent_maps_t13a_fields():
    q = quote_from_tencent("600519", _raw_quote()["600519"])
    # T13a 新增字段全部投射（不得漏收）
    assert q.open == 1690.0
    assert q.high == 1720.0
    assert q.low == 1675.0
    assert q.vol_ratio == 2.1
    assert q.pe_static == 29.0
    # 既有字段不变
    assert q.last_close == 1680.0
    assert q.price == 1700.0
    assert q.name == "贵州茅台"
    # 单位转换集中在 mapper
    assert q.market_cap == 21000.0 * 1e8      # 亿 -> 元
    assert q.turnover == 123456.0 * 1e4        # 万 -> 元
    assert q.turnover_rate == 0.5             # rename turnover_pct
    assert q.limit_up_price == 1870.0         # rename limit_up
    assert q.limit_down_price == 1530.0       # rename limit_down


# ── bidding_monitor：无字段丢失 ──────────────────────────────────────────

def test_bidding_monitor_no_field_loss(monkeypatch):
    """plan-stage1 警告：vol_ratio/open 丢字段会让 open_premium 分母塌成 0。迁模型后须非 0。"""
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: _raw_quote())
    snaps = asyncio.run(bidding_monitor.fetch_auction_snapshot_batch(["600519"]))
    assert len(snaps) == 1
    s = snaps[0]
    assert s["code"] == "600519"
    assert s["name"] == "贵州茅台"
    assert s["volume_ratio"] == 2.1                 # vol_ratio 不丢
    # open_premium = (open - last_close) / last_close = (1690-1680)/1680
    assert abs(s["open_premium"] - (1690.0 - 1680.0) / 1680.0) < 1e-9
    # 单位已是元（不再写死 *1e4 / *1e8）
    assert s["auction_amount"] == 123456.0 * 1e4    # turnover 元
    assert s["market_cap"] == 21000.0 * 1e8


def test_bidding_monitor_missing_quote_falls_back(monkeypatch):
    """行情接口异常时降级空快照，不中断监控链路。"""
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: (_ for _ in ()).throw(RuntimeError("net")))
    snaps = asyncio.run(bidding_monitor.fetch_auction_snapshot_batch(["600519"]))
    assert snaps[0]["volume_ratio"] == 0.0
    assert snaps[0]["open_premium"] == 0.0


# ── activity：输出 shape 兼容 + vol_ratio 不丢 ───────────────────────────

def test_activity_output_shape_unchanged(monkeypatch):
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: _raw_quote())
    # 未来日→tencent 路径（S044 R7 历史日走 kline 复算；本测试验 tencent-path shape 不变）
    out = activity.fetch_activity(["600519"], "2099-07-30")
    assert "600519" in out
    e = out["600519"]
    # 下游 candidate_funnel 依赖的 keys 仍在
    for k in ("name", "price", "change_pct", "turnover_pct", "vol_ratio",
              "amount_yi", "amplitude_pct", "limit_up", "limit_down"):
        assert k in e, f"输出 shape 破坏：缺 {k}"
    assert e["vol_ratio"] == 2.1                    # 不丢
    assert e["change_pct"] == 2.3                  # 死别名分支已删，直读模型
    assert e["turnover_pct"] == 0.5
    assert e["limit_up"] == 1870.0
    # amount_yi = turnover(元) / 1e8
    assert abs(e["amount_yi"] - 123456.0 * 1e4 / 1e8) < 1e-9
    # 无 missing（全字段取得）
    assert "missing" not in e


def test_activity_missing_fields_flagged(monkeypatch):
    """raw 缺字段时 missing 标记仍在（下游依赖此信号）。"""
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: {"600519": {"name": "X", "price": 1.0}})
    # 未来日→tencent 路径（同上；raw 缺 vol_ratio → missing 标记）
    out = activity.fetch_activity(["600519"], "2099-07-30")
    e = out["600519"]
    assert "missing" in e
    assert "vol_ratio" in e["missing"]


# ── portfolio：经模型读 name/price ───────────────────────────────────────

def test_portfolio_name_via_model(monkeypatch):
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: _raw_quote())
    # 共享可变 store：_save 写入后 _load 能读到（close_position 末尾会再调 get_portfolio 重读）
    store = {"holdings": [], "closed": [], "last_refresh": None}
    monkeypatch.setattr(portfolio, "_load", lambda: dict(store))  # 返回副本防内部 mutate 污染
    saved = {}
    def _capture_save(d):
        saved.update(d)
        store.update(d)
    monkeypatch.setattr(portfolio, "_save", _capture_save)
    # close_position 经模型取 name
    res = asyncio.run(portfolio.close_position("600519", "2026-07-30", 1700.0, 1.0, 1600.0))
    assert res["closed"][0]["name"] == "贵州茅台"


def test_value_funnel_name_of_via_model(monkeypatch):
    """value_funnel._name_of 经模型取 name（轻量调用，失败返空）。"""
    from value_funnel import funnel
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: _raw_quote())
    assert funnel._name_of("600519") == "贵州茅台"


def test_value_funnel_name_of_failure_returns_empty(monkeypatch):
    from value_funnel import funnel
    monkeypatch.setattr(astock, "tencent_quote", lambda codes: (_ for _ in ()).throw(RuntimeError("net")))
    assert funnel._name_of("600519") == ""
