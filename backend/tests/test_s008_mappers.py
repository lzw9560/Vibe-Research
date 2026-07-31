"""S008 data/mappers.py 单元测（纯函数，全离线）。

验证 raw dict → S007 模型字段对齐 + 单位转换 + 合规剥离。
"""
from models import Market
from models.fund_flow import FundFlow
from models.market_snapshot import Emotion, MarketSnapshot, Sector
from models.quote import Quote

from data import mappers


# ── quote_from_tencent ───────────────────────────────────────────────────

def test_quote_from_tencent_field_alignment():
    raw = {
        "name": "贵州茅台",
        "price": 1700.0,
        "change_pct": 2.34,
        "change_amt": 38.8,
        "amount_wan": 123456.0,  # 万元
        "turnover_pct": 0.5,
        "amplitude_pct": 3.2,
        "mcap_yi": 21356.0,  # 亿元
        "float_mcap_yi": 21300.0,
        "pe_ttm": 30.0,
        "pb": 10.0,
        "limit_up": 1870.0,
        "limit_down": 1530.0,
    }
    q = mappers.quote_from_tencent("600519", raw)
    assert isinstance(q, Quote)
    assert q.code == "600519"
    assert q.market == Market.A
    assert q.price == 1700.0
    assert q.change_pct == 2.34
    assert q.change_amount == 38.8  # rename change_amt→change_amount
    assert q.market_cap == 21356.0 * 1e8  # 亿→元
    assert q.float_market_cap == 21300.0 * 1e8
    assert q.turnover == 123456.0 * 1e4  # 万→元
    assert q.turnover_rate == 0.5  # rename
    assert q.amplitude == 3.2  # rename
    assert q.limit_up_price == 1870.0  # rename
    assert q.limit_down_price == 1530.0  # rename
    # 派生属性
    assert q.market_cap_yi == 21356.0


def test_quote_from_tencent_dash_values_become_none():
    """停牌字段 '-' → None。"""
    raw = {"name": "停牌股", "price": "-", "mcap_yi": "-"}
    q = mappers.quote_from_tencent("000001", raw)
    assert q.price is None
    assert q.market_cap is None


def test_quote_from_turnover_rank():
    raw = {
        "code": "600519", "name": "贵州茅台", "price": 1700.0,
        "pct": 2.3, "amount": 5e9, "mcap": 2.1356e12, "float_cap": 2.13e12,
    }
    q = mappers.quote_from_turnover_rank(raw)
    assert q.code == "600519"
    assert q.market == Market.A
    assert q.change_pct == 2.3  # pct→change_pct
    assert q.market_cap == 2.1356e12  # 已是元
    assert q.float_market_cap == 2.13e12


def test_quote_from_gstock_us_hk_flattens():
    raw = {
        "code": "AAPL", "name": "Apple", "market": "US",
        "quote": {"price": 190.0, "change_pct": 1.2, "amount": 1e10, "mcap": 3e12},
        "metrics": {"eps": 6.0},
    }
    q = mappers.quote_from_gstock_us_hk(raw)
    assert q.code == "AAPL"
    assert q.market == Market.US
    assert q.price == 190.0
    assert q.change_pct == 1.2
    assert q.market_cap == 3e12


def test_quote_from_gstock_hk():
    raw = {"code": "00700", "name": "腾讯", "market": "HK",
           "quote": {"price": 300.0, "change_pct": -0.5}}
    q = mappers.quote_from_gstock_us_hk(raw)
    assert q.market == Market.HK
    assert q.change_pct == -0.5


# ── fundflow_from_capital_flow ────────────────────────────────────────────

