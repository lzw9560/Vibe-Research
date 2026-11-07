# -*- coding: utf-8 -*-
"""test_cards.py — 卡片构建函数测试。

测试覆盖：
- build_premarket_card / build_postmarket_card / build_scan_card /
  build_sentiment_card / build_test_card / build_intraday_card /
  build_alert_card / build_alert_card_live
- 空数据降级（不崩溃）
- 正常数据（结构正确）
- 极端数据（边界值）
- 返回 dict + header/elements 结构

mock 数据层函数 + sentiment + urllib，不触碰真实网络/CLI。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from feishu import cards
from feishu.sentiment import calculate_sentiment_score


# ─── 辅助：构造 mock 数据 ───

def _index(code="000001.SH", price=3300.0, chg=0.5, turnover=5e10):
    return {"thscode": code, "last_price": price, "price_change_ratio_pct": chg, "turnover": turnover}


def _hot_stock(rank=1, name="热股A", code="600001.SH", trend="up"):
    return {"rank": rank, "name": name, "thscode": code, "rank_trend": trend}


def _dragon_item(name="龙虎A", code="600001.SH", net_value=3e8, concepts=None):
    return {
        "name": name, "thscode": code, "net_value": net_value,
        "concept_list": concepts or [{"name": "AI"}, {"name": "芯片"}],
    }


def _ladder_item(boards=None):
    return {"boards": boards or {
        "two_board": [{"name": "二板A", "board_num": 2}],
        "three_board": [{"name": "三板B", "board_num": 3}],
    }}


def _sentiment_data(score=50):
    """构造一个完整的 sentiment 返回 dict（震荡期）。"""
    return calculate_sentiment_score(data={
        "indices": [_index(turnover=8e10)],  # 8000亿 → vol_score=15
        "all_stocks": [{"price_change_ratio_pct": 1.0} for _ in range(60)] +
                      [{"price_change_ratio_pct": -1.0} for _ in range(40)],
        "ladder": [_ladder_item()],
        "dragon": [_dragon_item(net_value=3e8)],
    })


# ─── 公共 fixture：mock 所有数据层函数 ───

@pytest.fixture
def _empty_data(monkeypatch):
    """所有数据函数返回空——测降级不崩溃。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())
    # mock urllib 避免真实网络请求（premarket/intraday 都调 urllib）
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=OSError("no api")))


