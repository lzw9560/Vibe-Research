# -*- coding: utf-8 -*-
"""S088 盘前暴风雨预测单测。

覆盖 grill 对抗性核实后修复的三处承重 bug：
- Q5：_collect_news_factor 改 industries 嵌套聚合（原 radar.get("items") 取不存在的顶层键→恒 missing）+ 利好对冲
- Q1：prev_trading_date 严格前一交易日（原 last_trading_date(d) 在交易日返回 d 本身）+ get_t1 读前日快照
- Q4：八项 ④⑤ 补全（pool_item.fbt/zbc 注入 per-card ctx，原 market_ctx=board 无 fbt/zbc→恒 missing）

conftest 已设 VR_STORM_DAEMON=0，import storm_daemon 不会启动后台线程。
"""
from __future__ import annotations

import json
from datetime import date, datetime
from unittest.mock import patch


# ============================================================================
# Q5：新闻因子 industries 聚合 + 利好对冲
# ============================================================================

def _make_radar(titles: list[str]) -> dict:
    """构造 fetch_radar 返回结构：industries 嵌套 items（顶层无 items 键）。

    复刻真实 fetch_radar 顶层 keys=generated_at/recent_days/industries/stats。
    """
    items = [{"title": t, "summary": ""} for t in titles]
    return {
        "generated_at": "2026-08-20 09:00",
        "recent_days": 7,
        "industries": [
            {"key": "test", "name": "测试", "accent": "#fff", "total": len(items), "items": items}
        ],
        "stats": {"industries": 1, "total_sources": 1, "failed_sources": 0},
    }


def test_news_factor_aggregates_industries_items_not_top_level():
    """Q5：原 radar.get('items') 取不到顶层键→恒 missing。改后 industries 聚合应取到并计分。"""
    from strategies import storm_predictor

    radar = _make_radar(["暴跌", "大涨", "退市"])
    with patch("newsradar.get_radar", return_value=radar):
        f = storm_predictor._collect_news_factor("2026-08-20")
    assert f.data_status == "ok"
    assert "利空 2" in f.detail
    assert "利好 1" in f.detail
    # 利空占比 2/3 → score ≈ 66.7
    assert 60 <= f.score <= 70


def test_news_factor_neutral_words_not_counted():
    """Q5：增长/合作等中性高频词不计入（原 bearish_kw 含'风险/增长'致利好噪声大）。"""
    from strategies import storm_predictor

    radar = _make_radar(["增长5%", "合作协议", "风险提示"])
    with patch("newsradar.get_radar", return_value=radar):
        f = storm_predictor._collect_news_factor("2026-08-20")
    assert f.data_status == "missing"
    assert f.score == 50.0


def test_news_factor_missing_when_no_items():
    """Q5：industries 空时返 missing 50（缺数据不臆造）。"""
    from strategies import storm_predictor

    with patch("newsradar.get_radar", return_value={"industries": []}):
        f = storm_predictor._collect_news_factor("2026-08-20")
    assert f.data_status == "missing"
    assert f.score == 50.0


def test_news_factor_bullish_dominant_lowers_score():
    """Q5：利好远多于利空→低分（暴风雨概率低）。"""
    from strategies import storm_predictor

    radar = _make_radar(["退市", "涨停", "大涨", "暴涨", "回购", "增持"])
    with patch("newsradar.get_radar", return_value=radar):
        f = storm_predictor._collect_news_factor("2026-08-20")
    assert f.score < 25  # 利空 1/6 ≈ 16.7


def test_news_factor_all_bearish_max_score():
    """Q5：全利空→100 分。"""
    from strategies import storm_predictor

    radar = _make_radar(["暴跌", "崩盘", "跌停"])
    with patch("newsradar.get_radar", return_value=radar):
        f = storm_predictor._collect_news_factor("2026-08-20")
    assert f.score == 100.0


# ============================================================================
# Q1：prev_trading_date 严格前一交易日 + get_t1 读前日快照
# ============================================================================

def test_prev_trading_date_returns_previous_not_self():
    """Q1：交易日 d 的前一交易日不应是 d 本身（原 last_trading_date bug）。"""
    from vr_paths import prev_trading_date, last_trading_date

    d = date(2026, 8, 19)  # 周三，交易日
    assert last_trading_date(d) == d  # 确认旧行为：返回当日
    assert prev_trading_date(d) == date(2026, 8, 18)  # 严格前一交易日


def test_prev_trading_date_over_weekend():
    """Q1：周五的前一交易日是周四（跳过周末）。"""
    from vr_paths import prev_trading_date

    fri = date(2026, 8, 21)  # 周五
    assert prev_trading_date(fri) == date(2026, 8, 20)  # 周四


