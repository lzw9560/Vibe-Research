# -*- coding: utf-8 -*-
"""S008 数据层 — raw dict → S007 Pydantic 模型映射。

本模块是 astock/gstock/market 原始 dict 与 S007 契约模型之间的**唯一**映射点。
所有字段重命名 + 单位转换集中在此，可复算、可单测。

字段对齐表见 ``specs/S008-后端数据层迁移/plan.md`` §4.1。

合规红线：``emotion_from_dict`` 显式丢弃 ``lianban_stocks``（个股名）——
聚合情绪指标不得泄露个股名（CLAUDE.md §1）。连板股榜走原始池出口，
不进 Emotion 聚合。
"""

from __future__ import annotations

from typing import Any

from models import Market
from models.enums import ReportType
from models.financials import Announcement, CompanyInfo, ConceptBlock, Financials, ValuationPercentile
from models.fund_flow import FundFlow
from models.global_stock import GlobalMetrics, GlobalStock
from models.kline import KLine, KLineBar
from models.market_snapshot import Emotion, EmotionResponse, IndustrySector, LianbanStock, MarketSnapshot, Sector, ZTPoolItem
from models.news import News
from models.normalize import normalize_stock_code
from models.quote import Quote
from models.report import Report
from models.seat import BillboardDetail, DragonTiger, DragonTigerRecord
from models.valuation import Valuation


def _numf(v: Any) -> float | None:
    """东财/腾讯数值字段可能是 '-'（停牌/无数据）→ 归一成 float 或 None。"""
    if isinstance(v, bool):  # bool 是 int 子类，先排除
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip() and v.strip() != "-":
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


# ── Quote ────────────────────────────────────────────────────────────────

def quote_from_tencent(code: str, raw: dict) -> Quote:
    """astock.tencent_quote 单 code 项 → Quote。

    单位转换：mcap_yi(亿)→market_cap(元) ×1e8；float_mcap_yi(亿)→float_market_cap ×1e8；
    amount_wan(万)→turnover(元) ×1e4。
    字段 rename：turnover_pct→turnover_rate、amplitude_pct→amplitude、
    limit_up→limit_up_price、limit_down→limit_down_price、change_amt→change_amount。
    """
    try:
        norm_code, market = normalize_stock_code(code)
    except (ValueError, AttributeError):
        norm_code, market = code, Market.A

    mcap = _numf(raw.get("mcap_yi"))
    float_mcap = _numf(raw.get("float_mcap_yi"))
    amount_wan = _numf(raw.get("amount_wan"))
    return Quote(
        code=norm_code,
        market=market,
        name=raw.get("name"),
        price=_numf(raw.get("price")),
        change_pct=_numf(raw.get("change_pct")),
        change_amount=_numf(raw.get("change_amt")),
        volume=_numf(raw.get("vol")),  # 手（tencent 若无 vol 则 None）
        turnover=amount_wan * 1e4 if amount_wan is not None else None,
        market_cap=mcap * 1e8 if mcap is not None else None,
        float_market_cap=float_mcap * 1e8 if float_mcap is not None else None,
        pe_ttm=_numf(raw.get("pe_ttm")),
        pb=_numf(raw.get("pb")),
        turnover_rate=_numf(raw.get("turnover_pct")),
        amplitude=_numf(raw.get("amplitude_pct")),
        limit_up_price=_numf(raw.get("limit_up")),
        limit_down_price=_numf(raw.get("limit_down")),
        last_close=_numf(raw.get("last_close")),
        open=_numf(raw.get("open")),
        high=_numf(raw.get("high")),
        low=_numf(raw.get("low")),
        vol_ratio=_numf(raw.get("vol_ratio")),
        pe_static=_numf(raw.get("pe_static")),
    )