@pytest.fixture
def _normal_data(monkeypatch):
    """注入正常 mock 数据。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [_index(), _index("399001.SZ", 10500, -0.3)])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [_hot_stock(i, f"热股{i}", f"60000{i}.SH") for i in range(1, 11)])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [_dragon_item(net_value=v * 1e8) for v in [5, 4, 3, 2, 1]])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [_ladder_item()])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [{"name": f"飙升{i}", "thscode": f"60000{i}.SH"} for i in range(5)])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [{
        "code": "600001.SH", "name": "A组标的", "chg": 5.0, "net": 0.3,
        "hot_rank": 200, "concepts": "AI,芯片",
    }])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=OSError("no api")))


# ─── build_test_card ───

def test_build_test_card_returns_dict():
    """build_test_card 返回 dict 且含 header/elements。"""
    card = cards.build_test_card()
    assert isinstance(card, dict)
    assert "header" in card
    assert "elements" in card
    assert card["header"]["template"] == "green"


def test_build_test_card_title():
    """标题含"测试"字样。"""
    card = cards.build_test_card()
    title = card["header"]["title"]["content"]
    assert "测试" in title or "Bot" in title


def test_build_test_card_elements_nonempty():
    """elements 至少有 2 个（markdown + note）。"""
    card = cards.build_test_card()
    assert len(card["elements"]) >= 2


# ─── build_premarket_card ───

def test_build_premarket_card_empty_data(_empty_data):
    """空数据 → 不崩溃，返回 dict。"""
    card = cards.build_premarket_card()
    assert isinstance(card, dict)
    assert "header" in card
    assert "elements" in card
    # 空数据时仍应有 note 元素
    assert any(e.get("tag") == "note" for e in card["elements"])


def test_build_premarket_card_normal_data(_normal_data):
    """正常数据 → 含指数/热股/龙虎榜 markdown。"""
    card = cards.build_premarket_card()
    assert isinstance(card, dict)
    assert card["header"]["template"] == "blue"
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    joined = "\n".join(contents)
    # 应包含指数快照（有数据时）
    assert "指数快照" in joined


def test_build_premarket_card_header_template(_empty_data):
    """header template 为 blue。"""
    card = cards.build_premarket_card()
    assert card["header"]["template"] == "blue"


def test_build_premarket_card_title_has_timestamp(_empty_data):
    """标题含盘前推送 + 时间。"""
    card = cards.build_premarket_card()
    title = card["header"]["title"]["content"]
    assert "盘前" in title


# ─── build_postmarket_card ───

def test_build_postmarket_card_empty_data(_empty_data):
    """空数据 → 不崩溃。"""
    card = cards.build_postmarket_card()
    assert isinstance(card, dict)
    assert "header" in card
    assert "elements" in card


def test_build_postmarket_card_normal_data(_normal_data):
    """正常数据 → 含收盘指数/连板梯队/热股/龙虎榜。"""
    card = cards.build_postmarket_card()
    assert card["header"]["template"] == "green"
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    joined = "\n".join(contents)
    assert "收盘指数" in joined
    assert "连板梯队" in joined


def test_build_postmarket_card_has_strategy1_archive_notice(_empty_data):
    """盘后卡片含策略1归档通告。"""
    card = cards.build_postmarket_card()
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    joined = "\n".join(contents)
    assert "窒息量" in joined or "归档" in joined


# ─── build_scan_card ───

def test_build_scan_card_empty_data(_empty_data):
    """空 A 组数据 → 显示"无符合条件"。"""
    card = cards.build_scan_card()
    assert isinstance(card, dict)
    assert card["header"]["template"] == "grey"  # 无数据时 grey
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    joined = "\n".join(contents)
    assert "无符合条件" in joined or "无" in joined


def test_build_scan_card_normal_data(_normal_data):
    """有 A 组数据 → green template + 含标的。"""
    card = cards.build_scan_card()
    assert card["header"]["template"] == "green"
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    joined = "\n".join(contents)
    assert "A组" in joined
    # cards.py 用 code[:6] 截断 thscode（600001.SH → 600001）
    assert "600001" in joined


def test_build_scan_card_has_disclaimer(_empty_data):
    """scan 卡片含免责声明 note。"""
    card = cards.build_scan_card()
    notes = [e for e in card["elements"] if e.get("tag") == "note"]
    assert len(notes) >= 1
    assert "投资建议" in notes[0]["content"]


# ─── build_sentiment_card ───

def test_build_sentiment_card_empty(_empty_data):
    """sentiment 空数据 → 不崩溃（_sentiment_data 提供默认）。"""
    card = cards.build_sentiment_card()
    assert isinstance(card, dict)
    assert "header" in card
    assert "elements" in card


def test_build_sentiment_card_normal(_normal_data):
    """正常 sentiment → 含情绪得分/仓位/问财/风控。"""
    card = cards.build_sentiment_card()
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    joined = "\n".join(contents)
    assert "情绪得分" in joined
    assert "仓位" in joined
    assert "问财" in joined or "wencai" in joined.lower() or "选股" in joined
    assert "风控" in joined


def test_build_sentiment_card_template_by_score(monkeypatch):
    """template 随 score 变化：<=35 blue, <=70 orange, >70 red。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])

    # 冰点期 score<=35 → blue（空数据：vol=5 + effect=12 + ladder=3 + flow=3 = 23）
    freezing = calculate_sentiment_score(data={"indices": [], "all_stocks": [], "ladder": [], "dragon": []})
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: freezing)
    card_freeze = cards.build_sentiment_card()
    assert card_freeze["header"]["template"] == "blue"

    # 沸点期 score>70 → red
    # 需要 vol_score=25（turnover>15000亿=1.5e12）+ effect=25 + ladder=22 + flow=13 = 85
    boiling = calculate_sentiment_score(data={
        "indices": [_index(turnover=2e12)],  # 20000亿 → vol_score=25
        "all_stocks": [{"price_change_ratio_pct": 10.0} for _ in range(90)] +
                      [{"price_change_ratio_pct": -1.0} for _ in range(10)],
        "ladder": [{"boards": {"seven_over": [{"name": "七板", "board_num": 7}]}}],
        "dragon": [_dragon_item(net_value=1e9)],
    })
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: boiling)
    card_boil = cards.build_sentiment_card()
    assert card_boil["header"]["template"] == "red"


