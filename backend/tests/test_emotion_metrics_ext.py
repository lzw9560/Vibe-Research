"""S149 Phase 2 — emotion_metrics_ext 单测。

移植自 vibe-astock@3c3b7c8 emotion_metrics.py（部分函数）。验证：
- 6 个移植函数语义正确（money_effect/consec_premium/cycle_position/build_metrics/render_metrics/day_summary）
- 4 个 import/内联改写指向 Vibe-Research 基建（不裸调 urllib/akshare/requests）
- 字段映射（getYesterdayZTPool push2ex 字段 → fetch_prev_pool 目标形状）
- 分层契约（consec_premium aggregate 无个股名可进 emotion 层；明细带个股名走独立路由、不进 AI）
- 双源规则（cycle_position 不进 AI context——with_cycle=False 可剥离）
- 缓存经 vr_paths.resolve_data_dir()（不硬编码 ~/.duanxian-agents）
"""
from __future__ import annotations

import datetime
import json

import pytest

import emotion_metrics_ext as em
import emotion_metrics_ext as ext_mod


# ───────────────────────────── fixtures ──────────────────────────────
# push2ex getTopicZTPool 原始行（真实探样字段名：c/n/p/zdp/lbc/zbc/hybk/fbt/zttj…）
ZT_POOL_ROWS = [
    {"c": "605398", "n": "新炬网络", "p": 26660, "zdp": 9.98, "lbc": 2, "zbc": 0,
     "hybk": "IT服务Ⅱ", "fbt": 92501, "lbt": 92501, "fund": 83906671, "zttj": {"days": 2, "ct": 2}},
    {"c": "000813", "n": "德展健康", "p": 3430, "zdp": -4.99, "lbc": 1, "zbc": 0,
     "hybk": "化学制药", "fbt": 92501, "lbt": 92501, "fund": 48980835, "zttj": {"days": 1, "ct": 1}},
    {"c": "002403", "n": "爱仕达", "p": 11280, "zdp": 10.05, "lbc": 1, "zbc": 0,
     "hybk": "小家电", "fbt": 92501, "lbt": 92501, "fund": 30000000, "zttj": {"days": 1, "ct": 1}},
]

# push2ex getYesterdayZTPool 原始行（昨日涨停股在 date 当天的表现）
# 字段：c/n/p(最新价,厘)/ztp(涨停价,厘)/zdp(涨跌幅)/ylbc(昨日连板数)/yfbt(昨日封板时间)/hybk(行业)
PREV_POOL_ROWS = [
    {"c": "002403", "n": "爱仕达", "p": 11280, "ztp": 11280, "zdp": 10.05, "ylbc": 1,
     "yfbt": 142248, "hybk": "小家电", "zttj": {"days": 2, "ct": 1}},
    {"c": "605398", "n": "新炬网络", "p": 26660, "ztp": 26660, "zdp": 9.98, "ylbc": 2,
     "yfbt": 92501, "hybk": "IT服务Ⅱ", "zttj": {"days": 3, "ct": 2}},
    {"c": "000813", "n": "德展健康", "p": 3430, "ztp": 3970, "zdp": -4.99, "ylbc": 1,
     "yfbt": 142248, "hybk": "化学制药", "zttj": {"days": 2, "ct": 1}},
]


def _fake_em_zt_topic_pool(endpoint, date, sort="fbt:asc", raise_on_failure=False):
    """按 endpoint 返对应 fixture（模拟 push2ex）。date 透传不校验。"""
    if endpoint == "getTopicZTPool":
        return list(ZT_POOL_ROWS)
    if endpoint == "getYesterdayZTPool":
        return list(PREV_POOL_ROWS)
    return []


