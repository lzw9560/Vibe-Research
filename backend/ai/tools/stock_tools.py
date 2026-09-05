"""S010 T3：7 个声明式工具包装（移自 chat._exec_tool 硬分支）。

每个 `@register_tool` 装饰的函数 = 工具签名（供反射生成 schema） + 执行逻辑
（调 astock/gstock/mappers 返 S007 模型 model_dump）。保留原 `_exec_tool`
分支的取数与映射语义，使测试 `monkeypatch astock.xxx` 继续生效。

合规（CLAUDE.md §1 弱合规）：工具只返回客观数据 + 研究性判断 payload；
方向性研判由 LLM 在 SYSTEM_PROMPT 约束下给出，工具不越权。
东财端点经 `em_get`（astock 内部已封装），不裸调 requests（工程底线）。
"""
from __future__ import annotations

import astock
import gstock
from data import mappers

from .registry import register_tool


# ── 5 个数据工具（A 股 + 美港股） ─────────────────────────────────────

@register_tool(
    "query_quote",
    "查 A 股实时行情：现价/涨跌/PE/PB/市值/换手/涨跌停。可批量。",
    params={"codes": {"description": "6 位股票代码列表，如 ['600519','000858']"}},
)
def query_quote(codes: list[str]) -> dict:
    coerced = [str(c) for c in codes]
    raw = astock.tencent_quote(coerced)
    return {c: mappers.quote_from_tencent(c, r).model_dump(mode="json") for c, r in raw.items()}


@register_tool(
    "query_valuation",
    "查单只个股的完整估值：行情 + 机构一致预期 EPS + 前向PE/PEG/PE消化年数。"
    "S106：PE/PB 两源（东财 vs hithink）差异>5% 标 discrepancy（full_valuation 数据层仲裁，本工具透传）。",
    params={"code": {"description": "6 位股票代码"}},
)
def query_valuation(code: str) -> dict:
    raw = astock.full_valuation(str(code))
    # S106：discrepancy 在 full_valuation 数据层仲裁生成（astock.py），mapper 透传进 Valuation，
    # 本工具无需重复仲裁。raw.get("discrepancy") 经 mapper 已入 model_dump。
    out = mappers.valuation_from_full_valuation(str(code), raw).model_dump(mode="json")
    if raw.get("forecast_note"):
        out["note"] = raw["forecast_note"]
    return out


@register_tool(
    "query_reports",
    "查个股近期研报列表（标题/机构/评级/日期）。",
    params={"code": {"description": "6 位股票代码"}},
)
def query_reports(code: str) -> list[dict]:
    rows = astock.eastmoney_reports(str(code), max_pages=1)[:15]
    return [mappers.report_from_eastmoney_row(str(code), r).model_dump(mode="json") for r in rows]


@register_tool(
    "query_news",
    "查个股近期新闻（标题/时间/来源）。",
    params={"code": {"description": "6 位股票代码"}},
)
def query_news(code: str) -> list[dict]:
    rows = astock.stock_news(str(code), limit=15)
    return [mappers.news_from_akshare_row(str(code), r).model_dump(mode="json") for r in rows]


@register_tool(
    "query_global_stock",
    "查美股 / 港股 / 韩股个股：行情（现价/涨跌/市值/成交额）+ 关键财务指标（韩股仅行情、无财务）。"
    "美股用字母代码(如 AAPL/NVDA)，港股用数字(如 00700)，韩股用 6 位数字加 .KS 后缀"
    "(如三星 005930.KS、SK海力士 000660.KS)。",
    params={"symbol": {"description": "美股字母代码 / 港股代码 / 韩股 XXXXXX.KS"}},
)
def query_global_stock(symbol: str) -> dict:
    raw = gstock.us_hk_stock(str(symbol))
    if not raw:
        return {"error": "未找到该美股/港股/韩股代码"}
    return mappers.global_stock_from_gstock(raw).model_dump(mode="json")


