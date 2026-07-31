# -*- coding: utf-8 -*-
"""earnings-review §4.2 五异常信号单测。纯函数、无网络、可复算。"""
from models.financials import FinancialPeriod
from value_funnel.anomaly import detect_anomalies


def _p(**kw) -> FinancialPeriod:
    """快捷构造 FinancialPeriod（period 默认按需要）。"""
    return FinancialPeriod(**kw)


def test_channel_stuffing_triggered():
    """应收增速 50% > 营收增速 10% → 触发。"""
    prior = _p(period="2023", revenue=100.0, accounts_receivable=20.0)
    curr = _p(period="2024", revenue=110.0, accounts_receivable=30.0)
    r = detect_anomalies([prior, curr])
    s1 = r.signals[0]
    assert s1.triggered is True
    assert s1.severity == "warn"
    assert r.triggered_count == 1


def test_channel_stuffing_not_triggered_when_ar_flat():
    """应收增速 < 营收增速 → 不触发。"""
    prior = _p(period="2023", revenue=100.0, accounts_receivable=20.0)
    curr = _p(period="2024", revenue=150.0, accounts_receivable=20.0)  # ar 0%, rev 50%
    r = detect_anomalies([prior, curr])
    assert r.signals[0].triggered is False


def test_inventory_piling_triggered():
    prior = _p(period="2023", revenue=100.0, inventory=10.0)
    curr = _p(period="2024", revenue=110.0, inventory=20.0)  # inv +100%, rev +10%
    r = detect_anomalies([prior, curr])
    assert r.signals[1].triggered is True
    assert r.signals[1].severity == "warn"


def test_earnings_quality_triggered_high():
    """OCF<NI 当期 且 gap 当期>上期 → 触发 high。"""
    prior = _p(period="2023", net_profit=80.0, operating_cash_flow=70.0)  # gap 10
    curr = _p(period="2024", net_profit=100.0, operating_cash_flow=60.0)  # gap 40, OCF<NI
    r = detect_anomalies([prior, curr])
    s3 = r.signals[2]
    assert s3.triggered is True
    assert s3.severity == "high"


def test_earnings_quality_not_triggered_when_gap_shrinking():
    """OCF<NI 但 gap 缩小 → 不触发。"""
    prior = _p(period="2023", net_profit=100.0, operating_cash_flow=60.0)  # gap 40
    curr = _p(period="2024", net_profit=100.0, operating_cash_flow=80.0)    # gap 20, 缩小
    r = detect_anomalies([prior, curr])
    assert r.signals[2].triggered is False


def test_capex_spike_triggered():
    prior = _p(period="2023", capex=100.0)
    curr = _p(period="2024", capex=200.0)  # 2.0× > 1.5
    r = detect_anomalies([prior, curr])
    assert r.signals[3].triggered is True
    assert r.signals[3].severity == "warn"


def test_capex_spike_not_triggered_below_ratio():
    prior = _p(period="2023", capex=100.0)
    curr = _p(period="2024", capex=140.0)  # 1.4× < 1.5
    r = detect_anomalies([prior, curr])
    assert r.signals[3].triggered is False


def test_nonrecurring_spike_triggered():
    prior = _p(period="2023", net_profit=100.0, net_profit_excluding_nonrecurring=95.0)  # nr 5%, share 5%
    curr = _p(period="2024", net_profit=100.0, net_profit_excluding_nonrecurring=80.0)   # nr 20%, share 20%
    r = detect_anomalies([prior, curr])
    assert r.signals[4].triggered is True
    assert r.signals[4].severity == "high"


def test_nonrecurring_not_triggered_when_below_material_floor():
    """占比虽上升但 < 5% 噪声门槛 → 不触发。"""
    prior = _p(period="2023", net_profit=100.0, net_profit_excluding_nonrecurring=99.0)  # nr 1%, share 1%
    curr = _p(period="2024", net_profit=100.0, net_profit_excluding_nonrecurring=98.0)   # nr 2%, share 2%
    r = detect_anomalies([prior, curr])
    assert r.signals[4].triggered is False


def test_missing_values_marked_inapplicable():
    """缺字段 → 该信号 inapplicable，不臆造、不触发。"""
    prior = _p(period="2023")
    curr = _p(period="2024")
    r = detect_anomalies([prior, curr])
    for s in r.signals:
        assert s.inapplicable is True
    assert r.triggered_count == 0


def test_single_period_all_inapplicable():
    """仅 1 期 → 全部 inapplicable。"""
    r = detect_anomalies([_p(period="2024", revenue=100.0)])
    assert len(r.signals) == 5
    for s in r.signals:
        assert s.inapplicable is True
    assert r.triggered_count == 0


def test_period_and_prior_period_recorded():
    prior = _p(period="2023", revenue=100.0, accounts_receivable=10.0)
    curr = _p(period="2024", revenue=110.0, accounts_receivable=15.0)
    r = detect_anomalies([prior, curr])
    assert r.period == "2024"
    assert r.prior_period == "2023"


def test_all_clean_company_zero_triggers():
    """干净公司：五信号全不触发。"""
    prior = _p(period="2023", revenue=100.0, accounts_receivable=10.0, inventory=10.0,
               net_profit=50.0, operating_cash_flow=55.0, capex=20.0,
               net_profit_excluding_nonrecurring=49.0)
    curr = _p(period="2024", revenue=120.0, accounts_receivable=11.0, inventory=11.0,
              net_profit=60.0, operating_cash_flow=70.0, capex=22.0,
              net_profit_excluding_nonrecurring=59.0)
    r = detect_anomalies([prior, curr])
    assert r.triggered_count == 0
    assert all(not s.triggered for s in r.signals)