def test_prev_trading_day_string_helper_uses_prev():
    """Q1：storm_predictor._prev_trading_day 不再返回当日。"""
    from strategies import storm_predictor

    assert storm_predictor._prev_trading_day("2026-08-19") == "2026-08-18"


def test_get_t1_snapshot_reads_prev_trading_day_not_current(tmp_path, monkeypatch):
    """Q1：get_t1_global_snapshot 读前一交易日 .json，不读当日（修原取当日 bug）。"""
    from strategies import storm_daemon

    monkeypatch.setattr(storm_daemon, "_SNAP_DIR", tmp_path)
    # 前一交易日（0818）夜间快照：美股跌 3%
    (tmp_path / "2026-08-18.json").write_text(
        json.dumps([{"ts": "2026-08-18T04:00", "date": "2026-08-18",
                     "global_indices": [{"name": "道琼斯", "change_pct": -3.0}]}]),
        encoding="utf-8",
    )
    # 当日（0819）诱饵快照：美股涨 1%（证明不读当日）
    (tmp_path / "2026-08-19.json").write_text(
        json.dumps([{"ts": "2026-08-19T10:00", "date": "2026-08-19",
                     "global_indices": [{"name": "道琼斯", "change_pct": 1.0}]}]),
        encoding="utf-8",
    )
    snap = storm_daemon.get_t1_global_snapshot("2026-08-19")
    assert snap is not None
    assert snap["global_indices"][0]["change_pct"] == -3.0  # 读 0818 非当日


def test_get_t1_snapshot_returns_none_when_prev_missing(tmp_path, monkeypatch):
    """Q1：前一交易日无快照→None（调用方 fallback 当前，透明降级）。"""
    from strategies import storm_daemon

    monkeypatch.setattr(storm_daemon, "_SNAP_DIR", tmp_path)
    # 只有当日，无前日
    (tmp_path / "2026-08-19.json").write_text("[]", encoding="utf-8")
    assert storm_daemon.get_t1_global_snapshot("2026-08-19") is None


# ============================================================================
# Q4：八项 ④⑤ 补全（pool_item.fbt/zbc 注入 per-card ctx）
# ============================================================================

def _ind_basic() -> "object":
    """构造覆盖八项 ①②③⑥⑧ 的 IndicatorSet。"""
    from candidate_funnel.models import IndicatorSet

    return IndicatorSet(
        code="000001", name="测试",
        float_market_cap=5_000_000_000,  # 50 亿 → ① pass（30-150 亿）
        turnover_pct=10.0,              # ② pass（5-20%）
        vol_ratio=2.0,                  # ③ pass（≥1.5）
        seal_amount=100_000_000,        # ⑥ 1e8/5e9=2% > 1% → pass
        consec_boards=1,               # ⑧ 低位首板
        ma20=10.0, price=11.0,         # ⑧ price>ma20 平台突破
    )


def test_eight_standards_45_filled_from_pool_item():
    """Q4：pool_item.fbt/zbc 注入，④⑤ 不再恒 missing。"""
    from candidate_funnel.diagnosis import build_diagnosis_card
    from candidate_funnel.thresholds import BaseThreshold

    pool_item = {"fbt": 92500, "zbc": 0, "fund": 1e8}  # 09:25 首封 / 开板 0 次
    card = build_diagnosis_card("000001", "测试", _ind_basic(), BaseThreshold(),
                                market_ctx={}, pool_item=pool_item, as_of=datetime(2026, 8, 20, 9, 30))
    items = {i.key: i for i in card.eight_standards.items}
    assert items["4"].status != "missing", f"④ 应注入非 missing，实={items['4'].status}"
    assert items["5"].status != "missing", f"⑤ 应注入非 missing，实={items['5'].status}"
    assert items["4"].status == "pass"  # 09:25 ≤ 10:30
    assert items["5"].status == "pass"  # 0 ≤ 1


def test_eight_standards_4_fail_when_seal_after_1030():
    """Q4：fbt=110000（11:00）→ ④ fail（非 missing，证明注入生效参与判定）。"""
    from candidate_funnel.diagnosis import build_diagnosis_card
    from candidate_funnel.thresholds import BaseThreshold

    pool_item = {"fbt": 110000, "zbc": 0, "fund": 1e8}  # 11:00 首封
    card = build_diagnosis_card("000001", "测试", _ind_basic(), BaseThreshold(),
                                market_ctx={}, pool_item=pool_item, as_of=datetime(2026, 8, 20, 11, 0))
    items = {i.key: i for i in card.eight_standards.items}
    assert items["4"].status == "fail"  # 11:00 > 10:30