def quote_from_turnover_rank(raw: dict) -> Quote:
    """astock.market_turnover_rank 单项 → Quote。

    该源字段：code/name/price/pct/amount/mcap/float_cap/industry。
    mcap 已是元；pct→change_pct；amount→turnover（元）。
    """
    code = str(raw.get("code", ""))
    try:
        norm_code, market = normalize_stock_code(code)
    except (ValueError, AttributeError):
        norm_code, market = code, Market.A
    return Quote(
        code=norm_code,
        market=market,
        name=raw.get("name"),
        price=_numf(raw.get("price")),
        change_pct=_numf(raw.get("pct")),
        turnover=_numf(raw.get("amount")),
        market_cap=_numf(raw.get("mcap")),
        float_market_cap=_numf(raw.get("float_cap")),
    )


def quote_from_gstock_us_hk(raw: dict) -> Quote:
    """gstock.us_hk_stock 嵌套结构 → 扁平 Quote。

    raw = {code, name, market, quote: {price, open, high, low, prev_close,
    amount, mcap, change_pct}, metrics: {...}}。
    """
    code = str(raw.get("code", ""))
    market_str = str(raw.get("market", "")).upper()
    market = _market_from_str(market_str, code)
    inner = raw.get("quote", {}) or {}
    return Quote(
        code=code,
        market=market,
        name=raw.get("name"),
        price=_numf(inner.get("price")),
        change_pct=_numf(inner.get("change_pct")),
        turnover=_numf(inner.get("amount")),
        market_cap=_numf(inner.get("mcap")),
        last_close=_numf(inner.get("prev_close")),
    )


def _market_from_str(market_str: str, code: str) -> Market:
    """从 gstock market 字段（NASDAQ/NYSE/US/HK/KR）或代码推断 Market。"""
    m = market_str.upper()
    if "HK" in m or m == "116":
        return Market.HK
    if "KR" in m or m == "177" or code.endswith(".KS"):
        return Market.KR
    if "US" in m or m in ("NASDAQ", "NYSE", "105", "106", "107"):
        return Market.US
    return Market.A


# ── FundFlow ─────────────────────────────────────────────────────────────

def fundflow_from_capital_flow(raw: dict, *, code: str, market: str | Market) -> FundFlow:
    """astock.stock_fund_flow_120d / fallback capital_flow 行 → FundFlow。

    rename：super_net→super_large_net、mid_net→medium_net。
    """
    if isinstance(market, Market):
        mkt = market
    else:
        mkt = _market_from_str(str(market), code)
    return FundFlow(
        code=code,
        market=mkt,
        date=raw.get("date"),
        main_net=_numf(raw.get("main_net")),
        super_large_net=_numf(raw.get("super_net")),
        large_net=_numf(raw.get("large_net")),
        medium_net=_numf(raw.get("mid_net")),
        small_net=_numf(raw.get("small_net")),
    )


# ── MarketSnapshot / Emotion / Sector ─────────────────────────────────────

def emotion_from_dict(raw: dict) -> Emotion:
    """market._emotion() 原始 dict → Emotion 模型。

    合规：**显式丢弃 lianban_stocks**（含个股名）——聚合情绪指标零个股名。
    连板股榜（客观榜单）由调用方走 astock.em_zt_topic_pool 原始池出口呈现，
    不进 Emotion 聚合。
    """
    ladder_raw = raw.get("ladder") or []
    ladder = tuple(
        {"boards": item.get("boards"), "count": item.get("count")}
        for item in ladder_raw
        if isinstance(item, dict)
    )
    return Emotion(
        max_boards=_numf(raw.get("max_boards")),
        limit_up_count=_numf(raw.get("zt_count")),
        limit_down_count=_numf(raw.get("dt_count")),
        seal_rate=_numf(raw.get("seal_rate")),
        broken_rate=_numf(raw.get("break_rate")),
        advance_rate=_numf(raw.get("promotion_rate")),
        ladder=ladder,
    )