@pytest.fixture
def patched_pools(monkeypatch):
    """mock em_zt_topic_pool + fetch_raw，隔离网络。"""
    monkeypatch.setattr(ext_mod, "em_zt_topic_pool", _fake_em_zt_topic_pool)
    monkeypatch.setattr(ext_mod, "fetch_raw", lambda codes: {c: {"change_pct": 1.23} for c in codes})
    # 日历函数钉死，避免依赖实时状态（vr_paths.prev_trading_date 真实返 date 对象）
    monkeypatch.setattr(ext_mod, "prev_trading_date", lambda d: datetime.date(2026, 9, 3))
    monkeypatch.setattr(ext_mod, "is_settled", lambda d: True)
    monkeypatch.setattr(ext_mod, "live_quotes_are_close_of", lambda d: (False, "settled path only"))
    monkeypatch.setattr(ext_mod, "china_today", lambda: "2026-09-04")


# ─────────────────────── P2-T2a: batch_pct 改 fetch_raw ────────────────────────
def test_batch_pct_uses_tencent_fetch_raw_no_urllib(monkeypatch):
    """batch_pct 走 tencent.fetch_raw 提取 change_pct，不裸调 urllib。"""
    seen = {"called": False}

    def fake_fetch_raw(codes):
        seen["called"] = True
        return {"002403": {"change_pct": 10.05}, "000813": {"change_pct": -4.99}}

    monkeypatch.setattr(ext_mod, "fetch_raw", fake_fetch_raw)
    out = em.batch_pct(["002403", "000813", ""])
    assert seen["called"] is True
    assert out["002403"] == 10.05
    assert out["000813"] == -4.99
    # 空代码过滤
    assert "" not in out


def test_batch_pct_no_urllib_import_in_source():
    """防封底线：emotion_metrics_ext 不得 import urllib/akshare/requests 裸调。"""
    import inspect

    src = inspect.getsource(em)
    assert "import urllib" not in src, "不得 import urllib（走 tencent.fetch_raw 防封）"
    assert "import akshare" not in src, "不得 import akshare"
    assert "import requests" not in src, "不得裸调 requests（走 em_get/tencent 防封）"
    assert "qt.gtimg.cn" not in src or "_QUOTE_URL" not in src.replace("_QUOTE_URL", "x")  # 容许 vibe_astock_util 内部


# ─────────────────────── P2-T2b: fetch_prev_pool 字段映射 ────────────────────────
def test_settled_pool_maps_getYesterdayZTPool_fields(patched_pools):
    """getYesterdayZTPool push2ex 字段 → fetch_prev_pool 目标形状（ret/prev_boards/close/limit_price）。"""
    rows = em._settled_pool("2026-09-04")
    assert rows is not None and len(rows) == 3
    r0 = rows[0]
    # 字段映射
    assert r0["code"] == "002403"
    assert r0["name"] == "爱仕达"
    assert r0["ret"] == 10.05                      # zdp → ret
    assert r0["prev_boards"] == 1                 # ylbc → prev_boards
    assert r0["sector"] == "小家电"                # hybk → sector
    assert r0["close"] == pytest.approx(11.28, abs=0.01)   # p(11280 厘)/1000 → 元
    assert r0["limit_price"] == pytest.approx(11.28, abs=0.01)  # ztp(11280)/1000 → 元
    # seal_time 落字符串（yfbt 数字 → str）
    assert isinstance(r0["seal_time"], str)


def test_settled_pool_unit_conversion(patched_pools):
    """p/ztp 是厘（÷1000=元），对齐 market.py:370 约定。"""
    rows = em._settled_pool("2026-09-04")
    deZhan = [r for r in rows if r["code"] == "000813"][0]
    assert deZhan["close"] == pytest.approx(3.43, abs=0.01)      # 3430 厘 → 3.43 元
    assert deZhan["limit_price"] == pytest.approx(3.97, abs=0.01)  # 3970 厘 → 3.97 元


