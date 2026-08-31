# -*- coding: utf-8 -*-
"""S130 R1.4：_build_risk_factors conc/dt/seat/cf status 感知。

锁住（spec §3 R1.4）：
- ①conc missing→"席位集中度数据缺失"；
- ②dt degraded→"龙虎榜数据缺失"；
- ③seat missing→"席位数据缺失"；
- ④cf missing→"资金流数据缺失"；
- ⑤全 ok+超阈→原文本不破；
- ⑥四维全 missing→factors 含四"数据缺失"非"较少"。

对齐 S129 R3 trio 范式（test_s129_risk_trio_provenance），纯函数直调
_build_risk_factors，不依赖 live 取数。
"""
import risk_models


def _base_kwargs() -> dict:
    """全 ok 基线 kwargs（值全 0，无超阈触发，仅 status 维度可驱动 factor）。"""
    return dict(
        dynamic_score=50.0,
        risk_level="LOW",
        dragon_tiger_risk=0.0,
        volatility=0.0,
        max_drawdown=0.0,
        liquidity_risk=0.0,
        concentration_risk=0.0,
        capital_flow_trend="平衡",
        multi_seat_signal=False,
    )


# ── R1.4 ①-④：单维 missing/degraded → 对应"数据缺失" ─────────────────────

def test_r1_conc_missing_shows_concentration_data_missing():
    # Arrange：conc missing，其余 ok+值 0（无超阈）
    kw = _base_kwargs()
    # Act
    factors, _rec = risk_models._build_risk_factors(**kw, conc_status="missing")
    # Assert
    assert "席位集中度数据缺失" in factors
    assert "当前风险因素较少" not in factors


def test_r1_dt_degraded_shows_dragon_tiger_data_missing():
    # Arrange：dt degraded，其余 ok
    kw = _base_kwargs()
    # Act
    factors, _rec = risk_models._build_risk_factors(**kw, dt_status="degraded")
    # Assert
    assert "龙虎榜数据缺失" in factors
    assert "当前风险因素较少" not in factors


def test_r1_seat_missing_shows_seat_data_missing():
    # Arrange：seat missing，其余 ok
    kw = _base_kwargs()
    # Act
    factors, _rec = risk_models._build_risk_factors(**kw, seat_status="missing")
    # Assert
    assert "席位数据缺失" in factors
    assert "当前风险因素较少" not in factors


def test_r1_cf_missing_shows_capital_flow_data_missing():
    # Arrange：cf missing，其余 ok
    kw = _base_kwargs()
    # Act
    factors, _rec = risk_models._build_risk_factors(**kw, cf_status="missing")
    # Assert
    assert "资金流数据缺失" in factors
    assert "当前风险因素较少" not in factors


# ── R1.4 ⑤：全 ok+超阈→原文本不破 ──────────────────────────────────────

def test_r1_all_ok_high_threshold_preserves_original_text():
    # Arrange：全 ok，超阈值触发四维原文本
    # Act
    factors, _rec = risk_models._build_risk_factors(
        dynamic_score=80.0, risk_level="HIGH",
        dragon_tiger_risk=35.0, volatility=6.0, max_drawdown=12.0,
        liquidity_risk=10.0, concentration_risk=70.0,
        capital_flow_trend="流出", multi_seat_signal=True,
        vol_status="ok", dd_status="ok", liq_status="ok",
        conc_status="ok", dt_status="ok", seat_status="ok", cf_status="ok",
    )
    # Assert：四维原文本均显，不显任何"数据缺失"
    assert any("龙虎榜风险较高" in f for f in factors)
    assert any("波动率偏高" in f for f in factors)
    assert any("近期回撤较大" in f for f in factors)
    assert any("流动性风险" in f for f in factors)
    assert any("席位集中度较高" in f for f in factors)
    assert "资金流呈流出趋势" in factors
    assert "多席位共识信号" in factors
    assert not any("数据缺失" in f for f in factors)


# ── R1.4 ⑥：四维全 missing→四"数据缺失"非"较少" ───────────────────────

def test_r1_all_four_missing_shows_four_data_missing_not_fewer():
    # Arrange：conc/dt/seat/cf 全 missing（trio ok+值 0）
    kw = _base_kwargs()
    # Act
    factors, _rec = risk_models._build_risk_factors(
        **kw,
        conc_status="missing", dt_status="missing",
        seat_status="missing", cf_status="missing",
    )
    # Assert：四"数据缺失"均显
    assert "龙虎榜数据缺失" in factors
    assert "席位集中度数据缺失" in factors
    assert "席位数据缺失" in factors
    assert "资金流数据缺失" in factors
    # 不显"当前风险因素较少"（factors 非空）
    assert "当前风险因素较少" not in factors


# ── 向后兼容：默认 status 不传 → 原行为不破 ─────────────────────────────

def test_r1_backward_compat_no_status_args_preserves_original():
    # Arrange：不传 conc/dt/seat/cf_status（默认 ok），无超阈
    # Act
    factors, _rec = risk_models._build_risk_factors(**_base_kwargs())
    # Assert：无超阈无缺失 → "较少"兜底（原行为）
    assert "当前风险因素较少" in factors
    assert not any("数据缺失" in f for f in factors)