def sector_from_dict(raw: dict) -> Sector:
    """market.get_overview().sectors 项 → Sector。"""
    return Sector(
        name=raw.get("name", ""),
        pct=_numf(raw.get("pct")),
        net=_numf(raw.get("net")),
        inflow=_numf(raw.get("inflow")),
        outflow=_numf(raw.get("outflow")),
        firms=_numf(raw.get("firms")),
    )


def market_snapshot_from_overview(raw: dict) -> MarketSnapshot:
    """market.get_overview() → MarketSnapshot（情绪 + 板块）。

    注意：get_overview 的 sentiment 字段结构与 _emotion 不同（更宽泛的市场情绪），
    这里映射 sectors；emotion 若调用方提供 _emotion 结果则用之，否则 None。
    """
    sectors_raw = raw.get("sectors") or []
    sectors = tuple(sector_from_dict(s) for s in sectors_raw if isinstance(s, dict))
    emotion_raw = raw.get("emotion")
    emotion = emotion_from_dict(emotion_raw) if isinstance(emotion_raw, dict) else None
    return MarketSnapshot(
        emotion=emotion,
        sectors=sectors,
        updated=raw.get("updated"),
    )


# 注：本模块只提供 raw→模型投影（异构接口的「新」侧）。
# legacy 消费者直接吃 ``data.sources.*.fetch_raw`` 的 raw dict（全字段，单一事实源）——
# 不走 model→dict 往返（有损，会丢 last_close/open/vol_ratio 等字段）。
# 详见 specs/S008-后端数据层迁移/plan-stage1.md「数据总线 + 异构接口」。


# ── Valuation（full_valuation raw → Valuation）───────────────────────────

def valuation_from_full_valuation(code: str, raw: dict) -> Valuation:
    """astock.full_valuation raw → Valuation。

    rename：mcap_yi→market_cap(×1e8)、pe_26e→forward_pe、eps_26e→consensus_eps。
    forecast_note 不入模型（LLM 侧 car：调用方可附 raw.get('forecast_note')）。
    """
    try:
        norm_code, market = normalize_stock_code(code)
    except (ValueError, AttributeError):
        norm_code, market = code, Market.A
    mcap_yi = _numf(raw.get("mcap_yi"))
    return Valuation(
        code=norm_code,
        market=market,
        name=raw.get("name"),
        price=_numf(raw.get("price")),
        market_cap=mcap_yi * 1e8 if mcap_yi is not None else None,
        pe_ttm=_numf(raw.get("pe_ttm")),
        pb=_numf(raw.get("pb")),
        forward_pe=_numf(raw.get("pe_26e")),
        consensus_eps=_numf(raw.get("eps_26e")),
        cagr_pct=_numf(raw.get("cagr_pct")),
        peg=_numf(raw.get("peg")),
        digest_years=_numf(raw.get("digest_years")),
        analyst_count=int(_numf(raw.get("analyst_count"))) if _numf(raw.get("analyst_count")) is not None else None,
    )


# ── Report（eastmoney reportapi row → Report）────────────────────────────

def _report_type_from_str(s: str | None) -> ReportType | None:
    """东财 emRatingName → ReportType 枚举。未知值 → None（不抛）。"""
    if not s:
        return None
    table = {
        "买入": ReportType.BUY, "强买": ReportType.BUY, "推荐": ReportType.BUY,
        "增持": ReportType.OVERWEIGHT, "强推": ReportType.OVERWEIGHT, "优大于市": ReportType.OVERWEIGHT,
        "中性": ReportType.NEUTRAL, "同步大市": ReportType.NEUTRAL,
        "减持": ReportType.UNDERWEIGHT, "弱于大市": ReportType.UNDERWEIGHT,
        "卖出": ReportType.SELL,
    }
    return table.get(str(s).strip())


