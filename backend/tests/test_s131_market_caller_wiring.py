# -*- coding: utf-8 -*-
"""S131 R5/R6/R7 承重 caller 接线测试——market.py 侧。

S131 在 eastmoney.py 加了 raise_on_failure opt-in（R5 em_zt_topic_pool /
R6 market_turnover_rank / R7 sector_fund_flow），但 opt-in 机制本身不防谎——
caller 不传 True 时源断仍被吞 [] 当合法空。本测钉死 **caller 侧接线**：

- R5 market._emotion：em 源断 → data_status='missing'（非合法空 {}）；
  metrics 池源断 → data_status='degraded'（非 ok 当权威）；正常 → 'ok'（不破）。
- R6 market.get_turnover_top：源断 → data_status='missing'（非合法空 []）。
- R7 market.get_overview：源断 → sectors_status='missing'（非合法空 []）。

所有测试 mock caller 侧函数（astock.em_zt_topic_pool / market_turnover_rank /
sector_fund_flow），不联网。对齐 test_s130_market_lianban _patch_guards 范式。
"""
from __future__ import annotations

import os
import sys

import astock
import market

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import vr_paths  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────

def _patch_guards(monkeypatch):
    """bypass 交易日历/盘前守卫 + _sentiment 网络取数，让 _emotion 跑到 em_zt_topic_pool。"""
    monkeypatch.setattr(vr_paths, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(market, "_sentiment", lambda _date=None: {})
    monkeypatch.setattr(astock, "ths_limit_up_pool", lambda *a, **k: [])


def _zt_item():
    """一条涨停池原始行（最小可用：code/name/lbc/p/zdp/amount/ltsz/hybk）。"""
    return {"c": "600001", "n": "甲", "lbc": 2, "p": 10000, "zdp": 10.0,
            "amount": 5e8, "ltsz": 1e9, "hybk": "X"}


def _em_boom(endpoint, date, sort="fbt:asc", raise_on_failure=False):
    """模拟 em 源断：raise_on_failure=True 时 raise，默认返 []（向后兼容）。"""
    if raise_on_failure:
        raise ConnectionError("em_get 源断")
    return []


def _em_zt_ok_rest_boom(endpoint, date, sort="fbt:asc", raise_on_failure=False):
    """zt 池正常，zb/dt/yzt 源断（raise_on_failure=True 时 raise）。"""
    if endpoint == "getTopicZTPool":
        return [_zt_item()]
    if raise_on_failure:
        raise ConnectionError("em_get 源断")
    return []


def _em_all_ok(endpoint, date, sort="fbt:asc", raise_on_failure=False):
    """全部池正常：zt 返数据，zb/dt/yzt 返空（合法空=无异常）。"""
    if endpoint == "getTopicZTPool":
        return [_zt_item()]
    return []  # 合法空（非源断）


# ===========================================================================
# R5 market._emotion — em 源断 → data_status='missing'
# ===========================================================================

def test_r5_emotion_source_down_auto_locate_returns_missing(monkeypatch):
    """R5 caller：date=None（自动定位）em 全源断 → data_status='missing'。

    无接线时 em_zt_topic_pool 源断返 [] → 循环耗尽 → return {}（合法空=撒谎"无数据"）；
    接线后 raise_on_failure=True → catch → em_source_down=True → ths 也空 →
    return {data_status:'missing'}（源断不伪装"无数据"）。
    """
    _patch_guards(monkeypatch)
    monkeypatch.setattr(astock, "em_zt_topic_pool", _em_boom)
    market._CACHE.clear()
    out = market._emotion(None)
    assert out.get("data_status") == "missing"


def test_r5_emotion_source_down_explicit_date_returns_missing(monkeypatch):
    """R5 caller：date='2026-08-28'（显式交易日）em 源断 → data_status='missing'。

    无接线时 zt=[] → return {}（合法空=撒谎"该日无涨停"）；
    接线后 raise_on_failure=True → catch → em_source_down=True →
    return {data_status:'missing'}（源断不伪装"该日无涨停"）。
    """
    _patch_guards(monkeypatch)
    monkeypatch.setattr(astock, "em_zt_topic_pool", _em_boom)
    market._CACHE.clear()
    out = market._emotion("2026-08-28")
    assert out.get("data_status") == "missing"


# ===========================================================================
# R5 market._emotion — metrics 池源断 → data_status='degraded'
# ===========================================================================

def test_r5_emotion_metrics_source_down_returns_degraded(monkeypatch):
    """R5 caller：zt 池正常但 zb/dt/yzt 源断 → data_status='degraded'。

    无接线时 zb/dt/yzt 源断返 [] → zb_count=0/dt_count=0/yzt_count=0 →
    break_rate/promotion_rate 用 0 算（数据伪装完整）→ data_source='eastmoney'（当权威）；
    接线后 raise_on_failure=True → catch → pools_status='degraded' →
    data_status='degraded'（metrics 部分源断不伪装 ok 权威）。
    """
    _patch_guards(monkeypatch)
    monkeypatch.setattr(astock, "em_zt_topic_pool", _em_zt_ok_rest_boom)
    market._CACHE.clear()
    out = market._emotion("2026-08-28")
    assert out.get("data_status") == "degraded"
    # zt 池正常 → zt_count 非零（核心数据在）
    assert out.get("zt_count") == 1
    # zb/dt/yzt 源断 → count=0（降级标记，非真实 0）
    assert out.get("zb_count") == 0
    assert out.get("dt_count") == 0


# ===========================================================================
# R5 market._emotion — 正常路径 → data_status='ok'（不破）
# ===========================================================================

def test_r5_emotion_normal_path_returns_ok(monkeypatch):
    """R5 caller：全部池正常（合法空=无异常）→ data_status='ok'（向后兼容）。

    zb/dt/yzt 返空但无异常（合法空）→ pools_status='ok' → data_status='ok'。
    非源断不标 degraded（区分"合法空"vs"源断"）。
    """
    _patch_guards(monkeypatch)
    monkeypatch.setattr(astock, "em_zt_topic_pool", _em_all_ok)
    market._CACHE.clear()
    out = market._emotion("2026-08-28")
    assert out.get("data_status") == "ok"
    assert out.get("zt_count") == 1


# ===========================================================================
# R6 market.get_turnover_top — 源断 → data_status='missing'
# ===========================================================================

def test_r6_get_turnover_top_source_down_returns_missing(monkeypatch):
    """R6 caller：market_turnover_rank 双 host 断 → data_status='missing'。

    无接线时返 [] → {stocks:[]}（合法空=撒谎"无成交额榜"）；
    接线后 raise_on_failure=True → catch → data_status='missing'。
    """
    def _boom(n=20, raise_on_failure=False):
        if raise_on_failure:
            raise ConnectionError("em_get 源断")
        return []

    monkeypatch.setattr(astock, "market_turnover_rank", _boom)
    market._CACHE.clear()
    out = market.get_turnover_top()
    assert out["data_status"] == "missing"
    assert out["stocks"] == []


def test_r6_get_turnover_top_normal_returns_ok(monkeypatch):
    """R6 caller：正常返数据 → data_status='ok'（向后兼容）。"""
    fake = [{"code": "600001", "name": "甲", "price": 10.0, "amount": 5e8}]
    monkeypatch.setattr(astock, "market_turnover_rank",
                        lambda n=20, raise_on_failure=False: fake)
    market._CACHE.clear()
    out = market.get_turnover_top()
    assert out["data_status"] == "ok"
    assert len(out["stocks"]) == 1


# ===========================================================================
# R7 market.get_overview — 源断 → sectors_status='missing'
# ===========================================================================

def test_r7_get_overview_source_down_returns_missing(monkeypatch):
    """R7 caller：sector_fund_flow 双 host 断 → sectors_status='missing'。

    无接线时 _sectors 返 [] → {sectors:[]}（合法空=撒谎"无板块资金流"）；
    接线后 raise_on_failure=True → catch → sectors_status='missing'。
    """
    def _boom(raise_on_failure=False):
        if raise_on_failure:
            raise ConnectionError("em_get 源断")
        return []

    monkeypatch.setattr("data.sources.eastmoney.sector_fund_flow", _boom)
    monkeypatch.setattr(market, "_sentiment", lambda *a, **k: {"up": 100, "down": 50})
    market._CACHE.clear()
    out = market.get_overview()
    assert out["sectors_status"] == "missing"
    assert out["sectors"] == []


def test_r7_get_overview_normal_returns_ok(monkeypatch):
    """R7 caller：正常返数据 → sectors_status='ok'（向后兼容）。"""
    fake = [{"name": "半导体", "pct": 2.0, "net": 5.0, "firms": 100}]
    monkeypatch.setattr("data.sources.eastmoney.sector_fund_flow",
                        lambda raise_on_failure=False: fake)
    monkeypatch.setattr(market, "_sentiment", lambda *a, **k: {"up": 100, "down": 50})
    market._CACHE.clear()
    out = market.get_overview()
    assert out["sectors_status"] == "ok"
    assert len(out["sectors"]) == 1
