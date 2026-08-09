# -*- coding: utf-8 -*-
"""S044 阶段4 单测：龙虎榜游资席位接力频次聚合（R4）+ sources/diagnosis 接入。"""
import astock
from predict.features import fund_flow as ff
from candidate_funnel.sources import fund_flow as src_ff
from candidate_funnel.diagnosis import build_indicator_set


def _seat(date: str, name: str, net):
    return {"TRADE_DATE": date, "SECURITY_CODE": "000001",
            "OPERATEDEPT_NAME": name, "NET": net, "OPERATEDEPT_CODE": "1"}


def _dc(buy, sell):
    """eastmoney_datacenter mock：按 reportName 返 buy/sell。"""
    return lambda rn, **k: buy if rn == "RPT_BILLBOARD_DAILYDETAILSBUY" else sell


class TestFetchRelay:
    def test_接力席位出现2日_合计净额万元(self, monkeypatch):
        # 游资A 2 日出现 → 接力；游资B 仅 1 日 → 非接力
        buy = [_seat("2026-07-28", "游资A", 50000000), _seat("2026-07-15", "游资A", 30000000),
               _seat("2026-07-28", "游资B", 20000000)]
        monkeypatch.setattr(astock, "eastmoney_datacenter", _dc(buy, []))
        r = ff.fetch_dt_hot_money_relay("000001", date="2026-07-28")
        assert r == round((50000000 + 30000000) / 10000, 1)  # 8000 万

    def test_有上榜无接力席位_返0(self, monkeypatch):
        buy = [_seat("2026-07-28", "游资A", 50000000)]  # 仅 1 日
        monkeypatch.setattr(astock, "eastmoney_datacenter", _dc(buy, []))
        assert ff.fetch_dt_hot_money_relay("000001", date="2026-07-28") == 0.0

    def test_无上榜记录_返None(self, monkeypatch):
        monkeypatch.setattr(astock, "eastmoney_datacenter", _dc([], []))
        assert ff.fetch_dt_hot_money_relay("000001", date="2026-07-28") is None

    def test_异常返None(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("net")
        monkeypatch.setattr(astock, "eastmoney_datacenter", boom)
        assert ff.fetch_dt_hot_money_relay("000001", date="2026-07-28") is None

    def test_买卖两侧合并聚合(self, monkeypatch):
        buy = [_seat("2026-07-28", "游资A", 40000000)]
        sell = [_seat("2026-07-15", "游资A", 20000000)]  # 同席位另一日（卖侧）
        monkeypatch.setattr(astock, "eastmoney_datacenter", _dc(buy, sell))
        # 游资A 2 日（一买一卖）→ 接力；合计 4000万+2000万=6000万
        assert ff.fetch_dt_hot_money_relay("000001", date="2026-07-28") == round(60000000 / 10000, 1)


class TestSourcesAndDiagnosis:
    def test_sources填relay字段(self, monkeypatch):
        buy = [_seat("2026-07-28", "游资A", 50000000), _seat("2026-07-15", "游资A", 30000000)]
        monkeypatch.setattr(astock, "eastmoney_datacenter", _dc(buy, []))
        monkeypatch.setattr(astock, "stock_fund_flow_120d", lambda c: [])
        monkeypatch.setattr(astock, "dragon_tiger_board", lambda c: {})
        out = src_ff.fetch_fund_flow(["000001"], "2026-07-28")
        assert out["000001"]["dragon_tiger_hot_money_relay"] == round(80000000 / 10000, 1)

    def test_diagnosis拼接relay字段(self):
        fund = {"000001": {"dragon_tiger_hot_money_relay": 8000.0}}
        ind = build_indicator_set("000001", "test", {}, {}, fund, {}, {}, {})
        assert ind.dragon_tiger_hot_money_relay == 8000.0