def report_from_eastmoney_row(code: str, raw: dict, market: Market = Market.A) -> Report:
    """eastmoney_reports 单行 → Report。rename：orgSName→org、publishDate→publish_date、
    emRatingName→report_type（枚举映射）。researcher/rating_change/target_price/eps_forecast
    从完整行恢复（字段名按东财 reportapi 实际键，缺失则 None）。"""
    return Report(
        code=code,
        market=market,
        title=raw.get("title"),
        org=raw.get("orgSName") or raw.get("org"),
        researcher=raw.get("researcherName") or raw.get("researcher"),
        publish_date=(raw.get("publishDate") or "")[:10] or None,
        report_type=_report_type_from_str(raw.get("emRatingName") or raw.get("ratingName")),
        rating_change=raw.get("ratingChangeName") or raw.get("ratingChange"),
        target_price=_numf(raw.get("emRatingValue") or raw.get("targetPrice")),
        eps_forecast=_numf(raw.get("predictNextTwoYearEps") or raw.get("epsForecast")),
    )


# ── News（akshare stock_news_em row → News）─────────────────────────────

def news_from_akshare_row(code: str, raw: dict, market: Market = Market.A) -> News:
    """akshare stock_news_em 单行（中文键）→ News。
    rename：新闻标题→title、发布时间→publish_time、文章来源→source。
    content/keywords 从完整行恢复（akshare 列名）。"""
    return News(
        code=code,
        market=market,
        title=raw.get("新闻标题") or raw.get("title"),
        content=raw.get("内容") or raw.get("content"),
        publish_time=raw.get("发布时间") or raw.get("publish_time"),
        source=raw.get("文章来源") or raw.get("source"),
        keywords=raw.get("关键词") or raw.get("keywords"),
    )


# ── LianbanStock / EmotionResponse（market._emotion raw）─────────────────

def lianban_stock_from_dict(raw: dict) -> LianbanStock:
    """market._emotion().lianban_stocks 项 → LianbanStock（客观榜单行）。"""
    return LianbanStock(
        code=str(raw.get("code", "")),
        name=raw.get("name"),
        boards=int(_numf(raw.get("boards"))) if _numf(raw.get("boards")) is not None else None,
        price=_numf(raw.get("price")),
        pct=_numf(raw.get("pct")),
        amount=_numf(raw.get("amount")),
        float_cap=_numf(raw.get("float_cap")),
        industry=raw.get("industry"),
    )


def emotion_response_from_dict(raw: dict) -> EmotionResponse:
    """market._emotion() raw → EmotionResponse（clean Emotion + lianban_stocks 并列出口）。

    Emotion 子对象走 ``emotion_from_dict``（零个股名、ladder 无 plus）；
    lianban_stocks 同层暴露客观榜单。date/lianban_count/zb_count/yzt_count 透传。
    """
    stocks_raw = raw.get("lianban_stocks") or []
    stocks = tuple(
        lianban_stock_from_dict(s) for s in stocks_raw if isinstance(s, dict)
    )
    return EmotionResponse(
        emotion=emotion_from_dict(raw),
        lianban_stocks=stocks,
        date=raw.get("date"),
        lianban_count=int(_numf(raw.get("lianban_count"))) if _numf(raw.get("lianban_count")) is not None else None,
        zb_count=int(_numf(raw.get("zb_count"))) if _numf(raw.get("zb_count")) is not None else None,
        yzt_count=int(_numf(raw.get("yzt_count"))) if _numf(raw.get("yzt_count")) is not None else None,
    )


# ── GlobalMetrics / GlobalStock（gstock.us_hk_stock raw）────────────────