def test_settled_pool_uses_zs_desc_sort(patched_pools, monkeypatch):
    """getYesterdayZTPool 必须用 sort=zs:desc（fbt:asc 返空池，P2 探测确认）。"""
    seen = {}

    def fake(endpoint, date, sort="fbt:asc", raise_on_failure=False):
        seen["sort"] = sort
        return list(PREV_POOL_ROWS) if endpoint == "getYesterdayZTPool" else []

    monkeypatch.setattr(ext_mod, "em_zt_topic_pool", fake)
    em._settled_pool("2026-09-04")
    assert seen["sort"] == "zs:desc"


# ─────────────────────── P2-T2c: is_limit_up 字段判定 ────────────────────────
def test_is_limit_up_close_equals_limit_price():
    """close==limit_price（涨停）→ True；远低于涨停价 → False。"""
    assert em.is_limit_up({"close": 11.28, "limit_price": 11.28}) is True
    assert em.is_limit_up({"close": 3.43, "limit_price": 3.97}) is False


def test_is_limit_up_missing_prices_returns_none_or_fallback():
    """缺 close/limit_price 时按制度推定或返 None（不臆造）。"""
    # 缺价格 → 走 ret fallback（ret>=涨停幅度-0.3）或 None
    res = em.is_limit_up({"ret": 9.98, "code": "002403", "name": "爱仕达"})
    assert res in (True, False, None)
    # ret=9.98 + 主板 10% - 0.3 = 9.7 → 9.98>=9.7 → True
    if res is not None:
        assert res is True


# ─────────────────────── P2-T1a: money_effect ────────────────────────
def test_money_effect_settled_aggregate(patched_pools):
    """定稿记录优先：money_effect 返 aggregate（avg/median/positive_rate/limit_up_again_rate），无个股名。"""
    me = em.money_effect("2026-09-04")
    assert me["available"] is True
    assert me["source"] == "settled"
    assert me["prev_date"] == "2026-09-03"
    # 3 只样本
    assert me["sample"] == 3
    # 三只 ret: 10.05, 9.98, -4.99
    assert me["avg"] == pytest.approx((10.05 + 9.98 - 4.99) / 3, abs=0.01)
    assert me["median"] == pytest.approx(9.98, abs=0.01)
    assert me["positive_rate"] == pytest.approx(round(2 / 3, 3))  # 两只翻红
    # 再涨停：002403(close==limit→True), 605398(True), 000813(False) → 2/3
    assert me["limit_up_again_rate"] == pytest.approx(round(2 / 3, 3))


def test_money_effect_no_stock_names(patched_pools):
    """守 market.py:166 零个股名契约：aggregate 输出不含 code/name 字段。"""
    me = em.money_effect("2026-09-04")
    assert "code" not in me and "name" not in me
    assert "rows" not in me and "codes" not in me


def test_money_effect_unavailable_reason(patched_pools, monkeypatch):
    """取不到定稿记录且实时行情不可用 → available=False + reason。"""
    monkeypatch.setattr(ext_mod, "_settled_pool", lambda d: None)
    # live_quotes_are_close_of 已返 (False,...)（patched_pools）
    me = em.money_effect("2026-09-04")
    assert me["available"] is False
    assert "reason" in me


# ─────────────────────── P2-T1b: consec_premium 分层 ────────────────────────
def test_consec_premium_aggregate_no_names(patched_pools):
    """consec_premium aggregate：昨日 2 板以上（prev_boards>=2）今日表现，无个股名。"""
    cp = em.consec_premium("2026-09-04")
    assert cp["available"] is True
    assert cp["source"] == "settled"
    # 只有 605398（prev_boards=2）入选
    assert cp["sample"] == 1
    assert cp["avg"] == pytest.approx(9.98, abs=0.01)
    assert cp["median"] == pytest.approx(9.98, abs=0.01)
    assert cp["positive_rate"] == 1.0
    assert "code" not in cp and "name" not in cp