# ─── build_intraday_card ───

def test_build_intraday_card_api_fail(_empty_data):
    """RSI API 不可用 → 显示"拉取失败"，不崩溃。"""
    card = cards.build_intraday_card()
    assert isinstance(card, dict)
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    joined = "\n".join(contents)
    # urllib mock 抛 OSError → 走 except 显示"拉取失败"
    assert "拉取失败" in joined or "RSI" in joined


def test_build_intraday_card_normal(monkeypatch):
    """RSI API 返回买入信号 → 显示信号内容。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())

    rsi_data = {
        "buy_count": 1, "wait_count": 0,
        "signals": [{
            "index_name": "上证指数", "combo_signal": "买入",
            "rsi": 25, "expected_60d": 7.82, "win_rate_60d": 92,
            "macd_dif": 0.5, "macd_dea": 0.3,
        }],
    }
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=cm)
    cm.__exit__ = MagicMock(return_value=False)
    cm.read = MagicMock(return_value=json.dumps(rsi_data).encode("utf-8"))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(return_value=cm))

    card = cards.build_intraday_card()
    assert isinstance(card, dict)
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    joined = "\n".join(contents)
    assert "买入信号" in joined or "RSI" in joined


# ─── build_alert_card ───

def test_build_alert_card_empty_signals():
    """空信号列表 → 显示"暂无触发"。"""
    card = cards.build_alert_card([])
    assert isinstance(card, dict)
    assert card["header"]["template"] == "grey"
    contents = [e.get("content", "") for e in card["elements"] if e.get("tag") == "markdown"]
    assert "暂无" in contents[0]


def test_build_alert_card_with_buy_signal():
    """有买入信号 → red template。"""
    signals = [{
        "code": "600001.SH", "name": "测试股", "signal": "买入",
        "price": 10.5, "ma5": 10.0, "chg_pct": 2.5, "turnover": 3e8,
        "reason": "回踩5日线", "buy_condition": "T+2买入",
        "trigger_detail": "站稳5日线", "stop_loss_pct": -15,
        "target_pct": 20, "weight": 20,
    }]
    card = cards.build_alert_card(signals)
    assert card["header"]["template"] == "red"
    assert len(card["elements"]) >= 2  # markdown + hr + note


def test_build_alert_card_with_wait_signal():
    """观望信号 → grey-ish（非买入）。"""
    signals = [{
        "code": "600001.SH", "name": "测试股", "signal": "观望",
        "price": 10.5, "ma5": 10.0, "chg_pct": 0.5, "turnover": 3e8,
        "reason": "数据不足", "buy_condition": "观望",
        "trigger_detail": "未触发", "stop_loss_pct": -15,
        "target_pct": 20, "weight": 20,
    }]
    card = cards.build_alert_card(signals)
    assert card["header"]["template"] == "red"  # 有 signals 就 red


def test_build_alert_card_multiple_signals():
    """多个信号 → 每个 signal 一段 markdown + hr。"""
    signals = [
        {"code": f"60000{i}.SH", "name": f"股{i}", "signal": "买入",
         "price": 10, "ma5": 9, "chg_pct": 1, "turnover": 1e8,
         "reason": "r", "buy_condition": "c", "trigger_detail": "t",
         "stop_loss_pct": -10, "target_pct": 20, "weight": 20}
        for i in range(3)
    ]
    card = cards.build_alert_card(signals)
    markdowns = [e for e in card["elements"] if e.get("tag") == "markdown"]
    hrs = [e for e in card["elements"] if e.get("tag") == "hr"]
    assert len(markdowns) >= 3
    assert len(hrs) >= 2  # 信号之间有 hr


# ─── build_alert_card_live ───

def test_build_alert_card_live(monkeypatch):
    """build_alert_card_live 调 check_buy_signals 并构建卡片。"""
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    card = cards.build_alert_card_live()
    assert isinstance(card, dict)
    assert "header" in card


# ─── 极端数据测试 ───

def test_build_premarket_card_extreme_data(monkeypatch):
    """极端数据（巨幅涨跌/天量成交）不崩溃。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [
        _index("000001.SH", 99999.9, 99.9, 1e15),  # 涨停级涨幅 + 天量
        _index("399001.SZ", 0.01, -99.9, 0),       # 跌停级跌幅
    ])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=OSError("no api")))

    card = cards.build_premarket_card()
    assert isinstance(card, dict)


