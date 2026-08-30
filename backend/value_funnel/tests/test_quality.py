"""S005 quality 单测：去劣7条 + 豁免 + 双口径 + 年限降级 + 银行不适用。
全部 monkeypatch 取数函数，免联网。

S108：quality 第2/3/7 条新增新浪三表回退。本测试文件测 quality 既有逻辑（ths 口径），
故 mock 新浪 fetch_merged_periods 返空（模拟新浪不可用 → 降级 ths 代理/missing）。
S108 新浪回退行为在 tests/test_s108_sina_financials.py 测。
"""
import pytest

import value_funnel.quality as q
from value_funnel import models


@pytest.fixture(autouse=True)
def _mock_sina_empty(monkeypatch):
    """S108：mock 新浪 fetch_merged_periods 返空，让 quality 走 ths 代理/missing 降级路径。

    既有 quality 测试测 ths 口径逻辑，不依赖新浪；新浪回退在 test_s108 测。
    """
    monkeypatch.setattr("data.sources.sina_financial.fetch_merged_periods",
                        lambda code, num=8: [])


# ---------- 测试用历史数据（10年，优质公司） ----------

GOOD_ROWS = [
    {"报告期": f"{y}-12-31", "营业总收入": str(100 + i * 30), "净利润": str(10 + i * 3),
     "基本每股收益": "1.0", "每股净资产": "8.0", "净资产收益率": "15.0",
     "销售毛利率": "40.0", "销售净利率": "20.0", "每股经营现金流": "2.0"}
    for i, y in enumerate(range(2014, 2024))
]


def _good_fetch(code):
    return GOOD_ROWS


def _good_listing(code):
    return (12, "电子")


# ---------- 1. 优质公司：5/7 通过，双口径 ----------

def test_good_company(monkeypatch):
    monkeypatch.setattr(q, "_fetch_yearly_abstract", _good_fetch)
    monkeypatch.setattr(q, "_listing_info", _good_listing)
    a = q.compute_quality("000001")
    byidx = {m.index: m for m in a.metrics}
    assert byidx[1].passed is True          # ROE 15>=8
    assert byidx[2].passed is True          # FCF 正
    assert byidx[3].inapplicable is False and byidx[3].missing is True  # 非银行但无 EBIT
    assert byidx[4].passed is True         # 毛利 40>=15
    assert byidx[5].passed is True          # ocf/eps=2>=0.7
    assert byidx[6].passed is True          # 净利率 20>=5
    assert byidx[7].missing is True         # 历史股本未取得
    assert a.pass_count == 5
    assert a.inapplicable_count == 0
    assert a.pass_rate_absolute == round(5 / 7, 4)
    # 调整分母 = 7 - 0 不适用 = 7（missing 不计入不适用）
    assert a.pass_rate_adjusted == round(5 / 7, 4)
    assert a.data_years == 12
    assert a.data_years_note is None


# ---------- 2. 银行：第3条不适用，分母调整 ----------

def test_bank_metric3_inapplicable(monkeypatch):
    monkeypatch.setattr(q, "_fetch_yearly_abstract", _good_fetch)
    monkeypatch.setattr(q, "_listing_info", lambda c: (12, "银行"))
    a = q.compute_quality("601398")
    byidx = {m.index: m for m in a.metrics}
    assert byidx[3].inapplicable is True
    assert "银行" in byidx[3].inapplicable_reason
    assert a.inapplicable_count == 1
    # 调整分母 = 7 - 1 = 6
    assert a.pass_rate_adjusted == round(5 / 6, 4)


# ---------- 3. 上市不足5年：多项不适用 ----------

def test_under_5_years(monkeypatch):
    monkeypatch.setattr(q, "_fetch_yearly_abstract", lambda c: GOOD_ROWS[:3])
    monkeypatch.setattr(q, "_listing_info", lambda c: (3, "电子"))
    a = q.compute_quality("688999")
    byidx = {m.index: m for m in a.metrics}
    # 1/2/4/5/6/7 不适用，3 非银行但无 EBIT → missing
    for idx in (1, 2, 4, 5, 6, 7):
        assert byidx[idx].inapplicable is True, idx
    assert a.inapplicable_count == 6
    assert a.data_years == 3
    assert "不足5年" in (a.data_years_note or "")
    assert a.pass_rate_adjusted is not None  # 分母=1


# ---------- 4. 5-10年降级标"不足10年" ----------

def test_5_to_10_years_downgrade(monkeypatch):
    monkeypatch.setattr(q, "_fetch_yearly_abstract", lambda c: GOOD_ROWS[:7])
    monkeypatch.setattr(q, "_listing_info", lambda c: (7, "电子"))
    a = q.compute_quality("000002")
    assert a.data_years == 7
    assert "不足10年" in (a.data_years_note or "")
    # ROE 条 evidence 应标降级
    m1 = next(m for m in a.metrics if m.index == 1)
    assert "不足10年" in m1.evidence or "7年" in m1.evidence


# ---------- 5. ROE 不达标（<8%）未通过 ----------

def test_low_roe_fail(monkeypatch):
    rows = [dict(r, 净资产收益率="5.0") for r in GOOD_ROWS]
    monkeypatch.setattr(q, "_fetch_yearly_abstract", lambda c: rows)
    monkeypatch.setattr(q, "_listing_info", _good_listing)
    a = q.compute_quality("000003")
    m1 = next(m for m in a.metrics if m.index == 1)
    assert m1.passed is False
    assert m1.value == 5.0


# ---------- 6. 数据全缺失：全 missing，通过率 0 ----------

def test_all_missing(monkeypatch):
    monkeypatch.setattr(q, "_fetch_yearly_abstract", lambda c: [])
    monkeypatch.setattr(q, "_listing_info", _good_listing)
    a = q.compute_quality("000004")
    assert a.pass_count == 0
    # 上市12年但无数据 → 各条 missing/inapplicable
    assert a.pass_rate_absolute == 0.0


# ---------- 7. 豁免A：营收高增 + ROE 不达标 → 提示性豁免 ----------

def test_exemption_A(monkeypatch):
    rows = [dict(r, 净资产收益率="3.0") for r in GOOD_ROWS]  # ROE 低
    # 近3年营收增长 >1.5倍（触发豁免A的战略投入期营收高增条件）
    for i, r in enumerate(rows[-3:]):
        r["营业总收入"] = str(100 * (2 ** i))  # 100, 200, 400
    monkeypatch.setattr(q, "_fetch_yearly_abstract", lambda c: rows)
    monkeypatch.setattr(q, "_listing_info", _good_listing)
    a = q.compute_quality("000005")
    m1 = next(m for m in a.metrics if m.index == 1)
    assert m1.passed is False
    assert m1.exempt is True
    assert m1.exempt_rule and m1.exempt_rule.startswith("A")


# ---------- 8. 护城河代理：毛利率持续高 ----------

def test_moat_persistence(monkeypatch):
    monkeypatch.setattr(q, "_fetch_yearly_abstract", _good_fetch)
    monkeypatch.setattr(q, "_listing_info", _good_listing)
    a = q.compute_quality("000001")
    assert a.moat.gross_margin_persistence is True
    assert "系统不输出主观评分" in a.moat.note