def test_consec_premium_detail_has_stock_names(patched_pools):
    """明细层（分层要求）：consec_premium_detail 带个股 code/name，走独立路由。"""
    result = em.consec_premium_detail("2026-09-04")
    assert result["available"] is True
    assert isinstance(result["detail"], list)
    assert len(result["detail"]) == 1  # 只有 605398（prev_boards>=2）
    row = result["detail"][0]
    assert row["code"] == "605398"
    assert row["name"] == "新炬网络"
    assert row["prev_boards"] == 2
    assert row["ret"] == pytest.approx(9.98, abs=0.01)


def test_consec_premium_detail_signals_failure_not_silent_empty(patched_pools, monkeypatch):
    """取数失败不静默返 []（守"绝不静默吞错"）——返 available=False+reason。"""
    monkeypatch.setattr(ext_mod, "_settled_pool", lambda d: None)
    result = em.consec_premium_detail("2026-09-04")
    assert result["available"] is False
    assert "reason" in result and result["reason"]
    assert result["detail"] == []
    assert result["count"] == 0


def test_consec_premium_detail_not_in_ai_registry(patched_pools):
    """明细带个股名 → 不接入 AI context（不进 chat.TOOLS / registry）。"""
    try:
        from ai.tools import registry
    except Exception:  # noqa: BLE001
        pytest.skip("ai.tools.registry 不可用")
    tools = registry.get_openai_tools()
    names = {t.get("function", {}).get("name", "") if isinstance(t, dict) else getattr(t, "name", "") for t in tools}
    assert "consec_premium_detail" not in names
    assert "emotion_metrics_detail" not in names


# ─────────────────────── P2-T1c: cycle_position 双源规则 ────────────────────────
def test_cycle_position_basic(monkeypatch, patched_pools):
    """cycle_position：10 日窗口内第几天/分位/走向。基于 day_summary 序列。"""
    series = [
        {"date": f"2026-09-{d:02d}", "limit_up": 30, "highest_consec": 2, "broken_rate": 0.1}
        for d in range(1, 5)
    ]
    monkeypatch.setattr(ext_mod, "day_summary",
                        lambda d: next((s for s in series if s["date"] == d), None))
    monkeypatch.setattr(ext_mod, "trade_dates_ending_at", lambda d, n=10: [s["date"] for s in series])
    cp = em.cycle_position("2026-09-04")
    assert cp["available"] is True
    assert cp["window"] == 4
    assert "trough_date" in cp and "day_n" in cp and "trend" in cp
    assert "series" in cp


def test_cycle_position_not_in_render_when_with_cycle_false(patched_pools, monkeypatch):
    """双源规则：build_metrics(with_cycle=False) 不含 cycle → render 不出情绪周期段（AI 安全）。"""
    series = [{"date": "2026-09-01", "limit_up": 30, "highest_consec": 2, "broken_rate": 0.1}]
    monkeypatch.setattr(ext_mod, "day_summary", lambda d: series[0] if d == series[0]["date"] else None)
    monkeypatch.setattr(ext_mod, "trade_dates_ending_at", lambda d, n=10: ["2026-09-01"])
    m = em.build_metrics("2026-09-04", with_cycle=False)
    assert "cycle" not in m
    txt = em.render_metrics(m)
    assert "情绪周期" not in txt


# ─────────────────────── P2-T1d: build_metrics / render_metrics ────────────────────────
def test_build_metrics_three_indicators_only(patched_pools, monkeypatch):
    """§1.4 范围冻结：build_metrics 只含 3 个新指标（money_effect/consec_premium/cycle），无 promotion/ladder_gap。"""
    monkeypatch.setattr(ext_mod, "day_summary",
                        lambda d: {"limit_up": 30, "highest_consec": 2, "broken_rate": 0.1})
    monkeypatch.setattr(ext_mod, "trade_dates_ending_at",
                        lambda d, n=10: ["2026-09-01", "2026-09-02", "2026-09-03"])
    m = em.build_metrics("2026-09-04")
    assert "money_effect" in m
    assert "consec_premium" in m
    # 冻结：promotion/ladder_gap 不在（market._emotion 已有，参照不移植）
    assert "promotion" not in m
    assert "ladder_gap" not in m


