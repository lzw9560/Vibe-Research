# -*- coding: utf-8 -*-
"""sources/* 与 astock 返回结构的键名契约测试（离线，不联网）。

目的：堵住"source 用 .get(key) 取数、键名与 astock 实际返回不符→静默 missing"
这一类被 mock 测试遮蔽的盲区（见审查 HIGH-1 / MEDIUM-4）。

做法：用与 astock._parse_gtimg 实际输出**同形**的 fixture，patch 掉
astock.tencent_quote，断言 source 层映射正确（含单位换算）。
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from candidate_funnel.sources import activity
from candidate_funnel.sources import fund_flow
from candidate_funnel.sources import catalyst
from candidate_funnel.sources import gene


# ---- astock._parse_gtimg 实际输出形状（见 astock.py:_parse_gtimg） ----
# 键名必须与 astock 真实返回一致；amount 单位为"万"。
_GTIMG_SHAPE = {
    "600519": {
        "name": "贵州茅台",
        "price": 1800.0,
        "last_close": 1714.28,
        "open": 1720.0,
        "change_amt": 85.72,
        "change_pct": 5.0,
        "high": 1820.0,
        "low": 1710.0,
        "amount_wan": 500000.0,   # 50 亿（万为单位）
        "turnover_pct": 25.0,
        "pe_ttm": 30.0,
        "amplitude_pct": 6.4,
        "mcap_yi": 22600.0,
        "float_mcap_yi": 22600.0,
        "pb": 10.0,
        "limit_up": 1885.71,
        "limit_down": 1542.85,
        "vol_ratio": 3.0,
        "pe_static": 30.0,
    },
}


class TestActivityContract(unittest.TestCase):
    """activity.fetch_activity 与 tencent_quote 返回结构的键名/单位契约。"""

    def test_amount_mapped_from_amount_wan_and_converted_to_yi(self):
        """成交额：astock 返回 amount_wan(万) → source 输出 amount_yi(亿)。"""
        with mock.patch.object(activity.astock, "tencent_quote", return_value=_GTIMG_SHAPE):
            out = activity.fetch_activity(["600519"], "2026-07-28")
        entry = out["600519"]
        # 500000 万 == 50 亿
        self.assertAlmostEqual(entry["amount_yi"], 50.0, places=4)
        self.assertNotIn("amount_yi", entry.get("missing", {}))

    def test_amount_zero_is_not_swallowed_by_fallback(self):
        """amount_wan=0 应回 0.0 亿，而非被 `or` 误判为缺失走兜底。"""
        shape = {"600519": dict(_GTIMG_SHAPE["600519"], amount_wan=0.0)}
        with mock.patch.object(activity.astock, "tencent_quote", return_value=shape):
            out = activity.fetch_activity(["600519"], "2026-07-28")
        self.assertEqual(out["600519"]["amount_yi"], 0.0)
        self.assertNotIn("amount_yi", out["600519"].get("missing", {}))

    def test_other_fields_mapped_by_real_keys(self):
        """换手/量比/振幅/涨跌停 必须按 astock 真实键名取到。"""
        with mock.patch.object(activity.astock, "tencent_quote", return_value=_GTIMG_SHAPE):
            out = activity.fetch_activity(["600519"], "2026-07-28")
        e = out["600519"]
        self.assertAlmostEqual(e["turnover_pct"], 25.0)
        self.assertAlmostEqual(e["vol_ratio"], 3.0)
        self.assertAlmostEqual(e["amplitude_pct"], 6.4)
        self.assertAlmostEqual(e["limit_up"], 1885.71)
        self.assertAlmostEqual(e["limit_down"], 1542.85)
        self.assertAlmostEqual(e["change_pct"], 5.0)
        for k in ("turnover_pct", "vol_ratio", "amplitude_pct"):
            self.assertNotIn(k, e.get("missing", {}), f"{k} 不应 missing")

    def test_amount_wan_absent_marks_missing(self):
        """astock 真的没给 amount_wan 时才标 missing（而非键名不匹配的假缺失）。"""
        shape = {"600519": {k: v for k, v in _GTIMG_SHAPE["600519"].items() if k != "amount_wan"}}
        with mock.patch.object(activity.astock, "tencent_quote", return_value=shape):
            out = activity.fetch_activity(["600519"], "2026-07-28")
        self.assertIsNone(out["600519"]["amount_yi"])
        self.assertIn("amount_yi", out["600519"].get("missing", {}))


# ---- astock.stock_fund_flow_120d 实际返回形状（见 astock.py） ----
# 每条 {date, main_net, small_net, mid_net, large_net, super_net, ...}；
# main_net 单位：**元**（astock docstring："净流入(元)"），source 须 /10000 换算到万。
_FUND_FLOWS = [
    {"date": "2026-07-25", "main_net": 10000000.0, "small_net": 0.0, "mid_net": 0.0, "large_net": 0.0, "super_net": 10000000.0},   # 1000 万
    {"date": "2026-07-26", "main_net": -5000000.0, "small_net": 0.0, "mid_net": 0.0, "large_net": 0.0, "super_net": -5000000.0},   # -500 万
    {"date": "2026-07-27", "main_net": 20000000.0, "small_net": 0.0, "mid_net": 0.0, "large_net": 0.0, "super_net": 20000000.0},   # 2000 万
    {"date": "2026-07-28", "main_net": 30000000.0, "small_net": 0.0, "mid_net": 0.0, "large_net": 0.0, "super_net": 30000000.0},   # 3000 万
]
# astock.dragon_tiger_board 实际返回形状：含 institution.net_amt（已为"万"，无需再换算）。
_DRAGON_TIGER = {
    "records": [{"date": "2026-07-28", "reason": "日涨幅偏离值", "net_buy": 8000.0, "turnover": 1.2}],
    "seats": {"buy": [], "sell": []},
    "institution": {"buy_amt": 9000.0, "sell_amt": 1000.0, "net_amt": 8000.0},
}


class TestFundFlowContract(unittest.TestCase):
    """fund_flow.fetch_fund_flow 与 astock 返回结构的键名/单位契约。"""

    def test_main_net_converted_yuan_to_wan(self):
        """主力净流：astock main_net(元) → 万（/10000），取 flows[-1]。"""
        with mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=_FUND_FLOWS), \
             mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value=_DRAGON_TIGER):
            out = fund_flow.fetch_fund_flow(["600519"], "2026-07-28")
        self.assertEqual(out["600519"]["main_net_inflow"], 3000.0)  # 30000000 元 = 3000 万

    def test_main_net_5d_is_sum_of_last_five_in_wan(self):
        """5日主力：flows[-5:] 的 main_net 求和(元) 再 /10000 → 万。"""
        with mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=_FUND_FLOWS), \
             mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value=_DRAGON_TIGER):
            out = fund_flow.fetch_fund_flow(["600519"], "2026-07-28")
        # 1000 + -500 + 2000 + 3000 = 5500 万
        self.assertEqual(out["600519"]["main_net_5d"], 5500.0)

    def test_dragon_tiger_inst_net_in_wan_no_double_conversion(self):
        """龙虎榜机构：astock 已返回万，source 不再二次换算。"""
        with mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=_FUND_FLOWS), \
             mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value=_DRAGON_TIGER):
            out = fund_flow.fetch_fund_flow(["600519"], "2026-07-28")
        self.assertEqual(out["600519"]["dragon_tiger_inst_net"], 8000.0)

    def test_northbound_always_missing(self):
        """北向不可得 → missing（§8 边界）。"""
        with mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=_FUND_FLOWS), \
             mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value=_DRAGON_TIGER):
            out = fund_flow.fetch_fund_flow(["600519"], "2026-07-28")
        self.assertIsNone(out["600519"]["northbound"])
        self.assertEqual(out["600519"]["missing"]["northbound"], "北向数据不可得")

    def test_dragon_tiger_absent_marks_pending(self):
        """龙虎榜未披露（institution 无 net_amt）→ 待披露，不臆测。"""
        dt_no_inst = {"records": [], "seats": {"buy": [], "sell": []}, "institution": {}}
        with mock.patch.object(fund_flow.astock, "stock_fund_flow_120d", return_value=_FUND_FLOWS), \
             mock.patch.object(fund_flow.astock, "dragon_tiger_board", return_value=dt_no_inst):
            out = fund_flow.fetch_fund_flow(["600519"], "2026-07-28")
        self.assertIsNone(out["600519"]["dragon_tiger_inst_net"])
        self.assertEqual(out["600519"]["missing"]["dragon_tiger_inst_net"], "龙虎榜待披露")


# ---- astock.announcements / concept_blocks 实际返回形状 ----
_ANNOUNCEMENTS = [
    {"date": "2026-07-28", "title": "2026 年半年度业绩预增公告", "type": "业绩", "url": ""},
    {"date": "2026-07-15", "title": "关于回购股份的进展", "type": "回购", "url": ""},
]
_CONCEPT_BLOCKS = {
    "total": 2,
    "boards": [
        {"name": "白酒", "code": "BK0477", "change_pct": 2.1, "lead_stock": "贵州茅台"},
        {"name": "机构重仓", "code": "BK0556", "change_pct": 1.3, "lead_stock": ""},
    ],
    "concept_tags": ["白酒", "机构重仓"],
}


class TestCatalystContract(unittest.TestCase):
    """catalyst.fetch_catalyst 与 astock.announcements/concept_blocks 返回的键名契约。"""

    def test_announcements_mapped_by_title_date_type(self):
        with mock.patch.object(catalyst.astock, "announcements", return_value=_ANNOUNCEMENTS), \
             mock.patch.object(catalyst.astock, "concept_blocks", return_value=_CONCEPT_BLOCKS):
            out = catalyst.fetch_catalyst(["600519"], "2026-07-28")
        anns = out["600519"]["announcements"]
        self.assertEqual(len(anns), 2)
        self.assertEqual(anns[0]["title"], "2026 年半年度业绩预增公告")
        self.assertEqual(anns[0]["date"], "2026-07-28")
        self.assertEqual(anns[0]["type"], "业绩")

    def test_concepts_mapped_from_boards_name(self):
        with mock.patch.object(catalyst.astock, "announcements", return_value=_ANNOUNCEMENTS), \
             mock.patch.object(catalyst.astock, "concept_blocks", return_value=_CONCEPT_BLOCKS):
            out = catalyst.fetch_catalyst(["600519"], "2026-07-28")
        self.assertEqual(out["600519"]["concepts"], ["白酒", "机构重仓"])

    def test_no_announcements_marks_missing(self):
        with mock.patch.object(catalyst.astock, "announcements", return_value=[]), \
             mock.patch.object(catalyst.astock, "concept_blocks", return_value=_CONCEPT_BLOCKS):
            out = catalyst.fetch_catalyst(["600519"], "2026-07-28")
        self.assertEqual(out["600519"]["announcements"], [])
        self.assertEqual(out["600519"]["missing"]["announcements"], "近期无公告")


# ---- limitup_screener.get_screener_result 实际为 async def，source 须 await ----
class _Gene:
    def __init__(self, code, score, high, qual):
        self.code = code
        self.name = code
        self.total_score = score
        self.high_gene = high
        self.qualify = qual


class _ScreenerResult:
    def __init__(self, scores):
        self.gene_scores = scores


class TestGeneAsyncContract(unittest.TestCase):
    """gene.fetch_genes 必须真正 await limitup_screener 的 async 函数，否则静默返回 {}。"""

    def test_fetch_genes_awaits_async_screener(self):
        import limitup_screener as ls
        result = _ScreenerResult([_Gene("600519", 80.0, True, True), _Gene("000001", 65.0, False, True)])

        async def fake_get(date=None):
            return result

        with mock.patch.object(ls, "get_screener_result", fake_get):
            out = gene.fetch_genes("2026-07-29")
        self.assertEqual(set(out.keys()), {"600519", "000001"})
        self.assertEqual(out["600519"]["gene_score"], 80.0)
        self.assertTrue(out["600519"]["high_gene"])
        self.assertTrue(out["600519"]["qualify"])

    def test_fetch_genes_returns_empty_on_exception(self):
        import limitup_screener as ls

        async def fake_get(date=None):
            raise RuntimeError("boom")

        with mock.patch.object(ls, "get_screener_result", fake_get):
            out = gene.fetch_genes("2026-07-29")
        self.assertEqual(out, {})


if __name__ == "__main__":
    unittest.main()
