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
    bids,  # S085 D2 五档买卖盘（push2/push2delay 双 host 降级）
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


def _resample_daily_to_period(daily: list[dict], category: int) -> list[dict]:
    """日K → 周K(category=5)/月K(category=6) resample（纯函数，不臆造）。

    按 ISO 周 / 年-月分组，open=首 high=max low=min close=末 volume/amount=sum。
    缺失字段（None）跳过聚合（不臆造 0）。
    """
    from datetime import date
    from itertools import groupby

    def _key(b: dict) -> str:
        d = b.get("date", "")
        parts = d.split("-")
        if len(parts) < 3:
            return d
        y, m, dd = int(parts[0]), int(parts[1]), int(parts[2])
        if category == 5:  # 周 K：ISO 周
            wk = date(y, m, dd).isocalendar()[1]
            return f"{y}-{wk:02d}"
        return f"{y}-{m:02d}"  # 月 K

    out: list[dict] = []
    for _k, grp in groupby(daily, key=_key):
        rows = list(grp)
        if not rows:
            continue
        highs = [r["high"] for r in rows if r.get("high") is not None]
        lows = [r["low"] for r in rows if r.get("low") is not None]
        vols = [r["volume"] for r in rows if r.get("volume") is not None]
        amts = [r["amount"] for r in rows if r.get("amount") is not None]
        out.append({
            "date": rows[-1].get("date"),
            "open": rows[0].get("open"),
            "high": max(highs) if highs else None,
            "low": min(lows) if lows else None,
            "close": rows[-1].get("close"),
            "volume": sum(vols) if vols else None,
            "amount": sum(amts) if amts else None,
        })
    return out


def _aggregate_5min_to_60min(bars_5min: list[dict]) -> list[dict]:
    """5min bars → 60min bars（A 股 4 窗口/天：9:30-10:30/10:30-11:30/13:00-14:00/14:00-15:00）。

    baostock 5min time 格式 "20260915093500000"（YYYYMMDDHHMMSSmmm）。按 date + window 分组
    聚合 open=首/high=max/low=min/close=末/volume=sum。返 bar 含 timestamp（ms，窗口开始）供 klinecharts。
    """
    def _window(time_str: str) -> str:
        if len(time_str) < 12:
            return ""
        hhmm = time_str[8:12]
        h, m = int(hhmm[:2]), int(hhmm[2:4])
        if h < 10 or (h == 10 and m <= 30):
            return "0930"  # 9:30-10:30
        if h == 10 or (h == 11 and m <= 30):
            return "1030"  # 10:30-11:30
        if h < 14 or (h == 14 and m == 0):
            return "1300"  # 13:00-14:00
        return "1400"  # 14:00-15:00

    groups: dict[tuple[str, str], list[dict]] = {}
    for b in bars_5min:
        date = b.get("date", "")
        win = _window(b.get("time", ""))
        if not date or not win:
            continue
        key = (date, win)
        if key not in groups:
            groups[key] = []
        groups[key].append(b)

    out: list[dict] = []
    for (date, win), grp in sorted(groups.items()):
        if not grp:
            continue
        highs = [g["high"] for g in grp if g.get("high") is not None]
        lows = [g["low"] for g in grp if g.get("low") is not None]
        vols = [g["volume"] for g in grp if g.get("volume") is not None]
        # timestamp = 窗口开始时间（ms，北京 +08:00）
        ts_str = f"{date.replace('-', '')}{win}00000"
        # 解析 YYYYMMDDHHMMSS + 8h offset → ms
        y, mo, d, hh, mm = int(ts_str[:4]), int(ts_str[4:6]), int(ts_str[6:8]), int(ts_str[8:10]), int(ts_str[10:12])
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        ts = int(_dt(y, mo, d, hh, mm, tzinfo=_tz(_td(hours=8))).timestamp() * 1000)
        out.append({
            "date": date,
            "timestamp": ts,
            "open": grp[0].get("open"),
            "high": max(highs) if highs else None,
            "low": min(lows) if lows else None,
            "close": grp[-1].get("close"),
            "volume": sum(vols) if vols else None,
        })
    return out


def kline(code: str, category: int = 4, offset: int = 60) -> list[dict]:
    """K线：mootdx 优先（category 4=日/5=周/6=月/11=60min 透传 frequency），空时多源回退。

    mootdx 返空（服务器/库坏，实测 bars 0 + bestip NoneType）→ kline_multi 多源回退：
    - category=4（日K）：fetch_kline 多源（baidu→sina→mootdx→akshare）sina/baidu 可拿到 ~1000 bars
    - category=5/6（周/月K）：从日K回退源 resample（_resample_daily_to_period 纯函数聚合）
    - category=11（60min）：回退源无 intraday，mootdx 坏则返 []（诚实，不臆造）
    """
    from data.sources.mootdx_src import kline as _mootdx_kline
    # category=11（60min）: baostock 5min 聚合成 60min（A 股 4 窗口/天）——独立分支，不走日K kline_multi
    if category == 11:
        try:
            from data.sources.baostock_src import fetch_5min_bars
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=offset * 2)).strftime("%Y-%m-%d")
            bars_5min = fetch_5min_bars(code, start, end)
            if bars_5min:
                agg = _aggregate_5min_to_60min(bars_5min)
                return agg[-(offset * 4):] if len(agg) > offset * 4 else agg  # offset 天 × 4 根/天
        except Exception as e:
            logging.getLogger("astock").warning("kline(%s) 60min baostock 5min 聚合失败: %s", code, e)
        return []
    # kline_multi 并发优先（~4.6s sina 1023 bars，比 mootdx 7.6s 60 bars 快+多）
    # mootdx 不稳定（bestip 慢 + 有时返空走 baostock 回退 9s）→ 作回退
    try:
        daily, _src = kline_multi(code)
        if daily:
            if category == 4:
                return daily[-offset:] if offset < len(daily) else daily
            if category in (5, 6):
                resampled = _resample_daily_to_period(daily, category)
                return resampled[-offset:] if offset < len(resampled) else resampled
            # category=11（60min）回退源无 intraday → 诚实返 []
            return []
    except Exception as e:
        logging.getLogger("astock").warning(
            "kline(%s) kline_multi failed, fallback mootdx: %s", code, e)
    # kline_multi 空/失败 → mootdx 回退（baostock 回退在 mootdx_src 内，mootdx 返空时触发）
    bars = _mootdx_kline(code, category=category, offset=offset)
    return bars if bars else []

