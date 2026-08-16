"""A股全栈数据层 —— S008 门面（facade）。

本模块原 795 行取数逻辑已按数据源拆分到 ``backend/data/sources/*``（tencent /
eastmoney / akshare_src / mootdx_src / cninfo），本文件仅作**薄门面**：
- 公开函数与返回形状一字不改（仍返 raw dict），28 个消费者调用面不变；
- 被外部直访的内部名（``UA`` / ``DependencyMissing`` / ``get_prefix`` /
  ``_parse_gtimg`` / ``_numf`` / ``_akshare``）保留 re-export；
- 东财请求仍走 ``data.transport.eastmoney_get``（防封底线，``em_get`` 即其别名）。

异构接口（数据总线 + 无状态 dispatch）：legacy 消费者经本门面拿 raw（全字段，
不丢）；新消费者经 ``data.mappers.*_from_dict(raw)`` 拿 S007 模型。详见
``specs/S008-后端数据层迁移/plan-stage1.md``。

合规：本模块只按用户传入的代码返回客观数据，不预置任何标的、不排名、不建议。
"""

from __future__ import annotations

import logging
import math

# 抑制 urllib3 重试警告（东财 push2 偶发断连是正常的，不需要刷屏）
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)

# ── 共享件 re-export（被外部直访）──────────────────────────────────────────
from data.sources._common import UA, DependencyMissing  # noqa: F401,E402

# ── tencent 源（urllib 行情底座）────────────────────────────────────────────
from data.sources.tencent import (  # noqa: F401,E402
    get_prefix,
    _parse_gtimg,
    A_INDICES,
    fetch_raw as tencent_quote,
    index_raw as index_quote,
)

# ── eastmoney 源（em_get 系 + 直 requests 研报/公告/热门概念）─────────────────
# em_get = 东财统一请求入口（薄封装 → data.transport.eastmoney_get，防封底线）
from data.transport import eastmoney_get as em_get  # noqa: F401,E402
from data.sources.eastmoney import (  # noqa: F401,E402
    _numf,
    _report_session,
    _REPORT_API,
    _PDF_TPL,
    _DATACENTER_URL,
    _ZTB_UT,
    _ZTB_CACHE_TTL,
    _ztb_cache,
    eastmoney_reports,
    eastmoney_industry_reports,
    pdf_url,
    announcements,
    em_zt_topic_pool,
    market_turnover_rank,
    eastmoney_datacenter,
    margin_trading,
    block_trade,
    holder_num_change,
    dividend_history,
    stock_fund_flow_120d,
    dragon_tiger_board,
    lockup_expiry,
    concept_blocks,
    hot_concepts,
    industry_comparison,
    ths_limit_up_pool,  # S049 同花顺涨停揭秘（交叉验证/降级备用源）
)

# ── akshare 源（惰性）──────────────────────────────────────────────────────
from data.sources.akshare_src import (  # noqa: F401,E402
    _akshare,
    profit_forecast,
    stock_news,
    individual_info,
    disclosure,
    financials,
    valuation_percentile,
)

# ── mootdx 源（惰性）───────────────────────────────────────────────────────
from data.sources.mootdx_src import _mootdx_client, kline, finance  # noqa: F401,E402

# ── cninfo 源（直 requests 互动易）─────────────────────────────────────────
from data.sources.cninfo import investor_qa  # noqa: F401,E402

# ── baidu 源（urllib 日K线，不封 IP，自带 MA5/10/20）────────────────────────
from data.sources.baidu import fetch_raw as baidu_kline  # noqa: F401,E402

# ── 多源 kline 解析器（职责链+策略，baidu→sina→mootdx→akshare 回退）──────────
from data.sources.kline_resolver import fetch_kline as kline_multi  # noqa: F401,E402

# ── 新浪财报三表源（urllib，基本面因子组数据地基）──────────────────────────
from data.sources.sina_financial import fetch_raw as sina_financial_report  # noqa: F401,E402


# ---------------------------------------------------------------------------
# 估值计算（纯函数，无数据源，留本模块）
# ---------------------------------------------------------------------------

def calc_peg(pe: float, cagr: float) -> float:
    if cagr <= 0:
        return float("inf")
    return pe / (cagr * 100)


def pe_digestion(current_pe: float, cagr: float, target_pe: float = 30) -> float:
    if current_pe <= target_pe:
        return 0.0
    if cagr <= 0:
        return float("inf")
    return math.log(current_pe / target_pe) / math.log(1 + cagr)


def full_valuation(code: str) -> dict:
    """单票完整估值：腾讯行情 + 一致预期 EPS + 前向PE/PEG/消化年数。"""
    quotes = tencent_quote([code])
    q = quotes.get(code)
    if not q:
        raise ValueError(f"未取到 {code} 的行情")

    price = q["price"]
    out = {
        "name": q["name"], "code": code, "price": price,
        "mcap_yi": q["mcap_yi"], "pe_ttm": q["pe_ttm"], "pb": q["pb"],
        "eps_26e": None, "eps_27e": None, "pe_26e": None,
        "cagr_pct": None, "peg": None, "digest_years": None, "analyst_count": 0,
    }

    try:
        rows = profit_forecast(code)
    except DependencyMissing:
        out["forecast_note"] = "一致预期需安装 akshare"
        return out

    def _eps(row: dict):
        # 同花顺对覆盖不全的股票会缺「均值」或给 '-' 占位，硬取会让整只票的估值接口 502
        try:
            return float(str(row.get("均值", "")).replace(",", ""))
        except ValueError:
            return None

    eps_26 = eps_27 = None
    for row in rows:
        y = str(row.get("年度", ""))
        if "2026" in y:
            eps_26 = _eps(row)
            try:
                out["analyst_count"] = int(float(row.get("预测机构数") or 0))
            except (TypeError, ValueError):
                pass
        elif "2027" in y:
            eps_27 = _eps(row)

    out["eps_26e"], out["eps_27e"] = eps_26, eps_27
    if eps_26 and eps_26 > 0:
        pe_26e = price / eps_26
        out["pe_26e"] = round(pe_26e, 1)
        if eps_27:
            cagr = eps_27 / eps_26 - 1
            out["cagr_pct"] = round(cagr * 100, 0)
            peg = calc_peg(pe_26e, cagr)
            out["peg"] = round(peg, 2) if peg != float("inf") else None
            dig = pe_digestion(pe_26e, cagr)
            out["digest_years"] = round(dig, 1) if dig != float("inf") else None
    return out
