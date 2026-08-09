# -*- coding: utf-8 -*-
"""S044 阶段3 单测：公告类型化 + R3 按类型过滤。"""
from candidate_funnel.sources.catalyst import classify_announcement
from candidate_funnel.funnel import _filter_r3


class TestClassifyAnnouncement:
    def test_预增命中(self):
        assert classify_announcement({"title": "2026年半年度业绩预增公告"}) == "预增"

    def test_重组命中(self):
        assert classify_announcement({"title": "重大资产重组预案"}) == "重组"

    def test_回购命中(self):
        assert classify_announcement({"title": "关于回购公司股份的方案"}) == "回购"

    def test_其他兜底(self):
        assert classify_announcement({"title": "关于召开临时股东大会的通知"}) == "其他"

    def test_空title归其他(self):
        assert classify_announcement({"title": None}) == "其他"
        assert classify_announcement({}) == "其他"


def _cat(anns: list[dict], concepts: list[str] | None = None) -> dict:
    return {"announcements": anns, "concepts": concepts or [], "sector_flow": None, "missing": {}}


class TestFilterR3AnnTypes:
    def test_默认None保留所有有催化标的(self):
        cat = {"000001": _cat([{"title": "业绩预增", "date": "2026-08-01", "type": "预增"}])}
        kept, filt = _filter_r3(["000001"], {}, cat, {}, {}, ann_types=None)
        assert kept == ["000001"]
        assert filt == []

    def test_ann_types只留预增过滤重组(self):
        cat = {
            "000001": _cat([{"title": "业绩预增", "date": "", "type": "预增"}]),
            "000002": _cat([{"title": "重大资产重组", "date": "", "type": "重组"}]),
        }
        kept, filt = _filter_r3(["000001", "000002"], {}, cat, {}, {}, ann_types=["预增"])
        assert kept == ["000001"]
        assert [f.code for f in filt] == ["000002"]

    def test_无竞价无催化_过滤(self):
        cat = {"000003": _cat([], concepts=[])}
        kept, filt = _filter_r3(["000003"], {}, cat, {}, {}, ann_types=["预增"])
        assert kept == []
        assert [f.code for f in filt] == ["000003"]

    def test_概念催化但无公告_有ann_types时过滤(self):
        # has_catalyst 由 concepts 触发，但 ann_types 要求公告类型命中 → 过滤
        cat = {"000003": _cat([], concepts=["AI"])}
        kept, filt = _filter_r3(["000003"], {}, cat, {}, {}, ann_types=["预增"])
        assert kept == []
        assert [f.code for f in filt] == ["000003"]

    def test_概念催化无ann_types_保留(self):
        cat = {"000003": _cat([], concepts=["AI"])}
        kept, _ = _filter_r3(["000003"], {}, cat, {}, {}, ann_types=None)
        assert kept == ["000003"]

    def test_有竞价但公告类型不命中_过滤(self):
        au = {"000004": {"auction_open_pct": 5.0}}
        cat = {"000004": _cat([{"title": "通知", "date": "", "type": "其他"}])}
        kept, filt = _filter_r3(["000004"], au, cat, {}, {}, ann_types=["预增"])
        assert kept == []
        assert [f.code for f in filt] == ["000004"]

    def test_有竞价且公告类型命中_保留(self):
        au = {"000004": {"auction_open_pct": 5.0}}
        cat = {"000004": _cat([{"title": "业绩预增", "date": "", "type": "预增"}])}
        kept, _ = _filter_r3(["000004"], au, cat, {}, {}, ann_types=["预增"])
        assert kept == ["000004"]