def test_eight_standards_5_fail_when_reopens_twice():
    """Q4：zbc=2（开板 2 次）→ ⑤ fail（>1）。"""
    from candidate_funnel.diagnosis import build_diagnosis_card
    from candidate_funnel.thresholds import BaseThreshold

    pool_item = {"fbt": 92500, "zbc": 2, "fund": 1e8}
    card = build_diagnosis_card("000001", "测试", _ind_basic(), BaseThreshold(),
                                market_ctx={}, pool_item=pool_item, as_of=datetime(2026, 8, 20, 9, 30))
    items = {i.key: i for i in card.eight_standards.items}
    assert items["5"].status == "fail"  # 2 > 1


def test_eight_standards_45_missing_without_pool_item():
    """Q4：无 pool_item（非涨停股）④⑤ 仍 missing（正确，仅涨停股有意义）。"""
    from candidate_funnel.diagnosis import build_diagnosis_card
    from candidate_funnel.thresholds import BaseThreshold

    card = build_diagnosis_card("000001", "测试", _ind_basic(), BaseThreshold(),
                                market_ctx={}, pool_item=None, as_of=datetime(2026, 8, 20, 9, 30))
    items = {i.key: i for i in card.eight_standards.items}
    assert items["4"].status == "missing"
    assert items["5"].status == "missing"


def test_eight_standards_ctx_copy_no_leak_between_cards():
    """Q4：board 在 run_funnel 全 N 卡复用；per-card ctx 拷贝不泄漏上一只票 fbt。"""
    from candidate_funnel.diagnosis import build_diagnosis_card
    from candidate_funnel.thresholds import BaseThreshold

    shared_board = {}  # 模拟 run_funnel 复用的 board（无 fbt/zbc）
    # 票 A 有 fbt（注入到 A 的 ctx 拷贝）
    card_a = build_diagnosis_card("000001", "A", _ind_basic(), BaseThreshold(),
                                  market_ctx=shared_board,
                                  pool_item={"fbt": 92500, "zbc": 0, "fund": 1e8},
                                  as_of=datetime(2026, 8, 20, 9, 30))
    # 票 B 无 pool_item——若 ctx 不拷贝（直接改 shared_board），B 会继承 A 的 first_seal_time
    card_b = build_diagnosis_card("000002", "B", _ind_basic(), BaseThreshold(),
                                  market_ctx=shared_board, pool_item=None,
                                  as_of=datetime(2026, 8, 20, 9, 30))
    items_b = {i.key: i for i in card_b.eight_standards.items}
    # B 无 pool_item，④⑤ 应 missing（不泄漏 A 的值）
    assert items_b["4"].status == "missing"
    assert items_b["5"].status == "missing"


# ============================================================================
# 集成：predict_storm 加权 + 概率→仓位映射
# ============================================================================

def test_predict_storm_weights_and_position_mapping(monkeypatch):
    """S088 集成：四因子加权（0.35+0.35+0.20+0.10）+ 概率→仓位映射端到端。

    0.35*80 + 0.35*60 + 0.20*40 + 0.10*30 = 28+21+8+3 = 60 → 高/半仓 0.5
    """
    from strategies import storm_predictor

    def _f(name: str, score: float) -> "storm_predictor.StormFactor":
        return storm_predictor.StormFactor(name, score, "detail", "ok")

    monkeypatch.setattr(storm_predictor, "_collect_global_factor", lambda d: _f("外围", 80))
    monkeypatch.setattr(storm_predictor, "_collect_internal_factor", lambda d: _f("内部", 60))
    monkeypatch.setattr(storm_predictor, "_collect_news_factor", lambda d: _f("新闻", 40))
    monkeypatch.setattr(storm_predictor, "_collect_calendar_factor", lambda d: _f("日历", 30))
    p = storm_predictor.predict_storm("2026-08-20")
    assert p.probability == 60.0
    assert p.risk_level == "高"  # 50 ≤ 60 < 70
    assert p.suggested_position == 0.50
    assert len(p.factors) == 4


def test_predict_storm_high_risk_clamps_position(monkeypatch):
    """S088 集成：概率≥70 → 极高 / 0.25 仓。"""
    from strategies import storm_predictor

    def _f(name: str, score: float) -> "storm_predictor.StormFactor":
        return storm_predictor.StormFactor(name, score, "detail", "ok")

    monkeypatch.setattr(storm_predictor, "_collect_global_factor", lambda d: _f("外围", 90))
    monkeypatch.setattr(storm_predictor, "_collect_internal_factor", lambda d: _f("内部", 80))
    monkeypatch.setattr(storm_predictor, "_collect_news_factor", lambda d: _f("新闻", 80))
    monkeypatch.setattr(storm_predictor, "_collect_calendar_factor", lambda d: _f("日历", 80))
    p = storm_predictor.predict_storm("2026-08-20")
    # 0.35*90+0.35*80+0.20*80+0.10*80 = 31.5+28+16+8 = 83.5
    assert p.risk_level == "极高"
    assert p.suggested_position == 0.25


# ============================================================================
# Q2/Q3：外围因子 6 指数加权 + per-index missing 再归一 + KOSPI/SOX 接入
# ============================================================================

