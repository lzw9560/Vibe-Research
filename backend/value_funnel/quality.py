"""S005 去劣 7 条计算 + 3 豁免 + 双口径通过率 + 年限降级。

移植自 ai-berkshire quality-screen skill，适配 Vibe-Research。
合规：每条指标客观可复现（evidence 填取数时点+口径），豁免为提示性标注，
      最终认定交用户 AI/用户；不输出"一流/非一流"主观评价。

数据源：akshare stock_financial_abstract_ths(indicator="按年度") 取历史年度财务摘要。
        上市年限/行业 经 astock.individual_info 判断（银行/保险第3条不适用）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import models


# 年度财务摘要 TTL 缓存（避免 stage=all 对同一标的重复请求触发 akshare 限流）
_ABSTRACT_CACHE: dict[str, tuple[float, list[dict]]] = {}
_ABSTRACT_CACHE_TTL = 300  # 秒


# ---------- 工具 ----------

def _akshare():
    try:
        import akshare as ak
        return ak
    except ImportError as e:  # pragma: no cover - 依赖缺失走运行时报错
        raise RuntimeError("akshare 未安装：pip install akshare") from e


def _to_float(v) -> Optional[float]:
    """解析 ths 摘要值（容忍 %/逗号/中文逗号/None）。"""
    if v is None or v == "":
        return None
    s = str(v).strip().replace(",", "").replace("，", "")
    if s.endswith("%"):
        s = s[:-1]
    if s in ("--", "-", "nan", "None", ""):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _pct_to_ratio(v) -> Optional[float]:
    """ths 的 ROE/毛利率等多为百分数(15.32 或 '15.32%')，转成小数 0.1532。"""
    f = _to_float(v)
    return f / 100.0 if f is not None else None


# ---------- 取数 ----------

def _fetch_yearly_abstract(code: str) -> list[dict]:
    """akshare ths 按年度财务摘要，升序返回。失败返回 []。
    带 TTL 缓存（300s），避免 stage=all 对同一标的重复请求导致 akshare 限流。"""
    now = datetime.now().timestamp()
    cached = _ABSTRACT_CACHE.get(code)
    if cached and (now - cached[0]) < _ABSTRACT_CACHE_TTL:
        return cached[1]
    try:
        ak = _akshare()
        df = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
    except Exception:
        # 失败也短缓存，防重复打限流
        _ABSTRACT_CACHE[code] = (now, [])
        return []
    if df is None or df.empty:
        _ABSTRACT_CACHE[code] = (now, [])
        return []
    rows = df.to_dict("records")
    def _key(r):
        p = str(r.get("报告期") or r.get("报告日") or "")
        return p[:4]
    rows.sort(key=_key)
    _ABSTRACT_CACHE[code] = (now, rows)
    return rows


def _listing_info(code: str) -> tuple[int, str]:
    """返回 (上市年数, 行业)。失败返回 (0, '')。"""
    try:
        import astock
        from data.mappers import company_info_from_individual_info
        info = company_info_from_individual_info(astock.individual_info(code) or {})
    except Exception:
        return 0, ""
    industry = info.industry or ""
    listing = info.listing_date or ""
    year_str = listing[:4]
    try:
        ly = int(year_str)
        years = max(0, datetime.now().year - ly)
    except ValueError:
        years = 0
    return years, industry


def _is_bank_insurance(industry: str) -> bool:
    return any(k in industry for k in ("银行", "保险", "证券", "金融"))


# ---------- 7 条指标 ----------

def _metric_1_roe(rows: list[dict], years: int) -> models.QualityMetric:
    """10年平均ROE < 8% 排除。5-10年降级标"不足10年"，<5年不适用。"""
    m = models.QualityMetric(index=1, name="10年平均ROE", threshold=8.0)
    if years < 5:
        m.inapplicable, m.inapplicable_reason = True, "上市不足5年，数据不足"
        m.evidence = "上市年限<5，无法计算10年ROE"
        return m
    roes = [_pct_to_ratio(r.get("净资产收益率")) for r in rows[-10:]]
    roes = [r * 100 for r in roes if r is not None]
    if not roes:
        m.missing, m.evidence = True, "净资产收益率数据未取得"
        return m
    avg = sum(roes) / len(roes)
    m.value = round(avg, 2)
    m.passed = avg >= 8.0
    note = "不足10年(降级)" if len(roes) < 10 and years < 10 else f"基于{len(roes)}年"
    m.evidence = f"{note}，平均ROE={avg:.2f}%，阈值8%"
    return m


def _metric_2_fcf(rows: list[dict], years: int, code: str = "") -> models.QualityMetric:
    """5年累计自由现金流为负排除。S108：ths无capex → 新浪三表取真 OCF−capex 算 FCF。"""
    m = models.QualityMetric(index=2, name="5年累计自由现金流", threshold=0.0)
    if years < 5:
        m.inapplicable, m.inapplicable_reason = True, "上市不足5年，数据不足"
        m.evidence = "上市年限<5，无法计算5年累计FCF"
        return m
    # S108：优先新浪三表绝对额 OCF−capex 算真 FCF
    if code:
        try:
            from data.sources.sina_financial import fetch_merged_periods
            periods = fetch_merged_periods(code, num=5)
            ocf_list = [p.operating_cash_flow for p in periods if p.operating_cash_flow is not None]
            capex_list = [p.capex for p in periods if p.capex is not None]
            if len(ocf_list) >= 1 and len(capex_list) >= 1:
                n = min(len(ocf_list), len(capex_list), 5)
                fcf = sum(ocf_list[:n]) - sum(capex_list[:n])
                m.value = round(fcf, 2)
                m.passed = fcf >= 0
                m.evidence = f"5年累计FCF={fcf:.0f}(新浪: OCF累计{sum(ocf_list[:n]):.0f}−capex累计{sum(capex_list[:n]):.0f})，阈值≥0"
                return m
        except Exception:  # noqa: BLE001 — 新浪失败降级 ths 代理口径
            pass
    # 降级：ths 每股 OCF 累计代理（不扣 capex）
    ocf_ps = [_to_float(r.get("每股经营现金流")) for r in rows[-5:]]
    ocf_ps = [x for x in ocf_ps if x is not None]
    if not ocf_ps:
        m.missing, m.evidence = True, "经营现金流数据未取得"
        return m
    total = sum(ocf_ps)
    m.value = round(total, 4)
    m.passed = total >= 0
    m.evidence = f"5年累计每股经营现金流={total:.4f}(代理，新浪capex未取)，阈值≥0"
    return m


def _metric_3_interest(rows: list[dict], years: int, industry: str, code: str = "") -> models.QualityMetric:
    """利息覆盖倍数(EBIT/利息)<2 排除。银行/保险不适用。S108：ths缺→新浪取 financial_expense/total_profit。"""
    m = models.QualityMetric(index=3, name="利息覆盖倍数", threshold=2.0)
    if _is_bank_insurance(industry):
        m.inapplicable, m.inapplicable_reason = True, f"行业({industry})不适用利息覆盖"
        m.evidence = "银行/保险/证券不适用第3条"
        return m
    # S108：优先新浪三表 total_profit/financial_expense（绝对额稳定）
    if code:
        try:
            from data.sources.sina_financial import fetch_merged_periods
            periods = fetch_merged_periods(code, num=2)
            if len(periods) >= 1:
                p = periods[0]
                profit = p.total_profit or p.operating_profit
                fin_cost = p.financial_expense
                if profit is not None and fin_cost is not None and fin_cost != 0:
                    ratio = profit / abs(fin_cost)
                    m.value = round(ratio, 2)
                    m.passed = ratio >= 2.0
                    m.evidence = f"利润总额/|财务费用|={ratio:.2f}(新浪绝对额)，阈值2"
                    return m
        except Exception:  # noqa: BLE001 — 新浪失败降级 ths
            pass
    # 降级：ths 摘要利润总额/财务费用
    latest = rows[-1] if rows else {}
    profit = _to_float(latest.get("利润总额") or latest.get("营业利润"))
    fin_cost = _to_float(latest.get("财务费用"))
    if profit is None or fin_cost is None or fin_cost == 0:
        m.missing, m.evidence = True, "EBIT/利息费用数据未取得(ths摘要+新浪均无此字段)"
        return m
    ratio = profit / abs(fin_cost)
    m.value = round(ratio, 2)
    m.passed = ratio >= 2.0
    m.evidence = f"利润总额/|财务费用|={ratio:.2f}(ths代理口径)，阈值2"
    return m


def _metric_4_gross_margin(rows: list[dict], years: int) -> models.QualityMetric:
    """长期毛利率<15% 排除。"""
    m = models.QualityMetric(index=4, name="长期毛利率", threshold=15.0)
    if years < 5:
        m.inapplicable, m.inapplicable_reason = True, "上市不足5年，数据不足"
        m.evidence = "上市年限<5"
        return m
    gms = [_pct_to_ratio(r.get("销售毛利率")) for r in rows[-10:]]
    gms = [g * 100 for g in gms if g is not None]
    if not gms:
        m.missing, m.evidence = True, "毛利率数据未取得"
        return m
    avg = sum(gms) / len(gms)
    m.value = round(avg, 2)
    m.passed = avg >= 15.0
    m.evidence = f"基于{len(gms)}年平均毛利率={avg:.2f}%，阈值15%"
    return m


def _metric_5_cash_quality(rows: list[dict], years: int) -> models.QualityMetric:
    """经营现金流/净利润 5年均值<0.7 排除。"""
    m = models.QualityMetric(index=5, name="经营现金流/净利润(5年均值)", threshold=0.7)
    if years < 5:
        m.inapplicable, m.inapplicable_reason = True, "上市不足5年，数据不足"
        m.evidence = "上市年限<5"
        return m
    ratios = []
    for r in rows[-5:]:
        ocf = _to_float(r.get("每股经营现金流"))
        eps = _to_float(r.get("基本每股收益"))
        if ocf is not None and eps is not None and eps != 0:
            ratios.append(ocf / eps)
    if not ratios:
        m.missing, m.evidence = True, "经营现金流或EPS数据未取得"
        return m
    avg = sum(ratios) / len(ratios)
    m.value = round(avg, 3)
    m.passed = avg >= 0.7
    m.evidence = f"5年平均(每股经营现金流/EPS)={avg:.3f}，阈值0.7"
    return m


def _metric_6_net_margin(rows: list[dict], years: int) -> models.QualityMetric:
    """长期净利率<5% 排除。"""
    m = models.QualityMetric(index=6, name="长期净利率", threshold=5.0)
    if years < 5:
        m.inapplicable, m.inapplicable_reason = True, "上市不足5年，数据不足"
        m.evidence = "上市年限<5"
        return m
    nms = [_pct_to_ratio(r.get("销售净利率")) for r in rows[-10:]]
    nms = [n * 100 for n in nms if n is not None]
    if not nms:
        m.missing, m.evidence = True, "净利率数据未取得"
        return m
    avg = sum(nms) / len(nms)
    m.value = round(avg, 2)
    m.passed = avg >= 5.0
    m.evidence = f"基于{len(nms)}年平均净利率={avg:.2f}%，阈值5%"
    return m


def _metric_7_share_dilution(code: str, years: int) -> models.QualityMetric:
    """5年总股本膨胀>20%(非并购)排除。S108：新浪三表 share_capital 历史序列算膨胀率。"""
    m = models.QualityMetric(index=7, name="5年总股本膨胀", threshold=20.0)
    if years < 5:
        m.inapplicable, m.inapplicable_reason = True, "上市不足5年，数据不足"
        m.evidence = "上市年限<5"
        return m
    # S108：新浪三表 share_capital（实收资本(或股本)）历史序列
    try:
        from data.sources.sina_financial import fetch_merged_periods
        periods = fetch_merged_periods(code, num=10)
        shares = [p.share_capital for p in periods if p.share_capital is not None]
        if len(shares) >= 2:
            # periods 倒序（最新在前），取最新 vs 5 年前（或最早可得）
            latest = shares[0]
            oldest = shares[-1] if len(shares) >= 5 else shares[-1]
            if oldest and oldest != 0:
                dilution = (latest - oldest) / oldest * 100
                m.value = round(dilution, 2)
                m.passed = dilution <= 20.0
                m.evidence = f"股本膨胀={dilution:.2f}%(新浪share_capital: 最新{latest:.0f} vs 最早{oldest:.0f})，阈值≤20%"
                return m
    except Exception:  # noqa: BLE001 — 新浪失败降级 missing
        pass
    # 降级：ths 摘要无历史股本序列
    m.missing = True
    m.evidence = "历史股本序列未取得(新浪+ths均无)，需人工核实5年股本变化"
    return m


# ---------- 豁免（提示性） ----------

def _check_exemptions(metrics: list[models.QualityMetric], rows: list[dict],
                      moat: models.MoatSignals) -> None:
    """豁免 A/B/C 提示性标注（最终认定交用户 AI/用户）。"""
    # 豁免A 战略投入期：营收连续高增长 + 盈利承压
    revs = [_to_float(r.get("营业总收入")) for r in rows[-3:]] if len(rows) >= 3 else []
    if len(revs) >= 2 and revs[0] and revs[-1] and revs[-1] > revs[0] * 1.5:
        m1 = next((x for x in metrics if x.index == 1), None)
        if m1 and m1.passed is False:
            m1.exempt, m1.exempt_rule = True, "A 战略投入期(营收高增)"
    # 豁免B 周期底部：ROE/净利率历史均值低但近期回升（简化：留提示）
    # 豁免C 护城河补偿：毛利率持续高
    if moat.gross_margin_persistence:
        for idx in (1, 2, 6):
            mm = next((x for x in metrics if x.index == idx), None)
            if mm and mm.passed is False and not mm.exempt:
                mm.exempt, mm.exempt_rule = True, "C 护城河补偿(毛利率持续高)"
    # 注：豁免为提示性，evidence 已记依据，最终认定交 AI/用户


# ---------- 护城河代理 ----------

def moat_signals(rows: list[dict], rank: Optional[int] = None) -> models.MoatSignals:
    """护城河客观代理（不评分）。"""
    gms = [_pct_to_ratio(r.get("销售毛利率")) for r in rows[-10:]]
    gms = [g for g in gms if g is not None]
    persist = bool(gms) and all(g > 0.30 for g in gms) and len(gms) >= 3
    roes = [_pct_to_ratio(r.get("净资产收益率")) for r in rows[-10:]]
    roes = [r for r in roes if r is not None]
    roe_stab = (sum(roes) / len(roes)) if roes else None
    return models.MoatSignals(
        gross_margin_persistence=persist,
        market_share_rank=rank,
        roe_stability=round(roe_stab * 100, 2) if roe_stab is not None else None,
        identifiable_moat=[],
    )


# ---------- 编排 ----------

def compute_quality(code: str, rank: Optional[int] = None) -> models.QualityAssessment:
    """去劣7条 + 豁免 + 双口径通过率 + 年限降级。"""
    rows = _fetch_yearly_abstract(code)
    years, industry = _listing_info(code)

    metrics = [
        _metric_1_roe(rows, years),
        _metric_2_fcf(rows, years, code),
        _metric_3_interest(rows, years, industry, code),
        _metric_4_gross_margin(rows, years),
        _metric_5_cash_quality(rows, years),
        _metric_6_net_margin(rows, years),
        _metric_7_share_dilution(code, years),
    ]

    moat = moat_signals(rows, rank)
    _check_exemptions(metrics, rows, moat)

    # 双口径通过率：通过条数 / (7 − 不适用) ；
    # 注意 missing 不算不适用，分母按"可判定条数"=7−inapplicable
    pass_count = sum(1 for m in metrics if m.passed is True)
    inapp_count = sum(1 for m in metrics if m.inapplicable)
    denom_adj = 7 - inapp_count
    pass_abs = pass_count / 7
    pass_adj = (pass_count / denom_adj) if denom_adj > 0 else None

    data_years_note = None
    if 0 < years < 5:
        data_years_note = "不足5年(多项不适用)"
    elif 5 <= years < 10:
        data_years_note = "不足10年(降级口径)"

    return models.QualityAssessment(
        metrics=metrics,
        moat=moat,
        pass_count=pass_count,
        inapplicable_count=inapp_count,
        pass_rate_absolute=round(pass_abs, 4),
        pass_rate_adjusted=round(pass_adj, 4) if pass_adj is not None else None,
        data_years=years or None,
        data_years_note=data_years_note,
    )