def global_metrics_from_gstock(raw_metrics: dict | None) -> GlobalMetrics | None:
    """gstock.us_hk_stock().metrics → GlobalMetrics。None（韩股）→ None。"""
    if not isinstance(raw_metrics, dict) or not raw_metrics:
        return None
    return GlobalMetrics(
        report_date=raw_metrics.get("report_date"),
        revenue=_numf(raw_metrics.get("revenue")),
        revenue_yoy=_numf(raw_metrics.get("revenue_yoy")),
        net_profit=_numf(raw_metrics.get("net_profit")),
        eps=_numf(raw_metrics.get("eps")),
        roe=_numf(raw_metrics.get("roe")),
        gross_margin=_numf(raw_metrics.get("gross_margin")),
        net_margin=_numf(raw_metrics.get("net_margin")),
        debt_ratio=_numf(raw_metrics.get("debt_ratio")),
    )


def global_stock_from_gstock(raw: dict) -> GlobalStock:
    """gstock.us_hk_stock 嵌套 raw → GlobalStock（扁平 Quote + metrics 子模型）。"""
    return GlobalStock(
        code=str(raw.get("code", "")),
        name=raw.get("name"),
        market=raw.get("market"),
        quote=quote_from_gstock_us_hk(raw),
        metrics=global_metrics_from_gstock(raw.get("metrics")),
    )


# ── KLine ───────────────────────────────────────────────────────────────

def _bar_date(raw: dict) -> str | None:
    """从 mootdx bar 项归一日期为 YYYY-MM-DD。

    mootdx ``bars`` 返回字段随版本变化：可能直接含 ``date``/``datetime`` 字符串，
    也可能含 ``year``/``month``/``day`` 数值分量。优先取已有字符串，否则拼分量。
    """
    for k in ("date", "datetime"):
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v[:10]
    y = raw.get("year")
    m = raw.get("month")
    d = raw.get("day")
    if isinstance(y, int) and isinstance(m, int) and isinstance(d, int):
        return f"{y:04d}-{m:02d}-{d:02d}"
    return None


def kline_from_mootdx(code: str, raw_bars: list[dict], market: Market = Market.A) -> KLine:
    """astock.kline（mootdx 源）raw bars list[dict] → KLine。

    字段映射：``vol``→``volume``、``amount``→``turnover``（元）；缺字段=``None``
    （T13b 放宽后的 KLineBar 支持部分 bar）。不臆造——无值即 None。
    """
    try:
        norm_code, norm_market = normalize_stock_code(code)
    except (ValueError, AttributeError):
        norm_code, norm_market = code, market

    bars: list[KLineBar] = []
    for raw in raw_bars or []:
        vol = _numf(raw.get("vol"))
        bars.append(KLineBar(
            date=_bar_date(raw),
            open=_numf(raw.get("open")),
            close=_numf(raw.get("close")),
            high=_numf(raw.get("high")),
            low=_numf(raw.get("low")),
            volume=int(vol) if vol is not None else None,
            turnover=_numf(raw.get("amount")),
            amplitude=_numf(raw.get("amplitude")),
        ))
    return KLine(code=norm_code, market=norm_market, bars=tuple(bars))


# ── ZTPoolItem ──────────────────────────────────────────────────────────

def zt_pool_item_from_dict(raw: dict, pool_date: str | None = None) -> ZTPoolItem:
    """em_zt_topic_pool 单项 raw dict → ZTPoolItem。

    raw 键→model 字段：c→code、n→name、lbc→boards、fbt→seal_time、zbc→broken_count、
    zje→limit_price、open→open、seal_amount→seal_amount、float_shares→float_shares、
    prev_close→prev_close、zdp→limit_pct、hybk→industry。
    ``pool_date`` 为合成字段（service 注入池日期），默认 None。
    """
    return ZTPoolItem(
        code=str(raw.get("c", "")),
        name=raw.get("n"),
        boards=_numf(raw.get("lbc")),
        seal_time=_numf(raw.get("fbt")),
        broken_count=_numf(raw.get("zbc")),
        limit_price=_numf(raw.get("zje")),
        open=_numf(raw.get("open")),
        seal_amount=_numf(raw.get("seal_amount")),
        float_shares=_numf(raw.get("float_shares")),
        prev_close=_numf(raw.get("prev_close")),
        limit_pct=_numf(raw.get("zdp")),
        industry=raw.get("hybk"),
        pool_date=pool_date,
    )


