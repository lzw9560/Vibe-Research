# -*- coding: utf-8 -*-
"""S131 R4/R5 caller-side 接线测试——first_board_filter / first_board_market_env /
daily_review / extreme_market_detector。

S131 在 eastmoney.py 加了 raise_on_failure opt-in（R4 concept_blocks / R5 em_zt_topic_pool），
但 opt-in 机制本身不防谎——caller 不传 True 时源断仍被吞 [] 当合法空。本测钉死
**caller 侧接线**（4 文件 ONLY）：

- R5 first_board_filter：fetch_zt_pool / score_dim1_sector / score_dim_sector_link
  传 raise_on_failure=True + try/except 兜底（源断→[]/50.0/-1.0 降级）。
- R4 first_board_filter：extract_sector（concept_blocks）传 raise_on_failure=True
  + try/except 兜底（源断→{}）。
- R5 first_board_market_env：fetch_zt_count_compare T-1/T日 传 raise_on_failure=True
  + try/except 兜底（源断→zt_count_t1=0/zt_count_t=None）。
- R5 daily_review：generate_review 4 池 传 raise_on_failure=True
  + 逐池 try/except 兜底（源断→空池 + warning log）。
- R5 extreme_market_detector：lambda 内 em_zt_topic_pool 传 raise_on_failure=True
  → 源断 raise → get_with_fallback_meta fetch_ok=False → _resolve_pool_provenance 标 missing。

所有测试 mock caller 侧函数（astock.em_zt_topic_pool / concept_blocks / eastmoney.em_get），
不联网。对齐 test_s131_market_caller_wiring _em_boom 范式。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import fallback  # noqa: E402
from data.sources import eastmoney  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────

def _zt_item():
    """一条涨停池原始行（zt_pool_item_from_dict 可解析的最小字段集）。"""
    return {"c": "600001", "n": "测试股", "lbc": 1, "fbt": 93000, "zbc": 0,
            "zje": 10.0, "zdp": 10.0, "hybk": "半导体"}


def _em_boom(endpoint, date, sort="fbt:asc", *, raise_on_failure=False, **kw):
    """模拟 em 源断：raise_on_failure=True 时 raise，默认返 []（向后兼容）。"""
    if raise_on_failure:
        raise ConnectionError("em_get 源断")
    return []


def _em_ok(endpoint, date, sort="fbt:asc", *, raise_on_failure=False, **kw):
    """模拟 em 正常：zt 池返数据，其余池返空（合法空=无异常）。"""
    if endpoint == "getTopicZTPool":
        return [_zt_item()]
    return []


def _concept_boom(code, *, raise_on_failure=False, **kw):
    """模拟 concept_blocks 源断。"""
    if raise_on_failure:
        raise ConnectionError("em_get 源断")
    return {"total": 0, "boards": [], "concept_tags": []}


def _concept_ok(code, *, raise_on_failure=False, **kw):
    """模拟 concept_blocks 正常。"""
    return {"total": 1, "boards": [{"name": "白酒", "code": "BK0477",
            "change_pct": 2.0, "lead_stock": "贵州茅台"}], "concept_tags": ["白酒"]}


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch):
    """每个用例用独立缓存目录 + 干净内存缓存（对齐 test_data_honesty 范式）。"""
    monkeypatch.setattr(fallback, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(fallback, "_MEM_CACHE", {})
    eastmoney._ztb_cache.clear()
    return tmp_path


# ===========================================================================
# R5 first_board_filter — fetch_zt_pool
# ===========================================================================

def test_r5_fbf_fetch_zt_pool_passes_raise_on_failure(monkeypatch):
    """R5 caller：fetch_zt_pool 传 raise_on_failure=True。"""
    from strategies import first_board_filter as fbf
    captured: dict = {}

    def _spy(endpoint, date, sort="fbt:asc", **kw):
        captured.update(kw)
        return [_zt_item()]

    monkeypatch.setattr(fbf, "em_zt_topic_pool", _spy)
    fbf.fetch_zt_pool("20260818")
    assert captured.get("raise_on_failure") is True


def test_r5_fbf_fetch_zt_pool_source_fail_returns_empty(monkeypatch):
    """R5 caller：源断 raise → try/except 兜底 → []（非吞 [] 当合法空）。"""
    from strategies import first_board_filter as fbf
    monkeypatch.setattr(fbf, "em_zt_topic_pool", _em_boom)
    result = fbf.fetch_zt_pool("20260818")
    assert result == []


def test_r5_fbf_fetch_zt_pool_normal_returns_data(monkeypatch):
    """R5 caller：正常 → 返数据（向后兼容）。"""
    from strategies import first_board_filter as fbf
    monkeypatch.setattr(fbf, "em_zt_topic_pool", _em_ok)
    result = fbf.fetch_zt_pool("20260818")
    assert len(result) == 1
    assert result[0]["c"] == "600001"


# ===========================================================================
# R4 first_board_filter — extract_sector (concept_blocks)
# ===========================================================================

def test_r4_fbf_extract_sector_passes_raise_on_failure(monkeypatch):
    """R4 caller：extract_sector 传 concept_blocks(raise_on_failure=True)。"""
    from strategies import first_board_filter as fbf
    captured: dict = {}

    def _spy(code, **kw):
        captured.update(kw)
        return _concept_ok(code)

    monkeypatch.setattr(fbf, "concept_blocks", _spy)
    fbf.extract_sector("600001")
    assert captured.get("raise_on_failure") is True


def test_r4_fbf_extract_sector_source_fail_returns_empty(monkeypatch):
    """R4 caller：concept_blocks 源断 raise → try/except → {}（非空 dict 当合法空）。"""
    from strategies import first_board_filter as fbf
    monkeypatch.setattr(fbf, "concept_blocks", _concept_boom)
    result = fbf.extract_sector("600001")
    assert result == {}


def test_r4_fbf_extract_sector_normal_returns_data(monkeypatch):
    """R4 caller：正常 → 返板块数据（向后兼容）。"""
    from strategies import first_board_filter as fbf
    monkeypatch.setattr(fbf, "concept_blocks", _concept_ok)
    result = fbf.extract_sector("600001")
    assert "boards" in result
    assert result["concept_tags"] == ["白酒"]


# ===========================================================================
# R5 first_board_filter — score_dim1_sector
# ===========================================================================

def test_r5_fbf_score_dim1_passes_raise_on_failure(monkeypatch):
    """R5 caller：score_dim1_sector 传 raise_on_failure=True。"""
    from strategies import first_board_filter as fbf
    captured: dict = {}

    def _spy(endpoint, date, sort="fbt:asc", **kw):
        captured.update(kw)
        return [_zt_item()]

    monkeypatch.setattr(fbf, "em_zt_topic_pool", _spy)
    candidate = {"code": "600001", "industry": "半导体"}
    fbf.score_dim1_sector(candidate, "20260818")
    assert captured.get("raise_on_failure") is True


def test_r5_fbf_score_dim1_source_fail_returns_50(monkeypatch):
    """R5 caller：源断 raise → try/except → 50.0 降级（非吞 [] 算零联动）。"""
    from strategies import first_board_filter as fbf
    monkeypatch.setattr(fbf, "em_zt_topic_pool", _em_boom)
    candidate = {"code": "600001", "industry": "半导体"}
    score, raw = fbf.score_dim1_sector(candidate, "20260818")
    assert score == 50.0


def test_r5_fbf_score_dim1_normal_returns_score(monkeypatch):
    """R5 caller：正常 → 返评分（向后兼容）。"""
    from strategies import first_board_filter as fbf
    monkeypatch.setattr(fbf, "em_zt_topic_pool", _em_ok)
    candidate = {"code": "600001", "industry": "半导体"}
    score, raw = fbf.score_dim1_sector(candidate, "20260818")
    assert score > 0
    assert raw.get("sector_zt_count") == 1


# ===========================================================================
# R5 first_board_filter — score_dim_sector_link
# ===========================================================================

def test_r5_fbf_score_dim_sector_link_passes_raise_on_failure(monkeypatch):
    """R5 caller：score_dim_sector_link 传 raise_on_failure=True。"""
    from strategies import first_board_filter as fbf
    captured: dict = {}

    def _spy(endpoint, date, sort="fbt:asc", **kw):
        captured.update(kw)
        return [_zt_item()]

    monkeypatch.setattr(fbf, "em_zt_topic_pool", _spy)
    candidate = {"code": "600001", "industry": "半导体"}
    fbf.score_dim_sector_link(candidate, "20260818")
    assert captured.get("raise_on_failure") is True


def test_r5_fbf_score_dim_sector_link_source_fail_returns_neg1(monkeypatch):
    """R5 caller：源断 raise → try/except → -1.0（数据缺失不参与加权）。"""
    from strategies import first_board_filter as fbf
    monkeypatch.setattr(fbf, "em_zt_topic_pool", _em_boom)
    candidate = {"code": "600001", "industry": "半导体"}
    score, raw = fbf.score_dim_sector_link(candidate, "20260818")
    assert score == -1.0


def test_r5_fbf_score_dim_sector_link_normal_returns_score(monkeypatch):
    """R5 caller：正常 → 返评分（向后兼容）。"""
    from strategies import first_board_filter as fbf
    monkeypatch.setattr(fbf, "em_zt_topic_pool", _em_ok)
    candidate = {"code": "600001", "industry": "半导体"}
    score, raw = fbf.score_dim_sector_link(candidate, "20260818")
    assert score > 0
    assert raw.get("sector_zt_count") == 1


# ===========================================================================
# R5 first_board_market_env — fetch_zt_count_compare
# ===========================================================================

def test_r5_fbme_fetch_zt_compare_passes_raise_on_failure(monkeypatch):
    """R5 caller：fetch_zt_count_compare T-1/T日均传 raise_on_failure=True。"""
    from strategies import first_board_market_env as fbme
    from datetime import date as _date
    captured: list = []

    def _spy(endpoint, date, sort="fbt:asc", **kw):
        captured.append(kw.get("raise_on_failure"))
        return [_zt_item()] if endpoint == "getTopicZTPool" else []

    monkeypatch.setattr(fbme, "em_zt_topic_pool", _spy)
    monkeypatch.setattr(fbme, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(fbme, "prev_trading_date",
                        lambda _d: _date(2026, 8, 17))
    fbme.fetch_zt_count_compare("20260818")
    # 至少两次调用（T-1 + T日），均传 True
    assert len(captured) >= 2
    assert all(v is True for v in captured)


def test_r5_fbme_fetch_zt_compare_source_fail_degrades(monkeypatch):
    """R5 caller：源断 raise → try/except → zt_count_t1=0, zt_count_t=None。"""
    from strategies import first_board_market_env as fbme
    from datetime import date as _date
    monkeypatch.setattr(fbme, "em_zt_topic_pool", _em_boom)
    monkeypatch.setattr(fbme, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(fbme, "prev_trading_date",
                        lambda _d: _date(2026, 8, 17))
    result = fbme.fetch_zt_count_compare("20260818")
    assert result["zt_count_t1"] == 0
    assert result["zt_count_t"] is None
    assert result["ratio"] is None


def test_r5_fbme_fetch_zt_compare_normal_returns_data(monkeypatch):
    """R5 caller：正常 → 返涨停数（向后兼容）。"""
    from strategies import first_board_market_env as fbme
    from datetime import date as _date
    monkeypatch.setattr(fbme, "em_zt_topic_pool", _em_ok)
    monkeypatch.setattr(fbme, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(fbme, "prev_trading_date",
                        lambda _d: _date(2026, 8, 17))
    result = fbme.fetch_zt_count_compare("20260818")
    assert result["zt_count_t1"] == 1


# ===========================================================================
# R5 daily_review — generate_review
# ===========================================================================

def test_r5_daily_review_passes_raise_on_failure(monkeypatch):
    """R5 caller：generate_review 4 池均传 raise_on_failure=True。

    其他模块内部（limitup_sti/auction_screener）可能也调 em_zt_topic_pool 但不传
    raise_on_failure（非本 spec scope），只验证 generate_review 的 4 池接线。
    """
    import astock
    import daily_review
    import market
    captured: list = []

    def _spy(endpoint, date, sort="fbt:asc", **kw):
        captured.append((endpoint, kw.get("raise_on_failure")))
        return [_zt_item()]

    monkeypatch.setattr(daily_review, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(astock, "em_zt_topic_pool", _spy)
    monkeypatch.setattr(market, "_sentiment", lambda *a, **k: {"up": 100, "down": 50})
    reviewer = daily_review.DailyReviewer()
    reviewer.generate_review("2026-08-28")
    # 4 池（zt/dt/zb/yzt）均传 raise_on_failure=True（其他模块内部调用不传，
    # 非 generate_review 的接线 scope）
    wired = [(ep, rof) for ep, rof in captured if rof is True]
    wired_endpoints = {ep for ep, _ in wired}
    assert "getTopicZTPool" in wired_endpoints
    assert "getTopicDTPool" in wired_endpoints
    assert "getTopicZBPool" in wired_endpoints
    assert "getYesterdayZTPool" in wired_endpoints
    assert len(wired) >= 4


def test_r5_daily_review_source_fail_pools_empty(monkeypatch):
    """R5 caller：源断 raise → 逐池 try/except → 空池 + 报告不崩。"""
    import astock
    import daily_review
    import market
    monkeypatch.setattr(daily_review, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(astock, "em_zt_topic_pool", _em_boom)
    monkeypatch.setattr(market, "_sentiment", lambda *a, **k: {"up": 100, "down": 50})
    reviewer = daily_review.DailyReviewer()
    report = reviewer.generate_review("2026-08-28")
    # 源断 → 所有池空 → 计数为 0（非吞 [] 当合法空——有 warning log）
    assert report.zt_total == 0
    assert report.dt_total == 0
    assert report.zb_total == 0


def test_r5_daily_review_normal_returns_data(monkeypatch):
    """R5 caller：正常 → 返涨停数 > 0（向后兼容）。"""
    import astock
    import daily_review
    import market
    monkeypatch.setattr(daily_review, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(astock, "em_zt_topic_pool", _em_ok)
    monkeypatch.setattr(market, "_sentiment", lambda *a, **k: {"up": 100, "down": 50})
    reviewer = daily_review.DailyReviewer()
    report = reviewer.generate_review("2026-08-28")
    assert report.zt_total == 1


# ===========================================================================
# R5 extreme_market_detector — lambda 内 raise_on_failure=True
# ===========================================================================

def test_r5_emd_lambda_passes_raise_on_failure(monkeypatch):
    """R5 caller：extreme_market_detector lambda 内 em_zt_topic_pool 传 raise_on_failure=True。

    无接线时 lambda 不传 raise_on_failure → em_zt_topic_pool 源断返 []（swallow）→
    fetch_ok=True（wrong）；接线后传 True → 源断 raise → fetch_ok=False（correct）。
    """
    import astock
    import extreme_market_detector as emd
    captured: list = []

    def _spy(endpoint, date, sort="fbt:asc", **kw):
        captured.append(kw.get("raise_on_failure"))
        return [_zt_item()]

    monkeypatch.setattr(emd, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(astock, "em_zt_topic_pool", _spy)
    asyncio.run(emd.detect_extreme_market("2026-08-28"))
    # 3 池调用（zt/dt/zb），均传 True
    assert len(captured) == 3
    assert all(v is True for v in captured)


def test_r5_emd_source_fail_em_get_marks_missing(isolated_cache, monkeypatch):
    """R5 caller：em_get 源断 → em_zt_topic_pool(raise_on_failure=True) re-raise
    → lambda raise → get_with_fallback_meta fetch_ok=False → _resolve_pool_provenance
    标 missing（非"正常"平静市）。

    对齐 test_data_honesty:test_extreme_market_pool_source_break_marks_missing_not_normal，
    但本测走真实 em_zt_topic_pool 代码路径（mock em_get 而非 mock em_zt_topic_pool），
    验证 raise_on_failure=True 确实在 lambda 内传递生效。
    """
    import extreme_market_detector as emd

    monkeypatch.setattr(emd, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(eastmoney, "em_get", _em_get_boom)
    eastmoney._ztb_cache.clear()

    signal = asyncio.run(emd.detect_extreme_market("2026-08-28"))
    assert signal is not None
    assert signal.data_status == "missing"
    assert signal.signal_type != "正常"
    assert signal.is_extreme is False


def test_r5_emd_normal_path_returns_ok(isolated_cache, monkeypatch):
    """R5 caller：正常路径 → data_status='ok'（向后兼容，raise_on_failure=True 不破合法空）。

    em_get 返正常 JSON（zt 池有数据）→ em_zt_topic_pool(raise_on_failure=True) 返数据
    （无 raise，因为源正常）→ lambda 返非空 dict → get_with_fallback_meta fetch_ok=True
    → _resolve_pool_provenance 标 ok。
    """
    import extreme_market_detector as emd

    monkeypatch.setattr(emd, "is_trading_day", lambda _d: True)
    monkeypatch.setattr(eastmoney, "em_get", _em_get_ok)
    eastmoney._ztb_cache.clear()

    signal = asyncio.run(emd.detect_extreme_market("2026-08-28"))
    assert signal is not None
    assert signal.data_status == "ok"
    assert signal.zt_count > 0


# ── em_get mock helpers（走真实 em_zt_topic_pool 代码路径）─────────────────

def _em_get_boom(*a, **k):
    """模拟 em_get 源断（断连/限流/JSON 错统一 raise）。"""
    raise ConnectionError("em_get 源断")


def _em_get_ok(*a, **k):
    """模拟 em_get 正常返 JSON（zt 池有数据，其余池合法空）。"""
    url = a[0] if a else k.get("url", "")
    if "getTopicZTPool" in url:
        return _MockResp({"data": {"pool": [_zt_item()]}})
    if "getTopicDTPool" in url:
        return _MockResp({"data": {"pool": []}})
    if "getTopicZBPool" in url:
        return _MockResp({"data": {"pool": []}})
    return _MockResp({"data": {"pool": []}})


class _MockResp:
    """最小 requests.Response mock（.json() 返固定 dict）。"""
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data
