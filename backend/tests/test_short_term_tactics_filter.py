# -*- coding: utf-8 -*-
"""S234 短线战法排雷过滤器测试。

覆盖：第一层财务过滤 + R34 机构席位识别 + JSON 输出 + code normalize + verdict 诚实标注（R30）。
AAA 模式（Arrange-Act-Assert）。
"""
import sys
from pathlib import Path

# 加 tools 到 path（short_term_tactics_filter 在 backend/tools/）
_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import pytest
from short_term_tactics_filter import (  # noqa: E402
    filter_stock, to_json, _normalize_code, _check_institutional_seat,
    first_layer_filter, VERDICTS,
)


class TestCodeNormalize:
    """code 统一为 6 位纯数字（baostock kline + gene_scores 都用 6 位）。"""

    def test_sh_prefix_stripped(self):
        # Arrange & Act
        result = _normalize_code("sh.600519")
        # Assert
        assert result == "600519"

    def test_sz_prefix_stripped(self):
        assert _normalize_code("sz.000001") == "000001"

    def test_bj_prefix_stripped(self):
        assert _normalize_code("bj.430047") == "430047"

    def test_pure_6digit_unchanged(self):
        assert _normalize_code("603778") == "603778"


class TestFirstLayerFilter:
    """第一层财务硬过滤（ST + 5 日均成交，一票否决）。"""

    def test_st_name_blocked(self):
        # Arrange: ST 股（名称含 ST）
        # Act
        passed, hits = first_layer_filter("600519", "*ST某某", [])
        # Assert
        assert not passed
        assert any("ST" in h for h in hits)

    def test_low_liquidity_blocked(self):
        # Arrange: 000659 珠海中富 5 日均成交 0.60 亿 < 1.5 亿
        # Act
        r = filter_stock("000659", "战法2_尾盘锁定")
        # Assert
        assert not r.is_passed
        assert r.safe_action == "Block"
        assert r.risk_level == "High"
        assert any("5 日均成交" in h for h in r.hit_rules)


class TestR34InstitutionalSeat:
    """R34 龙虎榜机构+外资席位识别（dragon_tiger_history 已有 1 年数据）。"""

    def test_603778_inst_dominant(self):
        # Arrange: 603778 国晟科技 龙虎榜机构席位主导（沪股通+国泰海通总部+瑞银）
        # Act
        seat = _check_institutional_seat("603778")
        # Assert
        assert seat["has_lhb"] is True
        assert seat["is_inst_dominant"] is True
        assert seat["inst_net_pct"] > 0.5
        # 机构/外资席位名识别（R34 关键词）
        assert any(
            "股通" in s or "总部" in s or "瑞银" in s or "高盛" in s or "机构专用" in s
            for s in seat["inst_seats"]
        )

    def test_seat_structure(self):
        # Arrange & Act
        seat = _check_institutional_seat("603778")
        # Assert: 结构完整
        for key in ("has_lhb", "inst_seats", "inst_net_pct", "is_inst_dominant"):
            assert key in seat


class TestJsonOutput:
    """JSON 输出（借鉴安全审查模板 is_passed/risk_level/hit_rules/reason/safe_action）。"""

    def test_json_has_required_fields(self):
        # Arrange
        r = filter_stock("603778", "战法1_弱转强")
        # Act
        j = to_json(r)
        # Assert: 5+ 字段 + verdicts + tactics_meta
        for field in ("code", "name", "is_passed", "risk_level", "hit_rules",
                      "reason", "safe_action", "verdicts", "tactics_meta"):
            assert field in j, f"missing field: {field}"

    def test_verdicts_honest_falsified(self):
        """R30: verdicts 含 falsified 诚实标注（不藏）。"""
        r = filter_stock("603778", "战法1_弱转强")
        assert "战法1_弱转强" in r.verdicts
        v = r.verdicts["战法1_弱转强"].lower()
        assert "falsified" in v or "direction-confirmed" in v
        # 战法2 也标 falsified
        assert "战法2_尾盘锁定" in r.verdicts
        assert "假edge" in r.verdicts["战法2_尾盘锁定"].lower() or "falsified" in r.verdicts["战法2_尾盘锁定"].lower()

    def test_verdicts_red_chip_low_vol_positive(self):
        """红利低波 512890 标 ✅ 唯一可落地。"""
        r = filter_stock("603778", "战法1_弱转强")
        assert "红利低波_512890" in r.verdicts
        assert "✅" in r.verdicts["红利低波_512890"]

    def test_tactics_meta_chasing_dim(self):
        """R32/R35: 战法1 tactics_meta 含 chasing 维度。"""
        r = filter_stock("603778", "战法1_弱转强")
        meta = r.tactics_meta
        # chasing_gap 或 verdict 必有
        assert "chasing_gap" in meta or "verdict" in meta