# ── 公司基本面（T13d）────────────────────────────────────────────────────

def financials_from_dict(raw: dict) -> Financials:
    """astock.financials raw → Financials（akshare 口径）。"""
    return Financials(
        revenue=_numf(raw.get("revenue")),
        net_profit=_numf(raw.get("net_profit")),
        roe=_numf(raw.get("roe")),
        gross_margin=_numf(raw.get("gross_margin")),
        net_margin=_numf(raw.get("net_margin")),
        period=raw.get("period"),
    )


def valuation_percentile_from_dict(raw: dict) -> ValuationPercentile:
    """astock.valuation_percentile raw（nested {pe_ttm:{percentile}, pb:{percentile}}）→ ValuationPercentile。"""
    pe = raw.get("pe_ttm") or {}
    pb = raw.get("pb") or {}
    return ValuationPercentile(
        pe_ttm_percentile=_numf(pe.get("percentile")) if isinstance(pe, dict) else None,
        pb_percentile=_numf(pb.get("percentile")) if isinstance(pb, dict) else None,
    )


def company_info_from_individual_info(raw: dict) -> CompanyInfo:
    """astock.individual_info raw（akshare {行业, 上市时间, 上市日期}）→ CompanyInfo。"""
    return CompanyInfo(
        industry=raw.get("行业"),
        listing_date=raw.get("上市时间") or raw.get("上市日期"),
    )


# ── 龙虎榜 / 席位 / 行业 / 公告 / 概念（T13e）─────────────────────────────

def dragon_tiger_from_dict(raw: dict) -> DragonTiger:
    """astock.dragon_tiger_board raw（{records:[{net_buy}], institution:{net_amt}}）→ DragonTiger。"""
    records = []
    for r in (raw.get("records") or []):
        records.append(DragonTigerRecord(net_buy=_numf(r.get("net_buy"))))
    inst = raw.get("institution") or {}
    return DragonTiger(
        records=tuple(records),
        institution_net=_numf(inst.get("net_amt")) if isinstance(inst, dict) else None,
    )


def billboard_detail_from_dict(raw: dict) -> BillboardDetail:
    """astock.eastmoney_datacenter billboard 明细行 raw → BillboardDetail。"""
    trade_date = raw.get("TRADE_DATE")
    return BillboardDetail(
        buy=_numf(raw.get("BUY")),
        sell=_numf(raw.get("SELL")),
        net=_numf(raw.get("NET")),
        security_code=raw.get("SECURITY_CODE"),
        trade_date=str(trade_date)[:10] if trade_date else None,
        operate_dept_name=raw.get("OPERATEDEPT_NAME"),
        operate_dept_code=raw.get("OPERATEDEPT_CODE"),
    )


def industry_sector_from_dict(raw: dict) -> IndustrySector:
    """astock.industry_comparison 单板块 raw（{name,change_pct,up_count,down_count}）→ IndustrySector。"""
    return IndustrySector(
        name=str(raw.get("name", "")),
        change_pct=_numf(raw.get("change_pct")),
        up_count=int(_numf(raw.get("up_count"))) if raw.get("up_count") is not None else None,
        down_count=int(_numf(raw.get("down_count"))) if raw.get("down_count") is not None else None,
    )


def announcement_from_dict(raw: dict) -> Announcement:
    """astock.announcements 单条 raw（{title,date,type}）→ Announcement。"""
    return Announcement(
        title=raw.get("title"),
        date=raw.get("date"),
        type=raw.get("type"),
    )


def concept_blocks_from_dict(raw: dict) -> list[ConceptBlock]:
    """astock.concept_blocks raw（{boards:[{name}]}）→ list[ConceptBlock]。"""
    return [ConceptBlock(name=b.get("name")) for b in (raw.get("boards") or [])]