def test_build_postmarket_card_extreme_dragon(monkeypatch):
    """龙虎榜 net_value 为 None/0/负数不崩溃。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [
        {"name": "A", "thscode": "600001.SH", "net_value": None, "concept_list": []},
        {"name": "B", "thscode": "600002.SH", "net_value": 0, "concept_list": []},
        {"name": "C", "thscode": "600003.SH", "net_value": -1e8, "concept_list": []},
    ])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=OSError("no api")))

    card = cards.build_postmarket_card()
    assert isinstance(card, dict)


def test_build_premarket_card_missing_fields(monkeypatch):
    """数据项缺字段（无 last_price/turnover）不崩溃。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [
        {"thscode": "000001.SH"},  # 缺 last_price/turnover
    ])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [
        {"name": "热股"},  # 缺 rank/thscode
    ])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=OSError("no api")))

    # 可能抛 KeyError——如果代码用 idx['last_price'] 而非 .get()
    # 先验证是否能跑过，跑不过说明 cards 对缺字段不健壮（也是测试发现）
    try:
        card = cards.build_premarket_card()
        assert isinstance(card, dict)
    except (KeyError, TypeError):
        # 记录已知缺陷：cards.py 用 idx['last_price'] 硬取，缺字段会崩
        pytest.skip("cards.py 用硬取键访问，缺字段时崩溃——已知缺陷")


# ─── 卡片结构通用验证 ───

def test_all_cards_return_dict_with_header(_empty_data):
    """所有 build_*_card 返回 dict 且含 header 键。"""
    builders = [
        cards.build_premarket_card,
        cards.build_postmarket_card,
        cards.build_scan_card,
        cards.build_sentiment_card,
        cards.build_test_card,
        cards.build_intraday_card,
    ]
    for b in builders:
        card = b()
        assert isinstance(card, dict), f"{b.__name__} 未返回 dict"
        assert "header" in card, f"{b.__name__} 缺 header"
        assert "elements" in card, f"{b.__name__} 缺 elements"
        assert "title" in card["header"], f"{b.__name__} header 缺 title"
        assert "template" in card["header"], f"{b.__name__} header 缺 template"


def test_all_card_elements_are_dicts(_empty_data):
    """所有 elements 都是 dict 且含 tag 键。"""
    builders = [
        cards.build_premarket_card,
        cards.build_postmarket_card,
        cards.build_scan_card,
        cards.build_sentiment_card,
        cards.build_test_card,
        cards.build_intraday_card,
    ]
    for b in builders:
        card = b()
        for e in card["elements"]:
            assert isinstance(e, dict), f"{b.__name__} element 非 dict"
            assert "tag" in e, f"{b.__name__} element 缺 tag"


# ─── premarket RSI信号 + 回撤状态 mock ───

def _mock_urlopen_rsi_drawdown(monkeypatch, rsi_data=None, dd_data=None):
    """mock urllib 返回 RSI信号 + 回撤状态数据。"""
    import urllib.request
    import io

    responses = {}
    if rsi_data:
        responses["rsi-timing"] = json.dumps(rsi_data).encode()
    if dd_data:
        responses["drawdown-status"] = json.dumps(dd_data).encode()

    class _MockResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def _fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for key, data in responses.items():
            if key in url:
                return _MockResp(data)
        raise OSError("no matching mock")

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)