# ── 新浪财报三表源（urllib，基本面因子组数据地基）──────────────────────────
# S108：fetch_raw/fetch_merged_periods 由 value_funnel/quality + routers/value_funnel 直接调，
# 不再经 astock 死别名 re-export（原 sina_financial_report 零调用，删）。


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
    """单票完整估值：腾讯行情 + 一致预期 EPS + 前向PE/PEG/消化年数。

    S104：PS_TTM / PCF_TTM 由 hithink_src.valuation_snapshot 补（东财结构性缺）。
    hithink 失败/熔断 → PS/PCF 仍 None（东财本来也 None，诚实缺失不崩）；
    PE/PB 仍走东财腾讯行情口径（不变）。
    """
    quotes = tencent_quote([code])
    q = quotes.get(code)
    if not q:
        raise ValueError(f"未取到 {code} 的行情")

    price = q["price"]
    out = {
        "name": q["name"], "code": code, "price": price,
        "mcap_yi": q["mcap_yi"], "pe_ttm": q["pe_ttm"], "pb": q["pb"],
        "ps_ttm": None, "pcf_ttm": None,  # S104：hithink 补（东财结构性缺）
        "pe_ttm_hithink": None, "pb_hithink": None,  # S106：备源（供 cross_validate 仲裁）
        "eps_26e": None, "eps_27e": None, "pe_26e": None,
        "cagr_pct": None, "peg": None, "digest_years": None, "analyst_count": 0,
    }

    # S104：hithink 补 PS_TTM / PCF_TTM（5min TTL 缓存，hithink_src 内部）
    # S106：同时暴露 hithink 备源 PE/PB（valuation_snapshot 已返，零额外请求），供 cross_validate 仲裁
    try:
        from data.sources.hithink_src import valuation_snapshot as _hs_val
        hs = _hs_val([code])
        if code in hs:
            out["ps_ttm"] = hs[code].get("ps_ttm")
            out["pcf_ttm"] = hs[code].get("pcf_ttm")
            out["pe_ttm_hithink"] = hs[code].get("pe_ttm")   # S106 备源（与东财腾讯口径一致）
            out["pb_hithink"] = hs[code].get("pb_mrq")       # S106 备源
    except Exception:  # noqa: BLE001 — hithink 失败不阻塞估值，PS/PCF/备源 降级 None
        out["ps_pcf_status"] = "hithink_unavailable"  # S131 R3：标源断非"无估值"，mapper 透传 data_status 给 LLM

    # S106：PE/PB 交叉验证（东财 vs hithink）——数据层一处仲裁，两出口（query_valuation 走 mapper
    # → Valuation / /api/valuation raw dict）透传，无重复仲裁代码。
    # §44 边界：PE/PB 展示非"出结论"（§44 管 winrate/r/verdict）；MAJOR_DIFFERENCE 取主源（东财）
    # 不丢数据 + discrepancy 标记告知"这值两源差>5%，别基于它下重判断"，不阻断。
    try:
        from data.validators import Verdict, cross_validate
        discrepancies: list[dict] = []
        for field, em_val, hs_val in [
            ("pe_ttm", out.get("pe_ttm"), out.get("pe_ttm_hithink")),
            ("pb", out.get("pb"), out.get("pb_hithink")),
        ]:
            if em_val is not None and hs_val is not None:  # 两源都有才仲裁
                vr = cross_validate(field, {"东财": em_val, "hithink": hs_val})
                if vr.verdict in (Verdict.DIFFERENCE, Verdict.MAJOR_DIFFERENCE):
                    discrepancies.append({
                        "field": field,
                        "verdict": vr.verdict.value,
                        "deviation_pct": vr.max_deviation_pct,
                    })  # CONSISTENT/SINGLE_SOURCE 不标（不打扰）
        if discrepancies:
            out["discrepancy"] = discrepancies
    except Exception:  # noqa: BLE001 — cross_validate 故障不阻塞估值
        pass

    try:
        rows = profit_forecast(code)
    except DependencyMissing:
        out["forecast_note"] = "一致预期需安装 akshare"
        return out

    # S132 R2：empty-DataFrame（akshare soft-block/无覆盖，非 DependencyMissing）标 forecast_status
    # 非"无分析师覆盖"——mapper 透传 forecast_status 给 LLM 区分"源断"vs"合法无覆盖"
    if not rows:
        out["forecast_status"] = "empty_or_source_unavailable"

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
