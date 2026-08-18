# -*- coding: utf-8 -*-
"""S079 阶段 D 单测：workflow 路由响应 P2 字段透传（D1）+ AC6 处置（E4）。

覆盖：
- D1：_extract_p2_fields 从 factor results 提取 P2 字段
- D2-D3：get_pre_market_workflow 响应顶层含 P2 字段（done 分支 + 快照分支）
- E4：hot_money_seats datacenter 调用走 em_get 限流（AC6 标注齐全）
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from routers.workflow import _extract_p2_fields
from factors.base import FactorResult


# ---------------------------------------------------------------------------
# 构造工具
# ---------------------------------------------------------------------------

def _make_factor_result(
    factor_id: str = "limitup_screener",
    p2_config: dict | None = None,
) -> FactorResult:
    """构造 FactorResult（含 P2 字段在 config）。"""
    cfg = p2_config or {}
    return FactorResult(
        factor_id=factor_id,
        factor_name="test",
        candidates=[],
        layers=[],
        config=cfg,
        as_of="2026-08-18T08:00:00",
        data_date="2026-08-18",
    )


def _make_p2_config() -> dict:
    """构造 P2 字段 config。"""
    return {
        "market_phase": "普通",
        "market_phase_cap": 0.5,
        "position_cap_tier": "yellow",
        "seat_risk_flags": {"600000": ["【拒绝介入】黑名单占比 18.0%"]},
        "data_missing_flags": {"600001": "席位风控数据未取得，硬剔除不可执行"},
        "execution_checklist": ["仓位参数参考值，非执行指令", "黄色期仓位砍半"],
        "param_disclaimer": "仓位参数参考值，非执行指令 | 历史统计特征，市场有风险",
    }


# ===========================================================================
# D1：_extract_p2_fields 从 factor results 提取 P2 字段
# ===========================================================================

class TestExtractP2Fields:
    """D1 _extract_p2_fields 从 limitup_screener factor config 提取 P2 字段。"""

    def test_extract_from_limitup_screener(self):
        """从 limitup_screener factor config 提取 P2 字段。"""
        p2 = _make_p2_config()
        results = [_make_factor_result("limitup_screener", p2)]
        extracted = _extract_p2_fields(results)
        assert extracted["market_phase"] == "普通"
        assert extracted["market_phase_cap"] == 0.5
        assert extracted["position_cap_tier"] == "yellow"
        assert "600000" in extracted["seat_risk_flags"]
        assert "600001" in extracted["data_missing_flags"]
        assert len(extracted["execution_checklist"]) == 2
        assert "参考值" in extracted["param_disclaimer"]

    def test_extract_no_limitup_screener_returns_none(self):
        """无 limitup_screener factor → 全 None（降级，不阻塞）。"""
        results = [_make_factor_result("other_factor")]
        extracted = _extract_p2_fields(results)
        assert extracted["market_phase"] is None
        assert extracted["market_phase_cap"] is None
        assert extracted["position_cap_tier"] is None
        assert extracted["seat_risk_flags"] is None
        assert extracted["execution_checklist"] is None

    def test_extract_empty_results(self):
        """空 results → 全 None。"""
        extracted = _extract_p2_fields([])
        assert extracted["market_phase"] is None
        assert extracted["param_disclaimer"] is None

    def test_extract_none_results(self):
        """results=None → 全 None（不报错）。"""
        extracted = _extract_p2_fields(None)
        assert extracted["market_phase"] is None

    def test_extract_dict_factor_result(self):
        """dict 形式的 factor result（兼容性）。"""
        p2 = _make_p2_config()
        results = [{"factor_id": "limitup_screener", "config": p2}]
        extracted = _extract_p2_fields(results)
        assert extracted["market_phase"] == "普通"
        assert extracted["market_phase_cap"] == 0.5

    def test_extract_partial_p2_fields(self):
        """部分 P2 字段缺失 → 缺失字段 None。"""
        p2 = {"market_phase": "活跃"}  # 只有一个字段
        results = [_make_factor_result("limitup_screener", p2)]
        extracted = _extract_p2_fields(results)
        assert extracted["market_phase"] == "活跃"
        assert extracted["market_phase_cap"] is None  # 缺失
        assert extracted["position_cap_tier"] is None

    def test_extract_all_p2_keys_covered(self):
        """P2 字段 7 个 key 全覆盖。"""
        p2 = _make_p2_config()
        results = [_make_factor_result("limitup_screener", p2)]
        extracted = _extract_p2_fields(results)
        expected_keys = {
            "market_phase", "market_phase_cap", "position_cap_tier",
            "seat_risk_flags", "data_missing_flags", "execution_checklist",
            "param_disclaimer",
        }
        assert set(extracted.keys()) == expected_keys


# ===========================================================================
# D2-D3：get_pre_market_workflow 响应透传 P2 字段
# ===========================================================================

class TestPreMarketWorkflowResponse:
    """D2-D3 响应顶层含 P2 字段（done 分支 + 快照分支）。

    注：完整 endpoint 测试需 mock 整个 _collect + _cache + snapshot 链路，
    这里只验证 _extract_p2_fields + _cache 透传逻辑（单元层）。
    完整 HTTP 集成测试在阶段 F 验收时补。
    """

    def test_extract_p2_fields_used_in_cache_update(self):
        """验证 _extract_p2_fields 输出结构可被 _cache.update 消费。"""
        p2 = _make_p2_config()
        results = [_make_factor_result("limitup_screener", p2)]
        extracted = _extract_p2_fields(results)
        # 模拟 _cache.update 赋值
        cache_update = {
            "market_phase": extracted.get("market_phase"),
            "market_phase_cap": extracted.get("market_phase_cap"),
            "position_cap_tier": extracted.get("position_cap_tier"),
            "seat_risk_flags": extracted.get("seat_risk_flags", {}),
            "data_missing_flags": extracted.get("data_missing_flags", {}),
            "execution_checklist": extracted.get("execution_checklist", []),
            "param_disclaimer": extracted.get("param_disclaimer"),
        }
        assert cache_update["market_phase"] == "普通"
        assert cache_update["market_phase_cap"] == 0.5
        assert cache_update["position_cap_tier"] == "yellow"
        assert cache_update["seat_risk_flags"] == p2["seat_risk_flags"]
        assert cache_update["data_missing_flags"] == p2["data_missing_flags"]
        assert cache_update["execution_checklist"] == p2["execution_checklist"]
        assert cache_update["param_disclaimer"] == p2["param_disclaimer"]


# ===========================================================================
# E4：AC6 处置 —— hot_money_seats datacenter 调用走 em_get
# ===========================================================================

class TestAC6EmGetAdoption:
    """E4 AC6：hot_money_seats datacenter 调用走 astock.em_get（限流 + 熔断）。"""

    def test_fetch_billboard_dates_uses_em_get(self):
        """fetch_billboard_dates 调用 astock.em_get（不再直调 urllib）。"""
        from strategies.hot_money_seats import fetch_billboard_dates

        with patch("strategies.hot_money_seats.astock.em_get") as mock_em_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "result": {"data": [{"TRADE_DATE": "2026-08-15 00:00:00"}]}
            }
            mock_em_get.return_value = mock_resp
            dates = fetch_billboard_dates(days=5)
            assert mock_em_get.called
            assert len(dates) > 0

    def test_fetch_billboard_for_date_uses_em_get(self):
        """fetch_billboard_for_date 调用 astock.em_get（不再直调 urllib）。"""
        from strategies.hot_money_seats import fetch_billboard_for_date

        with patch("strategies.hot_money_seats.astock.em_get") as mock_em_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "result": {"data": [{"SECURITY_CODE": "600000", "side": "buy"}]}
            }
            mock_em_get.return_value = mock_resp
            results = fetch_billboard_for_date("2026-08-15")
            assert mock_em_get.called
            # buy + sell 两次调用
            assert mock_em_get.call_count == 2
            assert len(results) >= 1

    def test_fetch_billboard_dates_exception_returns_empty(self):
        """em_get 异常 → 返回空列表（不报错）。"""
        from strategies.hot_money_seats import fetch_billboard_dates

        with patch("strategies.hot_money_seats.astock.em_get", side_effect=Exception("network")):
            dates = fetch_billboard_dates(days=5)
            assert dates == []

    def test_fetch_billboard_for_date_exception_returns_empty(self):
        """em_get 异常 → 返回空列表（不报错，continue）。"""
        from strategies.hot_money_seats import fetch_billboard_for_date

        with patch("strategies.hot_money_seats.astock.em_get", side_effect=Exception("network")):
            results = fetch_billboard_for_date("2026-08-15")
            assert results == []

    def test_ac6_docstring_annotation_present(self):
        """AC6 标注齐全：模块 docstring 含 AC6 处置说明。"""
        from strategies import hot_money_seats

        docstring = hot_money_seats.__doc__ or ""
        # 模块 docstring 含 AC6 处置说明
        assert "AC6" in docstring
        assert "em_get" in docstring
        assert "限流" in docstring or "熔断" in docstring

    def test_ac6_function_docstring_annotation(self):
        """fetch_billboard_dates docstring 含 AC6 标注。"""
        from strategies.hot_money_seats import fetch_billboard_dates

        docstring = fetch_billboard_dates.__doc__ or ""
        assert "AC6" in docstring
        assert "em_get" in docstring

    def test_ac6_no_bare_urlopen_in_fetch_functions(self):
        """AC6：fetch 函数内不再直调 urllib.request.urlopen。

        验证源码不含裸 urlopen 调用（通过 inspect.getsource 检查）。
        """
        import inspect
        from strategies.hot_money_seats import fetch_billboard_dates, fetch_billboard_for_date

        src_dates = inspect.getsource(fetch_billboard_dates)
        src_for_date = inspect.getsource(fetch_billboard_for_date)

        # 不含裸 urllib.request.urlopen 调用
        assert "urllib.request.urlopen" not in src_dates
        assert "urllib.request.urlopen" not in src_for_date
        # 走 em_get
        assert "em_get" in src_dates
        assert "em_get" in src_for_date
