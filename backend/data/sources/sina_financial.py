# -*- coding: utf-8 -*-
"""S008 新浪财报三表源（urllib 底座，不限流但慢 12-25s）。

利润表 lrb / 资产负债表 fzb / 现金流量表 llb——P1 基本面因子组的数据地基。
quality-screen 7 因子（ROE/FCF/利息覆盖/毛利率/OCF/净利率/股本膨胀）与
earnings-review 5 异常信号（应收/存货/OCF<NI/资本化/非经常性）从三表算。

与东财 datacenter 财务摘要**异构交叉验证**（financial-data skill 契约：
误差≤1% 取主源、1-5% 标记、>5% 查原始财报），落 ``data/validators.py``。

公开：
- ``fetch_raw(code, report_type, num)``：单股票单表，返 period-keyed rows
  ``list[dict]``（按报告期倒序，keys 为中文科目 + ``"报告期"``，值字符串；
  含同比时附 ``"<科目>_同比"``）。
- ``_fetch_json``：薄 urllib 请求层（测试 monkeypatch 点）。

合规：只按用户传入代码返回客观数据，不预置标的。
NO-LOOK-AHEAD：财报是已披露历史数据；当期财报在披露日后才可用，消费方须按
披露日对齐（availability_offset），本源不负责对齐。
"""
from __future__ import annotations

import json
import urllib.request

from circuit_breaker import CircuitBreakerConfig, get_breaker

from ._common import UA
from .tencent import get_prefix

_SINA_FIN_URL = ("https://quotes.sina.cn/cn/api/openapi.php/"
                 "CompanyFinanceService.getFinanceReport2022")

# S134：新浪三表慢 12-25s、3×/code、无 Sina 备份——threshold=3 让 1 股完整
# outage（3 表全失败）即 trip，而非默认 5（1.5 股 150s）。first-write-wins 注入。
_SINA_FIN_BREAKER = get_breaker(
    "sina_financial", CircuitBreakerConfig(failure_threshold=3)
)


def _fetch_json(code: str, report_type: str = "lrb", num: int = 8) -> dict:
    """新浪财报三表原始 JSON。urllib 不限流；timeout 30s（实测 12-25s 留余量）。"""
    prefix = get_prefix(code)
    from urllib.parse import urlencode
    params = {
        "paperCode": f"{prefix}{code}",
        "source": report_type,   # lrb / fzb / llb
        "type": "0",
        "page": "1",
        "num": str(num),
    }
    url = _SINA_FIN_URL + "?" + urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse(report_list: dict, num: int) -> list[dict]:
    """result.data.report_list（period 键 dict）→ 按报告期倒序的 rows list[dict]。

    每期一条 dict：``{"报告期": "YYYY-MM-DD", "<科目>": "<值>", "<科目>_同比": "<同比>"}``。
    空标题/None 值跳过；同比仅在有值时附加。
    """
    if not report_list:
        return []
    rows: list[dict] = []
    for period in sorted(report_list.keys(), reverse=True)[:num]:
        obj = report_list[period] or {}
        rec = {"报告期": f"{period[:4]}-{period[4:6]}-{period[6:8]}"}
        for it in obj.get("data", []) or []:
            title = it.get("item_title", "")
            if not title or it.get("item_value") is None:
                continue
            rec[title] = it.get("item_value")
            tongbi = it.get("item_tongbi")
            if tongbi not in (None, ""):
                rec[title + "_同比"] = tongbi
        rows.append(rec)
    return rows


def fetch_raw(code: str, report_type: str = "lrb", num: int = 8) -> list[dict]:
    """单股票单表 period rows（中文科目键，倒序）。

    S134：顶加 sina_financial 熔断——OPEN fast-fail（raise RuntimeError，被
    fetch_merged_periods per-table catch 吞成 []）；_fetch_json raise →
    record_failure + re-raise；正常返 → record_success + 返 _parse 结果。
    """
    breaker = get_breaker("sina_financial")
    if not breaker.allow_request():
        raise RuntimeError(
            f"[CircuitBreaker:sina_financial] 新浪三表源熔断中，快速失败（{code}/{report_type}）"
        )
    try:
        d = _fetch_json(code, report_type, num)
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        raise
    report_list = d.get("result", {}).get("data", {}).get("report_list", {}) or {}
    return _parse(report_list, num)


def fetch_merged_periods(code: str, num: int = 8):
    """S108：同 code 调三表 fetch_raw → 按 period 对齐 merge raw → mapper 产完整 FinancialPeriod。

    FinancialPeriod frozen，一次只填一表字段——故合并须在喂 mapper 前合并 raw dict
    （mappers.merge_three_statements 按「报告期」对齐）。返按 period 倒序的完整
    FinancialPeriod 列表（每期含 lrb+fzb+llb 字段 + share_capital）。

    任一表 fetch 失败 → 该表当空 rows，merge 仍用其余两表（不阻断，缺失字段 None）。
    全失败 → 返 []（调用方 anomaly 标 inapplicable / quality 回退 ths）。
    """
    from data.mappers import merge_three_statements, sina_financials_from_rows

    try:
        lrb = fetch_raw(code, "lrb", num)
    except Exception:  # noqa: BLE001 — 单表失败不阻断，降级空 rows
        lrb = []
    try:
        fzb = fetch_raw(code, "fzb", num)
    except Exception:  # noqa: BLE001
        fzb = []
    try:
        llb = fetch_raw(code, "llb", num)
    except Exception:  # noqa: BLE001
        llb = []
    if not (lrb or fzb or llb):
        return []
    merged = merge_three_statements(lrb, fzb, llb)
    return sina_financials_from_rows(merged, report_type="merged")