class TestEndToEnd:
    """端到端：filter_stock 完整流程。"""

    def test_603778_war1_structure(self):
        # Act
        r = filter_stock("603778", "战法1_弱转强")
        # Assert: 结构对（603778 第一层通过，第二层看 zt_count_250d）
        assert r.code == "603778"
        assert r.name == "国晟科技"
        assert r.safe_action in ("Pass", "Block")

    def test_603778_war2_institutional_seat(self):
        """战法2 含 R34 机构席位识别。"""
        r = filter_stock("603778", "战法2_尾盘锁定")
        seat = r.tactics_meta.get("institutional_seat", {})
        if seat.get("has_lhb"):
            assert "inst_net_pct" in seat
            assert "is_inst_dominant" in seat

    def test_no_main_force_intent_fabrication(self):
        """§1.2: 不编主力意图（verdict/reason 基于可观测数据非臆造）。"""
        r = filter_stock("603778", "战法1_弱转强")
        # reason 不含"主力意图/操盘手心理"等臆造话术
        assert "主力意图" not in r.reason
        assert "操盘手心理" not in r.reason


class TestNoFabricationT44:
    """T4.4 不臆造数据验收：cache 空时 filter 不编数字、不臆造 verdict、不 pass。
    §1.2 工程底线——所有因子从 SQLite cache 取，cache miss 返空/False，不臆造。
    """

    def _patch_empty_cache(self, monkeypatch):
        """把所有 cache 加载函数替换为空（模拟 cache miss）。"""
        import short_term_tactics_filter as stf
        monkeypatch.setattr(stf, "_load_kline", lambda code: [])
        monkeypatch.setattr(stf, "_load_gene", lambda code: {})
        monkeypatch.setattr(
            stf, "_check_institutional_seat",
            lambda code: {"has_lhb": False, "is_inst_dominant": False, "inst_net_pct": 0.0},
        )

    def test_war1_no_data_does_not_pass(self, monkeypatch):
        """战法1 cache 空 → 第一层'数据不足'→ is_passed=False（不臆造 pass）。"""
        self._patch_empty_cache(monkeypatch)
        r = filter_stock("600001", "战法1_弱转强")
        assert r.is_passed is False
        assert any("数据不足" in h for h in r.hit_rules)

    def test_war2_no_data_does_not_match(self, monkeypatch):
        """战法2 cache 空 → bars<2 second_layer 返 False（不臆造 match）。"""
        self._patch_empty_cache(monkeypatch)
        r = filter_stock("600001", "战法2_尾盘锁定")
        assert r.is_passed is False

    def test_war3_no_data_does_not_match(self, monkeypatch):
        """战法3 cache 空 → 无机构席位 → 不 match（不臆造 inst_dominant）。"""
        self._patch_empty_cache(monkeypatch)
        r = filter_stock("600001", "战法3_机构抱团")
        assert r.is_passed is False

    def test_no_network_module_imported(self):
        """filter.py 不依赖网络模块（数据全从 SQLite cache 取，§1.2 不臆造）。"""
        import short_term_tactics_filter as stf
        assert not hasattr(stf, "requests"), "filter 不应 import requests"
        assert not hasattr(stf, "httpx"), "filter 不应 import httpx"
        assert not hasattr(stf, "socket"), "filter 不应 import socket"