def _make_indices(changes: dict[str, float]) -> list[dict]:
    """构造 global_indices 返回结构：{name: change_pct}。"""
    return [{"name": n, "change_pct": c, "region": "test", "key": n} for n, c in changes.items()]


def test_global_factor_six_indices_weighted(monkeypatch):
    """Q2/Q3：6 指数在场，权重 0.35/0.20/0.15/0.10/0.10/0.10 加权。

    美股均 -3.0 / A50 -1.0 / 港股均 -2.0 / 日经 -1.0 / KOSPI -2.0 / SOX -2.0
    combined = -1.05-0.20-0.30-0.10-0.20-0.20 = -2.05 → score = 50+30.75 = 80.75
    """
    from strategies import storm_predictor, storm_daemon

    indices = _make_indices({
        "道琼斯": -3.0, "标普500": -2.0, "纳斯达克": -4.0,
        "富时A50": -1.0, "恒生指数": -2.0, "恒生科技": -2.0,
        "日经225": -1.0, "韩国KOSPI": -2.0, "费城半导体": -2.0,
    })
    monkeypatch.setattr(storm_daemon, "get_t1_global_snapshot",
                       lambda d: {"global_indices": indices})
    f = storm_predictor._collect_global_factor("2026-08-20")
    assert f.data_status == "ok"
    assert abs(f.score - 80.75) < 0.3
    assert "KOSPI" in f.detail and "SOX" in f.detail and "日经" in f.detail
    assert "缺" not in f.detail  # 全在场无缺失


def test_global_factor_missing_index_renormalizes(monkeypatch):
    """Q2：缺 SOX 不静默归零——权重再归一给在场 5 项，detail 标'缺 SOX'。

    在场 5 项原权重和 0.90，再归一 ÷0.90：
    combined = (-3*0.35-1*0.20-2*0.15-1*0.10-2*0.10)/0.90 = -1.85/0.90 = -2.056
    score = 50+30.83 = 80.83（比全在场 80.75 略高，因 SOX -2.0 低于均值，剔除后剩余更悲观）
    """
    from strategies import storm_predictor, storm_daemon

    indices = _make_indices({
        "道琼斯": -3.0, "标普500": -2.0, "纳斯达克": -4.0,
        "富时A50": -1.0, "恒生指数": -2.0, "恒生科技": -2.0,
        "日经225": -1.0, "韩国KOSPI": -2.0,
        # 无费城半导体 SOX
    })
    monkeypatch.setattr(storm_daemon, "get_t1_global_snapshot",
                       lambda d: {"global_indices": indices})
    f = storm_predictor._collect_global_factor("2026-08-20")
    assert "缺 SOX" in f.detail
    assert abs(f.score - 80.83) < 0.4


def test_global_factor_all_missing_returns_neutral(monkeypatch):
    """Q2：全部指数 change_pct 缺→missing 50，不臆造。"""
    from strategies import storm_predictor, storm_daemon

    monkeypatch.setattr(storm_daemon, "get_t1_global_snapshot",
                       lambda d: {"global_indices": [{"name": "道琼斯", "change_pct": None}]})
    f = storm_predictor._collect_global_factor("2026-08-20")
    assert f.data_status == "missing"
    assert f.score == 50.0


def test_global_factor_fallback_current_when_no_snapshot(monkeypatch):
    """Q1：无前日快照→fallback market 当前，标 fallback_current。"""
    from strategies import storm_predictor, storm_daemon
    import market

    monkeypatch.setattr(storm_daemon, "get_t1_global_snapshot", lambda d: None)
    monkeypatch.setattr(market, "get_global_indices",
                        lambda: _make_indices({"道琼斯": -3.0, "标普500": -2.0, "纳斯达克": -4.0,
                                               "富时A50": -1.0}))
    f = storm_predictor._collect_global_factor("2026-08-20")
    assert f.data_status == "fallback_current"
    assert "美股均" in f.detail


def test_global_indices_includes_kospi_and_sox(monkeypatch):
    """Q3：global_indices 含 KOSPI（_INDICES push2）+ SOX（datacenter 分流）。"""
    import gstock

    monkeypatch.setattr(gstock, "_push2_stock_get",
                        lambda secid, fields: {"f58": "x", "f43": 100, "f170": 100, "f59": 2})
    monkeypatch.setattr(gstock, "_fetch_sox_datacenter",
                        lambda: {"key": "sox", "name": "费城半导体", "region": "外围半导体",
                                 "price": 11738, "change_pct": -2.12})
    out = gstock.global_indices()
    keys = {i["key"] for i in out}
    assert "kospi" in keys  # _INDICES 含（push2）
    assert "sox" in keys  # datacenter 分流
    sox = next(i for i in out if i["key"] == "sox")
    assert sox["change_pct"] == -2.12