def test_fundflow_from_capital_flow_renames():
    raw = {
        "date": "2026-07-30", "main_net": 1e8,
        "super_net": 5e7, "large_net": 3e7, "mid_net": 2e7, "small_net": -1e7,
    }
    ff = mappers.fundflow_from_capital_flow(raw, code="600519", market="A")
    assert isinstance(ff, FundFlow)
    assert ff.code == "600519"
    assert ff.market == Market.A
    assert ff.super_large_net == 5e7  # super_net→super_large_net
    assert ff.medium_net == 2e7  # mid_net→medium_net
    assert ff.small_net == -1e7


# ── emotion_from_dict 合规剥离 ───────────────────────────────────────────

def test_emotion_from_dict_stocks_lianban_stocks():
    """合规：lianban_stocks 必须被剥离，不进 Emotion。"""
    raw = {
        "date": "2026-07-30", "zt_count": 35, "dt_count": 2,
        "max_boards": 5, "seal_rate": 70.0, "break_rate": 15.0,
        "promotion_rate": 40.0,
        "ladder": [{"boards": 2, "count": 8}, {"boards": 3, "count": 3}],
        "lianban_stocks": [
            {"code": "000506", "name": "中成股份", "boards": 3, "price": 10.0, "pct": 9.98},
            {"code": "600722", "name": "金牛化工", "boards": 2, "price": 5.0, "pct": 10.0},
        ],
    }
    emo = mappers.emotion_from_dict(raw)
    assert isinstance(emo, Emotion)
    assert emo.max_boards == 5
    assert emo.limit_up_count == 35
    assert emo.limit_down_count == 2
    assert emo.seal_rate == 70.0
    assert emo.broken_rate == 15.0
    assert emo.advance_rate == 40.0
    assert len(emo.ladder) == 2
    assert emo.ladder[0] == {"boards": 2, "count": 8}
    # 合规核心：Emotion 模型无 lianban_stocks 字段，mapper 不携带个股名
    assert not hasattr(emo, "lianban_stocks")
    dumped = emo.model_dump()
    assert "lianban_stocks" not in dumped
    assert all("name" not in item for item in dumped["ladder"])


def test_emotion_from_dict_empty():
    emo = mappers.emotion_from_dict({})
    assert emo.max_boards is None
    assert emo.ladder == ()


# ── sector + market_snapshot ──────────────────────────────────────────────

def test_sector_from_dict():
    raw = {"name": "半导体", "pct": 2.1, "net": 5e8, "inflow": 1e9, "outflow": 5e8, "firms": 150}
    s = mappers.sector_from_dict(raw)
    assert isinstance(s, Sector)
    assert s.name == "半导体"
    assert s.pct == 2.1
    assert s.net == 5e8
    assert s.firms == 150


def test_market_snapshot_from_overview():
    raw = {
        "updated": "2026-07-30T15:00:00+08:00",
        "emotion": {"zt_count": 35, "seal_rate": 70.0, "ladder": [{"boards": 2, "count": 8}]},
        "sectors": [{"name": "半导体", "pct": 2.1}],
    }
    snap = mappers.market_snapshot_from_overview(raw)
    assert isinstance(snap, MarketSnapshot)
    assert snap.emotion is not None
    assert snap.emotion.limit_up_count == 35
    assert len(snap.sectors) == 1
    assert snap.sectors[0].name == "半导体"
    assert snap.updated == "2026-07-30T15:00:00+08:00"


def test_market_snapshot_no_emotion():
    snap = mappers.market_snapshot_from_overview({"sectors": [], "updated": "x"})
    assert snap.emotion is None
    assert snap.sectors == ()


# ── legacy 投影方向（数据总线设计）────────────────────────────────────────
# legacy 消费者直接吃 sources 的 raw dict（全字段），不走 model→dict 往返。
# 故 mappers 不提供 legacy_quote_dict——避免有损往返丢 last_close/open/vol_ratio。
# 详见 specs/S008-后端数据层迁移/plan-stage1.md。

def test_mappers_no_legacy_round_trip_helper():
    """mappers 不应有 legacy_quote_dict（有损往返），legacy 走 sources raw。"""
    assert not hasattr(mappers, "legacy_quote_dict")
