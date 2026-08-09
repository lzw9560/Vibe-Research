# -*- coding: utf-8 -*-
"""S044 concept_blocks 解析契约 + secid/ut 参数（push2 slist，offline mock）。

concept_blocks 经 ut 修复（e33cd5c）后应可用；之前 slist data:null 是探测用 secid=1.000001
（=上证指数，指数无概念板块→null 是预期）的假象，非函数 bug。本测试覆盖 parsing/secid/ut，
live 验证待东财 push2 IP 限流冷却。
"""
from data.sources import eastmoney


class _Resp:
    def __init__(self, d):
        self._d = d

    def json(self):
        return self._d


class TestConceptBlocksParsing:
    def test_diff_dict解析boards_含concept_tags(self, monkeypatch):
        monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: _Resp(
            {"data": {"diff": {"0": {"f12": "BK0477", "f14": "白酒", "f3": 2.1, "f128": "贵州茅台"},
                                  "1": {"f12": "BK0556", "f14": "机构重仓", "f3": 1.3, "f128": ""}}}}))
        out = eastmoney.concept_blocks("600519")
        assert out["total"] == 2
        assert out["boards"][0] == {"name": "白酒", "code": "BK0477", "change_pct": 2.1, "lead_stock": "贵州茅台"}
        assert out["concept_tags"] == ["白酒", "机构重仓"]

    def test_空响应返空(self, monkeypatch):
        monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: _Resp({"data": None}))
        out = eastmoney.concept_blocks("600519")
        assert out == {"total": 0, "boards": [], "concept_tags": []}

    def test_em_get异常返空(self, monkeypatch):
        monkeypatch.setattr(eastmoney, "em_get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net")))
        out = eastmoney.concept_blocks("600519")
        assert out["total"] == 0


class TestConceptBlocksParams:
    def _capture(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            eastmoney, "em_get",
            lambda url, params=None, **k: (captured.update(params) or _Resp({"data": {"diff": {}}})))
        return captured

    def test_SZ股secid_market0(self, monkeypatch):
        captured = self._capture(monkeypatch)
        eastmoney.concept_blocks("000001")
        assert captured["secid"] == "0.000001"  # 深市 market 0

    def test_SH股secid_market1(self, monkeypatch):
        captured = self._capture(monkeypatch)
        eastmoney.concept_blocks("600519")
        assert captured["secid"] == "1.600519"  # 沪市 market 1

    def test_带ut_token(self, monkeypatch):
        captured = self._capture(monkeypatch)
        eastmoney.concept_blocks("000001")
        assert captured.get("ut") == eastmoney._PUSH2_UT  # ut 修复（e33cd5c）生效
