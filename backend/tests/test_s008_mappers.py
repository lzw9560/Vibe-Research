"""S008 data/mappers.py 单元测（纯函数，全离线）。

验证 raw dict → S007 模型字段对齐 + 单位转换 + 合规剥离。
"""
from models import Market
from models.fund_flow import FundFlow
from models.market_snapshot import Emotion, MarketSnapshot, Sector
from models.quote import Quote
from models.valuation import Valuation

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


def test_quote_from_tencent_zero_coerced_fields_become_none():
    """S121：num() 把空字段归一成 0.0（亏损股 PE/停牌 price），quote_from_tencent
    对 0 永不合法字段归 None（防 LLM 见 PE=0/PB=0/price=0 当真，触 §1.2 不臆造）。"""
    raw = {
        "name": "亏损股",
        "price": 0.0,         # num() 空归一 → 0 永不合法 → None
        "last_close": 15.3,   # 真值保留
        "pe_ttm": 0.0,        # 亏损 PE 未定义 → 0 永不合法 → None
        "pb": 0.0,            # → None
        "pe_static": 0.0,     # → None
        "mcap_yi": 0.0,       # market_cap=0 永不合法 → None
        "float_mcap_yi": 0.0,  # → None
        "limit_up": 0.0,      # → None
        "limit_down": 0.0,    # → None
        "open": 0.0, "high": 0.0, "low": 0.0,  # → None
    }
    q = mappers.quote_from_tencent("600519", raw)
    # 0 永不合法字段 → None（非 0.0 喂 LLM）
    assert q.price is None            # price=0 与 last_close=15.3 矛盾 → price=None
    assert q.pe_ttm is None
    assert q.pb is None
    assert q.pe_static is None
    assert q.market_cap is None
    assert q.float_market_cap is None
    assert q.limit_up_price is None
    assert q.limit_down_price is None
    assert q.open is None and q.high is None and q.low is None
    # 真值保留
    assert q.last_close == 15.3


def test_quote_from_tencent_zero_legit_fields_stay_zero():
    """S121：0 合法字段（平盘 change_pct=0 / 停牌 volume=0 / 平盘 amplitude=0）保留 0.0。"""
    raw = {
        "name": "平盘股",
        "price": 15.3,
        "change_pct": 0.0,      # 0 合法（平盘）→ 保留
        "change_amt": 0.0,      # 0 合法 → 保留
        "amplitude_pct": 0.0,   # 0 合法（high==low）→ 保留
        "vol_ratio": 0.0,       # 0 合法 → 保留
        "turnover_pct": 0.0,   # 0 合法 → 保留
    }
    q = mappers.quote_from_tencent("600519", raw)
    assert q.change_pct == 0.0
    assert q.change_amount == 0.0
    assert q.amplitude == 0.0
    assert q.vol_ratio == 0.0
    assert q.turnover_rate == 0.0


def test_quote_from_tencent_real_values_unchanged():
    """S121：真正值不受 `or None` 影响（19.92 or None == 19.92）。"""
    raw = {
        "name": "茅台", "price": 1700.0, "last_close": 1661.16,
        "pe_ttm": 19.92, "pb": 6.46, "pe_static": 20.5,
        "mcap_yi": 18800.0, "float_mcap_yi": 18700.0,
        "limit_up": 1870.0, "limit_down": 1530.0,
        "open": 1665.0, "high": 1710.0, "low": 1655.0,
    }
    q = mappers.quote_from_tencent("600519", raw)
    assert q.price == 1700.0
    assert q.pe_ttm == 19.92
    assert q.pb == 6.46
    assert q.pe_static == 20.5
    assert q.market_cap == 18800.0 * 1e8
    assert q.limit_up_price == 1870.0
    assert q.high == 1710.0


# ── valuation_from_full_valuation ────────────────────────────────────────

