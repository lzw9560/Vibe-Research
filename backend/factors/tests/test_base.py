# -*- coding: utf-8 -*-
"""因子接口与注册表单测（S023 A3）。"""

from __future__ import annotations

from datetime import datetime

from factors import Candidate, FactorResult
from factors import registry
from candidate_funnel.models import FunnelLayer


def _fake_layer(name: str = "测试层", n_in: int = 10, n_out: int = 5) -> FunnelLayer:
    return FunnelLayer(
        layer_id="T",
        name=name,
        as_of=datetime.now(),
        input_count=n_in,
        output_count=n_out,
        filtered_out=[],
        output_codes=[],
    )


class FakeFactor:
    """假因子用于注册表测试。"""

    factor_id = "fake"
    factor_name = "假因子"

    def fetch(self, date: str, config: dict | None = None) -> FactorResult:
        return FactorResult(
            factor_id="fake",
            factor_name="假因子",
            candidates=[Candidate(code="000001", name="测试", source_factor_id="fake", source_layer="T")],
            layers=[_fake_layer()],
            config={"threshold": 1.0},
            as_of="2026-08-02T00:00:00",
            data_date="2026-08-01",
        )

    def describe(self) -> dict:
        return {"name": "假因子", "维度": ["测试"]}


class BoomFactor:
    """总会抛异常的因子，测 fetch_all 容错。"""

    factor_id = "boom"
    factor_name = "爆炸因子"

    def fetch(self, date: str, config: dict | None = None) -> FactorResult:
        raise RuntimeError("故意的")

    def describe(self) -> dict:
        return {"name": "爆炸因子"}


def setup_function():
    registry._registry.clear()


def test_candidate_fields():
    c = Candidate(code="600519", name="贵州茅台", source_factor_id="f1", source_layer="R2")
    assert c.code == "600519"
    assert c.hit_rules == []
    assert c.detail == {}


def test_factor_result_data_status_default_ok():
    r = FactorResult(factor_id="f", factor_name="f", candidates=[], layers=[])
    assert r.data_status == "ok"


def test_factor_result_data_status_missing():
    r = FactorResult(
        factor_id="f", factor_name="f", candidates=[], layers=[],
        config={"data_status": "未取得", "reason": "limitup_screener 未预计算"},
    )
    assert r.data_status == "未取得"


def test_register_and_get_factor():
    f = FakeFactor()
    registry.register(f)
    assert registry.get_factor("fake") is f
    assert registry.get_factor("nope") is None


def test_get_all_factors():
    registry.register(FakeFactor())
    registry.register(BoomFactor())
    all_f = registry.get_all_factors()
    assert len(all_f) == 2
    ids = {f.factor_id for f in all_f}
    assert ids == {"fake", "boom"}


def test_fetch_all_normal():
    registry.register(FakeFactor())
    results = registry.fetch_all("2026-08-01")
    assert len(results) == 1
    r = results[0]
    assert r.factor_id == "fake"
    assert len(r.candidates) == 1
    assert r.candidates[0].code == "000001"
    assert r.data_date == "2026-08-01"
    assert r.data_status == "ok"


def test_fetch_all_one_failure_does_not_block():
    registry.register(FakeFactor())
    registry.register(BoomFactor())
    results = registry.fetch_all("2026-08-01")
    assert len(results) == 2
    # fake 正常
    fake = next(r for r in results if r.factor_id == "fake")
    assert len(fake.candidates) == 1
    # boom 降级为未取得，不阻塞
    boom = next(r for r in results if r.factor_id == "boom")
    assert boom.candidates == []
    assert boom.data_status == "未取得"
    assert "故意的" in boom.config.get("reason", "")


def test_register_overwrites():
    f1 = FakeFactor()
    f1.factor_id = "dup"
    f2 = FakeFactor()
    f2.factor_id = "dup"
    registry.register(f1)
    registry.register(f2)
    assert registry.get_factor("dup") is f2
    assert len(registry.get_all_factors()) == 1
