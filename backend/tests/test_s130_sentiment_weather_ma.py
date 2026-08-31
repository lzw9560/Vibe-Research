# -*- coding: utf-8 -*-
"""S130 R3：exit-signal MA close 缺失过滤测试。

旧 bug：`b.get("close") or 0` 把缺失 close 当 0 → 均价被 0 拉低 → below_ma 误判。
修：过滤 None close（不纳入均价），closes 空 → ma_price=None（`if closes` 兜底已有）。

钉死三条契约（spec R3.3）：
① bars 含 1 个 None close → ma_price 只用非 None bar 算（不被 0 拉低）；
② 全 None close → ma_price=None（below_ma 不触发）；
③ 全有效 close → 原行为不变。
"""

import sys

import pytest
from fastapi.testclient import TestClient

_DATE = "2026-08-11"
_CODE = "000001"
_NAME = "测试股"


def _install_fakes(monkeypatch, *, bars, change_pct=1.0, price=12.0, open_price=12.0):
    """注入 fake workflow_state_repo + astock（端点内 lazy import，换 sys.modules 即生效）。"""
    class _FakeWsr:
        @staticmethod
        def list_states(date):
            return [{"code": _CODE, "name": _NAME, "status": "holding"}]

    class _FakeAstock:
        @staticmethod
        def tencent_quote(codes):
            # change_pct>0 → no_gap=False；交由 below_ma 分支决定触发与否
            return {_CODE: {"change_pct": change_pct, "open": open_price, "price": price}}

        @staticmethod
        def kline(code, *a, **k):
            return bars

    monkeypatch.setitem(sys.modules, "workflow_state_repo", _FakeWsr)
    monkeypatch.setitem(sys.modules, "astock", _FakeAstock)


def _signals(client):
    r = client.get(
        "/api/sentiment/weather/exit-signals",
        params={"date": _DATE},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["summary"]["total"] == 1
    return data["signals"][0]


class TestExitSignalMaNoneFilter:
    """R3.3：MA 计算对缺失 close 过滤而非 coerce 0。"""

    def test_one_none_close_excluded_from_ma(self, isolated_market_db, monkeypatch):
        """① 5 bar 中 1 个 close=None → ma 只用 4 个有效 bar（=10.0），不被 0 拉低到 8.0。

        Arrange: 最后 5 bar close = [10, 10, None, 10, 10]。
          新行为：closes=[10,10,10,10] → ma=10.0
          旧 bug(or 0)：closes=[10,10,0,10,10] → ma=8.0（None 被 coerce 成 0 拉低均价）
        设 price=12（>ma）→ below_ma=False，走非触发分支，仍回显 ma_price=10.0。
        """
        # Arrange
        import app as appmod
        bars = [
            {"close": 10.0},
            {"close": 10.0},
            {"close": None},   # 缺失：应过滤，不当 0
            {"close": 10.0},
            {"close": 10.0},
        ]
        _install_fakes(monkeypatch, bars=bars, change_pct=1.0, price=12.0)

        # Act
        client = TestClient(appmod.app)
        sig = _signals(client)

        # Assert：ma_price=10.0（非 8.0）证明 None 被过滤而非 coerce 0
        assert sig["ma_price"] == 10.0, sig
        assert sig["ma_price"] != 8.0  # 显式钉死：coerce-0 回归会在此失败
        assert sig["signal"] is None  # price 12 > ma 10 → 不触发
        assert sig["data_status"] == "ok"

    def test_all_none_close_yields_none_ma(self, isolated_market_db, monkeypatch):
        """② 全部 close=None → closes 空 → ma_price=None（`if closes` 兜底）→ below_ma 不触发。

        Arrange: 5 bar 全 None。
          新行为：closes=[] → ma_price=None → below_ma 短路 False（不触发强制离场）
        change_pct=1.0（高开）→ no_gap=False；below_ma=False → signal=None。
        """
        # Arrange
        import app as appmod
        bars = [{"close": None}] * 5
        _install_fakes(monkeypatch, bars=bars, change_pct=1.0, price=10.0)

        # Act
        client = TestClient(appmod.app)
        sig = _signals(client)

        # Assert：ma_price=None，below_ma 不触发
        assert sig["ma_price"] is None, sig
        assert sig["signal"] is None, sig
        assert sig["data_status"] == "ok"

    def test_all_valid_close_original_behavior(self, isolated_market_db, monkeypatch):
        """③ 全有效 close → 原行为不变：ma=11.0，price=10<11 → below_ma 触发强制离场。

        Arrange: 5 bar close=[10,11,12,11,11] → sum=55/5=11.0。
        change_pct=1.0（>0）→ no_gap=False；price=10<11 → below_ma=True → 触发。
        """
        # Arrange
        import app as appmod
        bars = [
            {"close": 10.0},
            {"close": 11.0},
            {"close": 12.0},
            {"close": 11.0},
            {"close": 11.0},
        ]
        _install_fakes(monkeypatch, bars=bars, change_pct=1.0, price=10.0)

        # Act
        client = TestClient(appmod.app)
        sig = _signals(client)

        # Assert：原行为——触发强制离场，ma_price=11.0
        assert sig["signal"] == "强制离场", sig
        assert sig["ma_price"] == 11.0, sig
        assert "开盘破5日均线" in sig["reason"], sig
        assert sig["data_status"] == "ok"