@register_tool(
    "query_intraday_features",
    "查个股近期盘中封单特征（last_lock_time 最后封死时刻 / broken_duration_min 开板时长 / "
    "max_drop_pct 最大回撤 / limit_price 涨停价）。读 seal_derived_features 预采集表。"
    "T6.1 辅助层——辅助非 edge：§44 H2 verdict lift=0.7843 劣于随机（封板时间无 edge），"
    "仅供 AI 看盘中结构，非买卖信号、非 validated edge。",
    params={
        "code": {"description": "6 位股票代码"},
        "days": {"description": "近 N 日（默认 5）"},
    },
)
def query_intraday_features(code: str, days: int = 5) -> list[dict]:
    # 懒导入：stock_tools import 时 risk 可能未就绪 + 避免循环；fresh env 表不存在返 []
    import sqlite3  # noqa: PLC0415
    from risk.seal_intraday_collector import _get_conn  # noqa: PLC0415
    note = "辅助非 edge（§44 H2 lift=0.7843 劣于随机，仅供看盘中结构）"
    try:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT date, last_lock_time, broken_duration_min, max_drop_pct, "
                "limit_price, data_status FROM seal_derived_features "
                "WHERE code = ? ORDER BY date DESC LIMIT ?",
                (str(code), int(days)),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # fresh env 未跑迁移 / 表不存在 → [] 不臆造（交调用方降级，非 edge 标注仍诚实）
        return []
    return [
        {
            "date": r["date"], "last_lock_time": r["last_lock_time"],
            "broken_duration_min": r["broken_duration_min"], "max_drop_pct": r["max_drop_pct"],
            "limit_price": r["limit_price"], "data_status": r["data_status"],
            "note": note,
        }
        for r in rows
    ]


# ── 2 个预测工具（S017 T11，研究参考性 payload + 免责） ───────────────
# 懒导入 routers.prediction：避免 stock_tools → routers → app → chat →
# ai.tools → stock_tools 的循环（chat.py import 时 routers 可能尚未就绪）。

@register_tool(
    "prediction_short_sector",
    "查短线板块预测级联快照（S1/S2/S3 阶段概率）。研究参考性判断，非投资建议。",
    params={
        "stage": {
            "enum": ["s1", "s2", "s3"],
            "description": "级联阶段：s1=T-1收盘后/s2=T开盘前/s3=T竞价",
        },
        "date": {"description": "交易日期 YYYY-MM-DD，默认今日"},
    },
)
def prediction_short_sector(stage: str, date: str | None = None) -> dict:
    from routers.prediction import prediction_payload

    s = str(stage)
    if s not in ("s1", "s2", "s3"):
        return {"error": "stage must be one of s1|s2|s3"}
    return prediction_payload("short_sector", s, date)


@register_tool(
    "prediction_intraday_framework",
    "查盘中教育性研判框架（S4 看什么/怎么判）：量比/分时量价/封板资金/龙头属性。"
    "教育参考，非信号、非交易指令。",
    params=None,
)
def prediction_intraday_framework() -> dict:
    from routers.prediction import intraday_framework_payload

    return intraday_framework_payload("short_sector")


# ── S104：hithink 特色数据工具（异动/飙升/热股榜，项目从无独立源） ──────

@register_tool(
    "query_skyrocket",
    "查 A 股飙升榜（同花顺口径，hithink 独家）：rank/heat/rank_change/rank_trend。"
    "东财无此数据源。period=day(日榜,默认) / hour(小时榜)。",
    params={"period": {"description": "周期：day(日榜) / hour(小时榜)", "default": "day"}},
)
def query_skyrocket(period: str = "day") -> list[dict]:
    from data.sources.hithink_src import skyrocket
    return skyrocket(str(period))


@register_tool(
    "query_hot_stock",
    "查 A 股热股榜（同花顺口径，hithink 独家）：rank/heat/rank_change/rank_trend。"
    "东财无此数据源。period=day / hour。",
    params={"period": {"description": "周期：day(日榜) / hour(小时榜)", "default": "day"}},
)
def query_hot_stock(period: str = "day") -> list[dict]:
    from data.sources.hithink_src import hot_stock
    return hot_stock(str(period))


@register_tool(
    "query_anomaly",
    "查 A 股异动分析（同花顺口径，hithink 独家）：个股异动标签/原因。"
    "东财无独立异动源。tag_codes 可选过滤异动类型。盘后可能空（异动本就少）。",
    params={"tag_codes": {"description": "可选，异动类型标签逗号分隔过滤"}},
)
def query_anomaly(tag_codes: str | None = None) -> list[dict]:
    from data.sources.hithink_src import anomaly_list
    return anomaly_list(tag_codes)
