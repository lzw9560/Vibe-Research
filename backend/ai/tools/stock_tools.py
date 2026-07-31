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
    "查单只个股的完整估值：行情 + 机构一致预期 EPS + 前向PE/PEG/PE消化年数。",
    params={"code": {"description": "6 位股票代码"}},
)
def query_valuation(code: str) -> dict:
    raw = astock.full_valuation(str(code))
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