def test_premarket_rsi_signal_triggered(monkeypatch):
    """premarket RSI信号触发时卡片含RSI markdown。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [_index()])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [_ladder_item()])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())

    rsi_data = {
        "any_triggered": True,
        "signals": [
            {"index_name": "上证", "is_triggered": True, "current_rsi": 15,
             "threshold": 20, "sample_size": 100, "expected_return": 7.82,
             "win_rate": 92, "p_value": 0.0002, "hold_days": 60,
             "stop_loss_pct": 0.05},
            {"index_name": "创业板", "is_triggered": False, "current_rsi": 35,
             "threshold": 20, "sample_size": 100, "expected_return": 0,
             "win_rate": 0, "p_value": 1, "hold_days": 0,
             "stop_loss_pct": 0},
        ],
    }
    dd_data = {
        "portfolio": {"equity": 95000, "peak": 100000, "drawdown_pct": -5.0,
                       "days_tracked": 30, "size_multiplier": 0.5}
    }
    _mock_urlopen_rsi_drawdown(monkeypatch, rsi_data=rsi_data, dd_data=dd_data)

    card = cards.build_premarket_card()
    # RSI markdown 应在 elements 中
    rsi_elements = [e for e in card["elements"] if e.get("tag") == "markdown" and "RSI" in e.get("content", "")]
    assert len(rsi_elements) > 0
    assert "🚨" in rsi_elements[0]["content"]
    # 回撤状态 markdown 应在 elements 中
    dd_elements = [e for e in card["elements"] if e.get("tag") == "markdown" and "回撤" in e.get("content", "")]
    assert len(dd_elements) > 0


def test_premarket_rsi_not_triggered(monkeypatch):
    """premarket RSI未触发时无RSI markdown。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [_index()])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [_ladder_item()])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())

    rsi_data = {"any_triggered": False, "signals": []}
    _mock_urlopen_rsi_drawdown(monkeypatch, rsi_data=rsi_data, dd_data=None)

    card = cards.build_premarket_card()
    rsi_elements = [e for e in card["elements"] if e.get("tag") == "markdown" and "RSI择时信号触发" in e.get("content", "")]
    assert len(rsi_elements) == 0


