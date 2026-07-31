"""S007 契约层 T1-T3 切片测试：enums / normalize / Quote 模型。"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from models import Quote
from models.enums import Market, ReportType, STIPhase
from models.normalize import normalize_stock_code


# ── T1 · enums ────────────────────────────────────────────────────────────

class TestEnums:
    def test_market_values(self):
        assert Market.A == "A"
        assert Market.US == "US"
        assert Market.HK == "HK"
        assert Market.KR == "KR"

    def test_report_type_values(self):
        assert ReportType.BUY == "买入"
        assert ReportType.OVERWEIGHT == "增持"
        assert ReportType.NEUTRAL == "中性"
        assert ReportType.UNDERWEIGHT == "减持"
        assert ReportType.SELL == "卖出"

    def test_sti_phase_values(self):
        assert STIPhase.HIGH == "高潮"
        assert STIPhase.START == "启动"
        assert STIPhase.DIVERGE == "分歧"
        assert STIPhase.LOW == "冰点"
        assert STIPhase.EBB == "退潮"


# ── T2 · normalize_stock_code ──────────────────────────────────────────────

class TestNormalize:
    def test_a_share_6digit(self):
        assert normalize_stock_code("600519") == ("600519", Market.A)
        assert normalize_stock_code("000858") == ("000858", Market.A)
        assert normalize_stock_code("300750") == ("300750", Market.A)

    def test_hk_5digit(self):
        assert normalize_stock_code("00700") == ("00700", Market.HK)

    def test_us_ticker(self):
        assert normalize_stock_code("AAPL") == ("AAPL", Market.US)
        assert normalize_stock_code("TSLA") == ("TSLA", Market.US)

    def test_kr_with_suffix(self):
        assert normalize_stock_code("005930.KS") == ("005930", Market.KR)

    def test_kr_without_suffix_defaults_to_a(self):
        # 6 位纯数字无后缀，按 spec 默认 A 股（韩股识别依赖 .KS）
        assert normalize_stock_code("005930") == ("005930", Market.A)

    def test_invalid_empty(self):
        with pytest.raises(ValueError):
            normalize_stock_code("")

    def test_invalid_none(self):
        with pytest.raises(ValueError):
            normalize_stock_code(None)  # type: ignore[arg-type]


# ── T3 · Quote 模型 ───────────────────────────────────────────────────────

class TestQuote:
    def test_quote_minimal_valid(self):
        q = Quote(code="600519", market=Market.A, price=1680.5)
        assert q.code == "600519"
        assert q.market == Market.A
        assert q.price == 1680.5
        assert q.name is None
        assert q.change_pct is None

    def test_quote_full_valid(self):
        q = Quote(
            code="600519",
            market=Market.A,
            name="贵州茅台",
            price=1680.5,
            change_pct=2.34,
            change_amount=38.5,
            volume=12345,
            turnover=1_000_000_000.0,
            market_cap=2_100_000_000_000.0,
            float_market_cap=2_100_000_000_000.0,
            pe_ttm=28.5,
            pb=8.2,
            turnover_rate=0.35,
            amplitude=3.12,
            limit_up_price=1800.0,
            limit_down_price=1600.0,
            updated_at="2026-07-29T15:05:00+08:00",
        )
        assert q.code == "600519"
        assert q.name == "贵州茅台"
        assert q.market_cap_yi == pytest.approx(21000.0)

    def test_quote_missing_required_code(self):
        with pytest.raises(ValidationError) as exc:
            Quote(market=Market.A, price=100.0)
        assert "code" in str(exc.value)

    def test_quote_missing_required_market(self):
        with pytest.raises(ValidationError) as exc:
            Quote(code="600519", price=100.0)
        assert "market" in str(exc.value)

    def test_quote_missing_required_price(self):
        with pytest.raises(ValidationError) as exc:
            Quote(code="600519", market=Market.A)
        assert "price" in str(exc.value)

    def test_quote_frozen_cannot_mutate(self):
        q = Quote(code="600519", market=Market.A, price=1680.5)
        with pytest.raises(ValidationError):
            q.price = 1700.0

    def test_quote_round_trip_serialization(self):
        original = {
            "code": "600519",
            "market": "A",
            "name": "贵州茅台",
            "price": 1680.5,
            "change_pct": 2.34,
            "change_amount": 38.5,
            "volume": 12345,
            "turnover": 1_000_000_000.0,
            "market_cap": 2_100_000_000_000.0,
            "float_market_cap": 2_100_000_000_000.0,
            "pe_ttm": 28.5,
            "pb": 8.2,
            "turnover_rate": 0.35,
            "amplitude": 3.12,
            "limit_up_price": 1800.0,
            "limit_down_price": 1600.0,
            "updated_at": "2026-07-29T15:05:00+08:00",
        }
        q = Quote.model_validate(original)
        dumped = q.model_dump()
        assert dumped["code"] == "600519"
        assert dumped["market"] == "A"
        assert dumped["name"] == "贵州茅台"
        assert dumped["price"] == 1680.5
        assert dumped["change_pct"] == 2.34
        assert dumped["change_amount"] == 38.5
        assert dumped["volume"] == 12345
        assert dumped["turnover"] == 1_000_000_000.0
        assert dumped["market_cap"] == 2_100_000_000_000.0
        assert dumped["float_market_cap"] == 2_100_000_000_000.0
        assert dumped["pe_ttm"] == 28.5
        assert dumped["pb"] == 8.2
        assert dumped["turnover_rate"] == 0.35
        assert dumped["amplitude"] == 3.12
        assert dumped["limit_up_price"] == 1800.0
        assert dumped["limit_down_price"] == 1600.0
        assert dumped["updated_at"] == "2026-07-29T15:05:00+08:00"

    def test_quote_market_cap_yi_when_none(self):
        q = Quote(code="600519", market=Market.A, price=100.0, market_cap=None)
        assert q.market_cap_yi is None

    def test_quote_market_cap_yi_derived(self):
        q = Quote(code="600519", market=Market.A, price=100.0, market_cap=2_100_000_000_000.0)
        assert q.market_cap_yi == pytest.approx(21000.0)


# ── T4 · Valuation 模型 ───────────────────────────────────────────────────

class TestValuation:
    def test_valuation_minimal_valid(self):
        from models import Valuation

        v = Valuation(code="600519", market=Market.A)
        assert v.code == "600519"
        assert v.market == Market.A
        assert v.name is None
        assert v.pe_ttm is None

    def test_valuation_full_valid(self):
        from models import Valuation

        v = Valuation(
            code="600519",
            market=Market.A,
            name="贵州茅台",
            price=1680.5,
            market_cap=2_100_000_000_000.0,
            pe_ttm=28.5,
            pb=8.2,
            ps_ttm=6.8,
            dividend_yield=1.35,
            peg=1.12,
            forward_pe=25.3,
            consensus_eps=66.4,
            cagr_pct=15.0,
            digest_years=3.5,
            analyst_count=42,
            updated_at="2026-07-29T15:05:00+08:00",
        )
        assert v.code == "600519"
        assert v.name == "贵州茅台"
        assert v.pe_ttm == 28.5
        assert v.pb == 8.2
        assert v.ps_ttm == 6.8
        assert v.dividend_yield == 1.35
        assert v.peg == 1.12
        assert v.forward_pe == 25.3
        assert v.consensus_eps == 66.4
        assert v.cagr_pct == 15.0
        assert v.digest_years == 3.5
        assert v.analyst_count == 42

    def test_valuation_missing_required_code(self):
        from models import Valuation

        with pytest.raises(ValidationError) as exc:
            Valuation(market=Market.A)
        assert "code" in str(exc.value)

    def test_valuation_missing_required_market(self):
        from models import Valuation

        with pytest.raises(ValidationError) as exc:
            Valuation(code="600519")
        assert "market" in str(exc.value)

    def test_valuation_frozen_cannot_mutate(self):
        from models import Valuation

        v = Valuation(code="600519", market=Market.A)
        with pytest.raises(ValidationError):
            v.pe_ttm = 30.0

    def test_valuation_round_trip_serialization(self):
        from models import Valuation

        original = {
            "code": "600519",
            "market": "A",
            "name": "贵州茅台",
            "price": 1680.5,
            "market_cap": 2_100_000_000_000.0,
            "pe_ttm": 28.5,
            "pb": 8.2,
            "ps_ttm": 6.8,
            "dividend_yield": 1.35,
            "peg": 1.12,
            "forward_pe": 25.3,
            "consensus_eps": 66.4,
            "cagr_pct": 15.0,
            "digest_years": 3.5,
            "analyst_count": 42,
            "updated_at": "2026-07-29T15:05:00+08:00",
        }
        v = Valuation.model_validate(original)
        dumped = v.model_dump()
        assert dumped["code"] == "600519"
        assert dumped["market"] == "A"
        assert dumped["name"] == "贵州茅台"
        assert dumped["price"] == 1680.5
        assert dumped["market_cap"] == 2_100_000_000_000.0
        assert dumped["pe_ttm"] == 28.5
        assert dumped["pb"] == 8.2
        assert dumped["ps_ttm"] == 6.8
        assert dumped["dividend_yield"] == 1.35
        assert dumped["peg"] == 1.12
        assert dumped["forward_pe"] == 25.3
        assert dumped["consensus_eps"] == 66.4
        assert dumped["cagr_pct"] == 15.0
        assert dumped["digest_years"] == 3.5
        assert dumped["analyst_count"] == 42
        assert dumped["updated_at"] == "2026-07-29T15:05:00+08:00"

    def test_valuation_optional_fields_default_to_none(self):
        from models import Valuation

        v = Valuation(code="000858", market=Market.A)
        assert v.price is None
        assert v.pe_ttm is None
        assert v.pb is None
        assert v.ps_ttm is None
        assert v.dividend_yield is None
        assert v.peg is None
        assert v.forward_pe is None
        assert v.consensus_eps is None
        assert v.cagr_pct is None
        assert v.digest_years is None
        assert v.analyst_count is None
        assert v.updated_at is None


# ── T5 · KLine 模型 ────────────────────────────────────────────────────────

class TestKLine:
    def test_kline_minimal_valid(self):
        from models import KLine

        kl = KLine(code="600519", market=Market.A)
        assert kl.code == "600519"
        assert kl.market == Market.A
        assert kl.bars == ()

    def test_kline_with_bars(self):
        from models import KLine, KLineBar

        kl = KLine(
            code="600519",
            market=Market.A,
            bars=[
                KLineBar(
                    date="2026-07-28",
                    open=1600.0,
                    close=1650.0,
                    high=1660.0,
                    low=1590.0,
                    volume=50000,
                    turnover=800_000_000.0,
                    amplitude=4.38,
                ),
                KLineBar(
                    date="2026-07-29",
                    open=1650.0,
                    close=1680.5,
                    high=1690.0,
                    low=1640.0,
                    volume=48000,
                    turnover=780_000_000.0,
                    amplitude=3.03,
                ),
            ],
        )
        assert kl.code == "600519"
        assert len(kl.bars) == 2
        assert kl.bars[0].date == "2026-07-28"
        assert kl.bars[0].open == 1600.0
        assert kl.bars[0].close == 1650.0
        assert kl.bars[0].high == 1660.0
        assert kl.bars[0].low == 1590.0
        assert kl.bars[0].volume == 50000
        assert kl.bars[0].turnover == 800_000_000.0
        assert kl.bars[0].amplitude == 4.38
        assert kl.bars[1].date == "2026-07-29"
        assert kl.bars[1].close == 1680.5

    def test_kline_bar_defaults(self):
        from models import KLineBar

        bar = KLineBar(
            date="2026-07-29",
            open=1600.0,
            close=1650.0,
            high=1660.0,
            low=1590.0,
        )
        assert bar.volume is None
        assert bar.turnover is None
        assert bar.amplitude is None

    def test_kline_missing_required_code(self):
        from models import KLine

        with pytest.raises(ValidationError) as exc:
            KLine(market=Market.A)
        assert "code" in str(exc.value)

    def test_kline_missing_required_market(self):
        from models import KLine

        with pytest.raises(ValidationError) as exc:
            KLine(code="600519")
        assert "market" in str(exc.value)

    def test_kline_frozen_cannot_mutate(self):
        from models import KLine

        kl = KLine(code="600519", market=Market.A)
        with pytest.raises(ValidationError):
            kl.code = "000858"

    def test_kline_bar_frozen_cannot_mutate(self):
        from models import KLineBar

        bar = KLineBar(date="2026-07-29", open=1600.0, close=1650.0, high=1660.0, low=1590.0)
        with pytest.raises(ValidationError):
            bar.close = 1700.0

    def test_kline_round_trip_serialization(self):
        from models import KLine

        original = {
            "code": "600519",
            "market": "A",
            "bars": [
                {
                    "date": "2026-07-28",
                    "open": 1600.0,
                    "close": 1650.0,
                    "high": 1660.0,
                    "low": 1590.0,
                    "volume": 50000,
                    "turnover": 800_000_000.0,
                    "amplitude": 4.38,
                },
                {
                    "date": "2026-07-29",
                    "open": 1650.0,
                    "close": 1680.5,
                    "high": 1690.0,
                    "low": 1640.0,
                    "volume": 48000,
                    "turnover": 780_000_000.0,
                    "amplitude": 3.03,
                },
            ],
        }
        kl = KLine.model_validate(original)
        dumped = kl.model_dump()
        assert dumped["code"] == "600519"
        assert dumped["market"] == "A"
        assert len(dumped["bars"]) == 2
        assert dumped["bars"][0]["date"] == "2026-07-28"
        assert dumped["bars"][0]["open"] == 1600.0
        assert dumped["bars"][0]["close"] == 1650.0
        assert dumped["bars"][0]["high"] == 1660.0
        assert dumped["bars"][0]["low"] == 1590.0
        assert dumped["bars"][0]["volume"] == 50000
        assert dumped["bars"][0]["turnover"] == 800_000_000.0
        assert dumped["bars"][0]["amplitude"] == 4.38
        assert dumped["bars"][1]["date"] == "2026-07-29"
        assert dumped["bars"][1]["close"] == 1680.5


# ── T6 · Report 模型 ───────────────────────────────────────────────────────

class TestReport:
    def test_report_minimal_valid(self):
        from models import Report

        r = Report(code="600519", market=Market.A)
        assert r.code == "600519"
        assert r.market == Market.A
        assert r.title is None
        assert r.org is None
        assert r.researcher is None
        assert r.publish_date is None
        assert r.report_type is None
        assert r.rating_change is None
        assert r.target_price is None
        assert r.eps_forecast is None
        assert r.updated_at is None

    def test_report_full_valid(self):
        from models import Report

        r = Report(
            code="600519",
            market=Market.A,
            title="贵州茅台深度报告",
            org="中信证券",
            researcher="张三",
            publish_date="2026-07-29",
            report_type=ReportType.BUY,
            rating_change="首次评级",
            target_price=2100.0,
            eps_forecast=66.5,
            updated_at="2026-07-29T15:05:00+08:00",
        )
        assert r.code == "600519"
        assert r.title == "贵州茅台深度报告"
        assert r.org == "中信证券"
        assert r.researcher == "张三"
        assert r.publish_date == "2026-07-29"
        assert r.report_type == ReportType.BUY
        assert r.rating_change == "首次评级"
        assert r.target_price == 2100.0
        assert r.eps_forecast == 66.5

    def test_report_missing_required_code(self):
        from models import Report

        with pytest.raises(ValidationError) as exc:
            Report(market=Market.A)
        assert "code" in str(exc.value)

    def test_report_missing_required_market(self):
        from models import Report

        with pytest.raises(ValidationError) as exc:
            Report(code="600519")
        assert "market" in str(exc.value)

    def test_report_frozen_cannot_mutate(self):
        from models import Report

        r = Report(code="600519", market=Market.A)
        with pytest.raises(ValidationError):
            r.title = "new title"

    def test_report_round_trip_serialization(self):
        from models import Report

        original = {
            "code": "600519",
            "market": "A",
            "title": "贵州茅台深度报告",
            "org": "中信证券",
            "researcher": "张三",
            "publish_date": "2026-07-29",
            "report_type": "买入",
            "rating_change": "首次评级",
            "target_price": 2100.0,
            "eps_forecast": 66.5,
            "updated_at": "2026-07-29T15:05:00+08:00",
        }
        r = Report.model_validate(original)
        dumped = r.model_dump()
        assert dumped["code"] == "600519"
        assert dumped["market"] == "A"
        assert dumped["title"] == "贵州茅台深度报告"
        assert dumped["org"] == "中信证券"
        assert dumped["researcher"] == "张三"
        assert dumped["publish_date"] == "2026-07-29"
        assert dumped["report_type"] == "买入"
        assert dumped["rating_change"] == "首次评级"
        assert dumped["target_price"] == 2100.0
        assert dumped["eps_forecast"] == 66.5
        assert dumped["updated_at"] == "2026-07-29T15:05:00+08:00"


# ── T7 · News 模型 ─────────────────────────────────────────────────────────

class TestNews:
    def test_news_minimal_valid(self):
        from models import News

        n = News(code="600519", market=Market.A)
        assert n.code == "600519"
        assert n.market == Market.A
        assert n.title is None
        assert n.content is None
        assert n.publish_time is None
        assert n.source is None
        assert n.keywords is None

    def test_news_full_valid(self):
        from models import News

        n = News(
            code="600519",
            market=Market.A,
            title="茅台业绩超预期",
            content="贵州茅台发布半年度业绩预告...",
            publish_time="2026-07-29 10:30:00",
            source="证券时报",
            keywords="茅台,白酒,业绩",
        )
        assert n.code == "600519"
        assert n.title == "茅台业绩超预期"
        assert n.content == "贵州茅台发布半年度业绩预告..."
        assert n.publish_time == "2026-07-29 10:30:00"
        assert n.source == "证券时报"
        assert n.keywords == "茅台,白酒,业绩"

    def test_news_missing_required_code(self):
        from models import News

        with pytest.raises(ValidationError) as exc:
            News(market=Market.A)
        assert "code" in str(exc.value)

    def test_news_missing_required_market(self):
        from models import News

        with pytest.raises(ValidationError) as exc:
            News(code="600519")
        assert "market" in str(exc.value)

    def test_news_frozen_cannot_mutate(self):
        from models import News

        n = News(code="600519", market=Market.A)
        with pytest.raises(ValidationError):
            n.title = "new title"

    def test_news_round_trip_serialization(self):
        from models import News

        original = {
            "code": "600519",
            "market": "A",
            "title": "茅台业绩超预期",
            "content": "贵州茅台发布半年度业绩预告...",
            "publish_time": "2026-07-29 10:30:00",
            "source": "证券时报",
            "keywords": "茅台,白酒,业绩",
        }
        n = News.model_validate(original)
        dumped = n.model_dump()
        assert dumped["code"] == "600519"
        assert dumped["market"] == "A"
        assert dumped["title"] == "茅台业绩超预期"
        assert dumped["content"] == "贵州茅台发布半年度业绩预告..."
        assert dumped["publish_time"] == "2026-07-29 10:30:00"
        assert dumped["source"] == "证券时报"
        assert dumped["keywords"] == "茅台,白酒,业绩"


# ── T8 · MarketSnapshot / Emotion / Sector 模型 ────────────────────────────

class TestEmotion:
    def test_emotion_minimal_valid(self):
        from models import Emotion

        e = Emotion()
        assert e.max_boards is None
        assert e.limit_up_count is None
        assert e.limit_down_count is None
        assert e.seal_rate is None
        assert e.broken_rate is None
        assert e.advance_rate is None
        assert e.ladder == ()

    def test_emotion_full_valid(self):
        from models import Emotion

        e = Emotion(
            max_boards=7,
            limit_up_count=45,
            limit_down_count=3,
            seal_rate=0.82,
            broken_rate=0.18,
            advance_rate=0.35,
            ladder=({"boards": 2, "count": 15}, {"boards": 3, "count": 8}),
        )
        assert e.max_boards == 7
        assert e.limit_up_count == 45
        assert e.limit_down_count == 3
        assert e.seal_rate == 0.82
        assert e.broken_rate == 0.18
        assert e.advance_rate == 0.35
        assert len(e.ladder) == 2
        assert e.ladder[0] == {"boards": 2, "count": 15}

    def test_emotion_frozen_cannot_mutate(self):
        from models import Emotion

        e = Emotion(max_boards=5)
        with pytest.raises(ValidationError):
            e.max_boards = 6

    def test_emotion_no_stock_name_fields(self):
        """合规测试：Emotion 模型不含 code/name/stock_name 字段。"""
        from models import Emotion

        fields = set(Emotion.model_fields.keys())
        assert "code" not in fields
        assert "name" not in fields
        assert "stock_name" not in fields


class TestSector:
    def test_sector_minimal_valid(self):
        from models import Sector

        s = Sector(name="白酒")
        assert s.name == "白酒"
        assert s.pct is None
        assert s.net is None
        assert s.inflow is None
        assert s.outflow is None
        assert s.firms is None

    def test_sector_full_valid(self):
        from models import Sector

        s = Sector(name="白酒", pct=2.34, net=1_000_000_000.0, inflow=5_000_000_000.0, outflow=4_000_000_000.0, firms=25)
        assert s.name == "白酒"
        assert s.pct == 2.34
        assert s.net == 1_000_000_000.0
        assert s.inflow == 5_000_000_000.0
        assert s.outflow == 4_000_000_000.0
        assert s.firms == 25

    def test_sector_frozen_cannot_mutate(self):
        from models import Sector

        s = Sector(name="白酒")
        with pytest.raises(ValidationError):
            s.pct = 3.0

    def test_sector_round_trip_serialization(self):
        from models import Sector

        original = {"name": "白酒", "pct": 2.34, "net": 1_000_000_000.0, "inflow": 5_000_000_000.0, "outflow": 4_000_000_000.0, "firms": 25}
        s = Sector.model_validate(original)
        dumped = s.model_dump()
        assert dumped["name"] == "白酒"
        assert dumped["pct"] == 2.34
        assert dumped["net"] == 1_000_000_000.0
        assert dumped["inflow"] == 5_000_000_000.0
        assert dumped["outflow"] == 4_000_000_000.0
        assert dumped["firms"] == 25


class TestMarketSnapshot:
    def test_market_snapshot_minimal_valid(self):
        from models import MarketSnapshot

        ms = MarketSnapshot()
        assert ms.emotion is None
        assert ms.sectors == ()
        assert ms.updated is None

    def test_market_snapshot_full_valid(self):
        from models import Emotion, MarketSnapshot, Sector

        ms = MarketSnapshot(
            emotion=Emotion(max_boards=7, limit_up_count=45, limit_down_count=3),
            sectors=(
                Sector(name="白酒", pct=2.34, net=1_000_000_000.0),
                Sector(name="半导体", pct=-1.23, net=-500_000_000.0),
            ),
            updated="2026-07-29T15:05:00+08:00",
        )
        assert ms.emotion is not None
        assert ms.emotion.max_boards == 7
        assert len(ms.sectors) == 2
        assert ms.sectors[0].name == "白酒"
        assert ms.sectors[1].name == "半导体"
        assert ms.updated == "2026-07-29T15:05:00+08:00"

    def test_market_snapshot_frozen_cannot_mutate(self):
        from models import MarketSnapshot

        ms = MarketSnapshot()
        with pytest.raises(ValidationError):
            ms.updated = "2026-07-30"

    def test_market_snapshot_round_trip_serialization(self):
        from models import Emotion, MarketSnapshot, Sector

        original = {
            "emotion": {
                "max_boards": 7,
                "limit_up_count": 45,
                "limit_down_count": 3,
                "seal_rate": 0.82,
                "broken_rate": 0.18,
                "advance_rate": 0.35,
                "ladder": [{"boards": 2, "count": 15}, {"boards": 3, "count": 8}],
            },
            "sectors": [
                {"name": "白酒", "pct": 2.34, "net": 1_000_000_000.0, "inflow": 5_000_000_000.0, "outflow": 4_000_000_000.0, "firms": 25},
                {"name": "半导体", "pct": -1.23, "net": -500_000_000.0, "inflow": 2_000_000_000.0, "outflow": 2_500_000_000.0, "firms": 30},
            ],
            "updated": "2026-07-29T15:05:00+08:00",
        }
        ms = MarketSnapshot.model_validate(original)
        dumped = ms.model_dump()
        assert dumped["emotion"]["max_boards"] == 7
        assert dumped["emotion"]["limit_up_count"] == 45
        assert dumped["emotion"]["limit_down_count"] == 3
        assert dumped["emotion"]["seal_rate"] == 0.82
        assert dumped["emotion"]["broken_rate"] == 0.18
        assert dumped["emotion"]["advance_rate"] == 0.35
        assert len(dumped["emotion"]["ladder"]) == 2
        assert len(dumped["sectors"]) == 2
        assert dumped["sectors"][0]["name"] == "白酒"
        assert dumped["updated"] == "2026-07-29T15:05:00+08:00"

    def test_market_snapshot_no_stock_name_in_emotion(self):
        """合规测试：MarketSnapshot.Emotion 不含 code/name/stock_name 字段。"""
        from models import Emotion

        fields = set(Emotion.model_fields.keys())
        assert "code" not in fields
        assert "name" not in fields
        assert "stock_name" not in fields

    def test_market_snapshot_sectors_tuple_immutable(self):
        """Sector tuple 字段深度不可变。"""
        from models import MarketSnapshot, Sector

        ms = MarketSnapshot(sectors=(Sector(name="白酒"),))
        assert len(ms.sectors) == 1
        with pytest.raises(TypeError):
            ms.sectors[0] = Sector(name="半导体")  # tuple 不可变


# ── T9 · FundFlow 模型 ─────────────────────────────────────────────────────

class TestFundFlow:
    def test_fund_flow_minimal_valid(self):
        from models import FundFlow

        f = FundFlow(code="600519", market=Market.A)
        assert f.code == "600519"
        assert f.market == Market.A
        assert f.date is None
        assert f.main_net is None
        assert f.super_large_net is None
        assert f.large_net is None
        assert f.medium_net is None
        assert f.small_net is None

    def test_fund_flow_full_valid(self):
        from models import FundFlow

        f = FundFlow(
            code="600519",
            market=Market.A,
            date="2026-07-29",
            main_net=1_000_000.0,
            super_large_net=500_000.0,
            large_net=300_000.0,
            medium_net=100_000.0,
            small_net=100_000.0,
        )
        assert f.code == "600519"
        assert f.date == "2026-07-29"
        assert f.main_net == 1_000_000.0
        assert f.super_large_net == 500_000.0
        assert f.large_net == 300_000.0
        assert f.medium_net == 100_000.0
        assert f.small_net == 100_000.0

    def test_fund_flow_missing_required_code(self):
        from models import FundFlow

        with pytest.raises(ValidationError) as exc:
            FundFlow(market=Market.A)
        assert "code" in str(exc.value)

    def test_fund_flow_missing_required_market(self):
        from models import FundFlow

        with pytest.raises(ValidationError) as exc:
            FundFlow(code="600519")
        assert "market" in str(exc.value)

    def test_fund_flow_frozen_cannot_mutate(self):
        from models import FundFlow

        f = FundFlow(code="600519", market=Market.A)
        with pytest.raises(ValidationError):
            f.main_net = 100.0

    def test_fund_flow_round_trip_with_fallback_json(self):
        """用 fallback JSON 真实形状做 round-trip。"""
        import json
        from pathlib import Path

        from models import FundFlow

        fallback_path = Path(__file__).parent.parent / "data" / "fallback" / "capital_flow_000045.json"
        raw = json.loads(fallback_path.read_text(encoding="utf-8"))
        items = raw.get("data", [])
        assert items, "fallback JSON 应含至少一条数据"
        first = items[0]
        original = {
            "code": "000045",
            "market": "A",
            "date": first["date"],
            "main_net": first["main_net"],
            "super_large_net": first["super_net"],
            "large_net": first["large_net"],
            "medium_net": first["mid_net"],
            "small_net": first["small_net"],
        }
        f = FundFlow.model_validate(original)
        dumped = f.model_dump()
        assert dumped["code"] == "000045"
        assert dumped["market"] == "A"
        assert dumped["date"] == first["date"]
        assert dumped["main_net"] == first["main_net"]
        assert dumped["super_large_net"] == first["super_net"]
        assert dumped["large_net"] == first["large_net"]
        assert dumped["medium_net"] == first["mid_net"]
        assert dumped["small_net"] == first["small_net"]