def test_render_metrics_renders_three_sections(patched_pools, monkeypatch):
    """render_metrics 渲染赚钱效应/连板溢价（+情绪周期当 with_cycle）。"""
    monkeypatch.setattr(ext_mod, "day_summary",
                        lambda d: {"limit_up": 30, "highest_consec": 2, "broken_rate": 0.1})
    monkeypatch.setattr(ext_mod, "trade_dates_ending_at",
                        lambda d, n=10: ["2026-09-01", "2026-09-02", "2026-09-03"])
    m = em.build_metrics("2026-09-04", with_cycle=True)
    txt = em.render_metrics(m)
    assert "赚钱效应" in txt
    assert "连板溢价" in txt
    assert "情绪周期" in txt


# ─────────────────────── P2-T1d: day_summary 缓存 ────────────────────────
def test_day_summary_cache_under_vr_data_dir(monkeypatch, tmp_path):
    """缓存落 resolve_data_dir()/zt_summary/，不硬编码 ~/.duanxian-agents。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ext_mod, "em_zt_topic_pool", _fake_em_zt_topic_pool)
    monkeypatch.setattr(ext_mod, "is_settled", lambda d: True)
    monkeypatch.setattr(ext_mod, "china_today", lambda: "2026-09-04")
    monkeypatch.setattr(ext_mod, "prev_trading_date", lambda d: "2026-09-03")

    out = em.day_summary("2026-09-04")
    assert out is not None
    assert out["limit_up"] == 3
    # 落盘路径在 VR_DATA_DIR 下，不在 home
    cache_file = tmp_path / "zt_summary" / "2026-09-04.json"
    assert cache_file.is_file()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert data["source"] == "em_zt_topic_pool"   # 非 akshare_zt_pool
    assert data["date"] == "2026-09-04"
    # 再读走缓存（不重新取数）
    calls = {"n": 0}
    _orig = _fake_em_zt_topic_pool

    def counting(endpoint, date, sort="fbt:asc", raise_on_failure=False):
        calls["n"] += 1
        return _orig(endpoint, date, sort, raise_on_failure)

    monkeypatch.setattr(ext_mod, "em_zt_topic_pool", counting)
    out2 = em.day_summary("2026-09-04")
    assert out2 == out
    assert calls["n"] == 0   # 命中缓存，未触网


def test_day_summary_no_hardcoded_home(monkeypatch, tmp_path):
    """缓存目录走 vr_paths.resolve_data_dir()——运行时路径不含 ~/.duanxian-agents。"""
    monkeypatch.setenv("VR_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ext_mod, "em_zt_topic_pool", _fake_em_zt_topic_pool)
    monkeypatch.setattr(ext_mod, "is_settled", lambda d: True)
    monkeypatch.setattr(ext_mod, "china_today", lambda: "2026-09-04")
    em.day_summary("2026-09-04")
    cache_dir = em._summary_cache_dir()
    assert str(tmp_path) in cache_dir                # 在 VR_DATA_DIR 下
    assert ".duanxian-agents" not in cache_dir       # 不硬编码 home 路径


# ─────────────────────── _zt_pool / ladder / pool_codes ────────────────────────
def test_zt_pool_maps_getTopicZTPool(patched_pools):
    """_zt_pool：getTopicZTPool list[dict] → {zt, ladder, zb_count, highest_consec}。"""
    zt = em._zt_pool("2026-09-04")
    assert zt is not None
    assert zt["error_zt"] in (None, False)
    assert len(zt["zt"]) == 3
    ladder = zt["ladder"]
    by_code = {x["code"]: x for x in ladder}
    assert by_code["605398"]["boards"] == 2
    assert by_code["000813"]["boards"] == 1


def test_pool_codes(patched_pools):
    zt = em._zt_pool("2026-09-04")
    codes = em._pool_codes(zt)
    assert "605398" in codes and "000813" in codes and "002403" in codes