def test_valuation_from_full_valuation_zero_coerced_fields_become_none():
    """S125 R2：PE/PB/PS/PCF/price/market_cap/forward_pe=0 永不合法（S121 契约补全），
    0→None 防 LLM 见 PE=0/price=0/市值=0 当真低估。对齐 quote_from_tencent:62-87。"""
    # Arrange — input 用 mapper 读取的键名（pe_26e/eps_26e，非 output 字段名 forward_pe/consensus_eps）
    raw = {
        "name": "亏损股",
        "price": 0.0,       # 0 永不合法 → None（S125 契约补全）
        "mcap_yi": 0.0,     # 0 永不合法 → None（市值=0 喂 LLM 当真低估）
        "pe_ttm": 0.0,      # 亏损 PE 未定义 → None
        "pb": 0.0,          # → None
        "ps_ttm": 0.0,      # → None
        "pcf_ttm": 0.0,     # → None
        "pe_26e": 0.0,      # forward PE 0 永不合法 → None（S125 契约补全）
        # 0 合法字段保留 0.0（EPS=0 真平仓/无分红/无增长/PEG 无 E 非真 0）
        "eps_26e": 0.0,     # consensus_eps：EPS=0 合法（盈亏平衡），不 coerce
        "dividend_yield": 0.0,
        "cagr_pct": 0.0,
        "peg": 0.0,
    }
    # Act
    v = mappers.valuation_from_full_valuation("600519", raw)
    # Assert — 0 永不合法字段 → None（非 0.0 喂 LLM）
    assert isinstance(v, Valuation)
    assert v.price is None
    assert v.market_cap is None
    assert v.pe_ttm is None
    assert v.pb is None
    assert v.ps_ttm is None
    assert v.pcf_ttm is None
    assert v.forward_pe is None
    # Assert — 0 合法字段保留 0.0（EPS/分红/增长/PEG）
    assert v.dividend_yield == 0.0
    assert v.consensus_eps == 0.0
    assert v.cagr_pct == 0.0
    assert v.peg == 0.0


def test_valuation_from_full_valuation_real_values_unchanged():
    """S125 R2：真正值不受 `or None` 影响（19.92 or None == 19.92）。"""
    # Arrange
    raw = {
        "name": "茅台", "price": 1700.0, "mcap_yi": 18800.0,
        "pe_ttm": 19.92, "pb": 6.46, "ps_ttm": 12.5, "pcf_ttm": 8.3,
    }
    # Act
    v = mappers.valuation_from_full_valuation("600519", raw)
    # Assert — 真值原样透传
    assert v.pe_ttm == 19.92
    assert v.pb == 6.46
    assert v.ps_ttm == 12.5
    assert v.pcf_ttm == 8.3
    assert v.price == 1700.0
    assert v.market_cap == 18800.0 * 1e8


def test_valuation_from_full_valuation_missing_fields_become_none():
    """S125 R2：缺失字段（key 不在 raw）→ _numf(None) → None。"""
    # Act
    v = mappers.valuation_from_full_valuation("600519", {"name": "新股"})
    # Assert — 缺失归 None（非 0）
    assert v.pe_ttm is None
    assert v.pb is None
    assert v.ps_ttm is None
    assert v.pcf_ttm is None
    assert v.price is None
    assert v.market_cap is None


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


def test_quote_from_gstock_us_hk_passes_is_delayed():
    """S135：push2delay 延时标记从 inner.quote 透传到 Quote.is_delayed（不撒谎把延时当实时）。"""
    raw_delayed = {"code": "AAPL", "name": "Apple", "market": "US",
                   "quote": {"price": 190.0, "change_pct": 1.2, "is_delayed": True}}
    raw_live = {"code": "AAPL", "name": "Apple", "market": "US",
                "quote": {"price": 190.0, "change_pct": 1.2, "is_delayed": False}}
    raw_missing = {"code": "AAPL", "name": "Apple", "market": "US",
                   "quote": {"price": 190.0, "change_pct": 1.2}}
    assert mappers.quote_from_gstock_us_hk(raw_delayed).is_delayed is True
    assert mappers.quote_from_gstock_us_hk(raw_live).is_delayed is False
    assert mappers.quote_from_gstock_us_hk(raw_missing).is_delayed is False  # 缺键默认 False（非延时）


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