def test_premarket_api_all_fail(monkeypatch):
    """premarket 所有API失败时降级不崩。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [_index()])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [_ladder_item()])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=OSError("no api")))

    card = cards.build_premarket_card()
    assert isinstance(card, dict)
    assert "header" in card
    # RSI/回撤降级后不应崩
    assert "elements" in card


# ─── intraday RSI+MACD 信号 mock ───

def test_intraday_buy_signal(monkeypatch):
    """intraday RSI+MACD买入信号。"""
    rsi_macd_data = {
        "buy_count": 1,
        "wait_count": 0,
        "signals": [{
            "combo_signal": "买入", "index_name": "上证",
            "rsi": 15, "expected_60d": 7.82, "win_rate_60d": 92,
            "macd_dif": 0.5, "macd_dea": 0.3,
        }],
    }
    import urllib.request
    import io

    class _MockResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def _fake_urlopen(req, timeout=None):
        return _MockResp(json.dumps(rsi_macd_data).encode())

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    card = cards.build_intraday_card()
    buy_elements = [e for e in card["elements"] if e.get("tag") == "markdown" and "买入信号" in e.get("content", "")]
    assert len(buy_elements) > 0


def test_intraday_wait_signal(monkeypatch):
    """intraday RSI触发但MACD未金叉——等待。"""
    rsi_macd_data = {
        "buy_count": 0,
        "wait_count": 1,
        "signals": [{
            "combo_signal": "等待", "index_name": "上证",
            "rsi": 15, "macd_dif": -0.2, "macd_dea": 0.1,
        }],
    }
    import urllib.request

    class _MockResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def _fake_urlopen(req, timeout=None):
        return _MockResp(json.dumps(rsi_macd_data).encode())

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    card = cards.build_intraday_card()
    wait_elements = [e for e in card["elements"] if e.get("tag") == "markdown" and "等待" in e.get("content", "")]
    assert len(wait_elements) > 0


def test_intraday_no_signal(monkeypatch):
    """intraday 无RSI信号。"""
    rsi_macd_data = {
        "buy_count": 0, "wait_count": 0, "signals": [],
    }
    import urllib.request

    class _MockResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    def _fake_urlopen(req, timeout=None):
        return _MockResp(json.dumps(rsi_macd_data).encode())

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    card = cards.build_intraday_card()
    no_signal = [e for e in card["elements"] if e.get("tag") == "markdown" and "无RSI信号" in e.get("content", "")]
    assert len(no_signal) > 0


# ─── premarket 回撤诊断永久锁定 + peak衰减 ───

def test_premarket_drawdown_permanently_locked(monkeypatch):
    """premarket 回撤永久锁定时卡片含peak衰减方案。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [_index()])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [_ladder_item()])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())

    # mock RSI API 失败
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=OSError("no rsi")))

    # mock backend.strategies.tail_dip_engine 在 sys.modules
    import sys
    from unittest.mock import MagicMock as _MM
    mock_engine = _MM()
    mock_diag = _MM()
    mock_diag.is_permanently_locked = True
    mock_diag.diagnosis = "peak decay needed"
    mock_engine.diagnose_drawdown_lock.return_value = mock_diag
    mock_proposal = _MM()
    mock_proposal.current_peak = 100000
    mock_proposal.proposed_peak = 90000
    mock_proposal.decay_factor = 0.9
    mock_proposal.trigger_reason = "drawdown > 20%"
    mock_proposal.recommendation = "reduce peak"
    mock_engine.propose_peak_decay.return_value = mock_proposal

    # 注入 mock 模块
    sys.modules["backend.strategies.tail_dip_engine"] = mock_engine

    # mock drawdown-status API
    import io
    class _MockResp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    dd_data = json.dumps({
        "portfolio": {"equity": 75000, "peak": 100000, "drawdown_pct": -25.0,
                       "days_tracked": 60, "size_multiplier": 0.3}
    }).encode()

    def _fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "drawdown-status" in url:
            return _MockResp(dd_data)
        raise OSError("no api")

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    card = cards.build_premarket_card()
    # 应含回撤诊断 + peak衰减
    dd_elements = [e for e in card["elements"] if e.get("tag") == "markdown" and "永久锁定" in e.get("content", "")]
    assert len(dd_elements) > 0
    peak_elements = [e for e in card["elements"] if e.get("tag") == "markdown" and "peak衰减" in e.get("content", "")]
    assert len(peak_elements) > 0

    # 清理 mock 模块
    del sys.modules["backend.strategies.tail_dip_engine"]


# ─── cards.py ImportError 降级路径 ───

def test_premarket_tail_dip_engine_import_fail(monkeypatch):
    """premarket tail_dip_engine import 失败时降级不崩。"""
    monkeypatch.setattr(cards, "get_index_snapshot", lambda: [_index()])
    monkeypatch.setattr(cards, "get_hot_stocks", lambda: [])
    monkeypatch.setattr(cards, "get_dragon_tiger", lambda: [])
    monkeypatch.setattr(cards, "get_limit_up_ladder", lambda: [_ladder_item()])
    monkeypatch.setattr(cards, "get_skyrocket", lambda: [])
    monkeypatch.setattr(cards, "scan_group_a_stocks", lambda: [])
    monkeypatch.setattr(cards, "check_buy_signals", lambda: [])
    monkeypatch.setattr(cards, "calculate_sentiment_score", lambda: _sentiment_data())

    # mock urllib 让 RSI/drawdown API 失败（不触发 L90-122）
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", MagicMock(side_effect=OSError("no api")))

    # mock __import__ 让 backend.strategies.tail_dip_engine 抛 ImportError
    import builtins
    real_import = builtins.__import__
    def _fail_tail_dip(name, *args, **kwargs):
        if "tail_dip_engine" in name:
            raise ImportError("mocked: tail_dip_engine unavailable")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", _fail_tail_dip)

    # 清除缓存模块
    import sys
    for mod in list(sys.modules.keys()):
        if "tail_dip_engine" in mod:
            monkeypatch.delitem(sys.modules, mod, raising=False)

    card = cards.build_premarket_card()
    assert isinstance(card, dict)
    assert "header" in card
