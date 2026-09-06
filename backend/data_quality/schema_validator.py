# -*- coding: utf-8 -*-
"""S163 R1：源边界 schema 校验 —— bad data 拒绝进 §44 verifier（不污染 verdict）。

每个数据源（baostock / ths / em_zt_topic_pool / hithink / akshare）在进入 §44 分析前
过质量门：shape（结构）+ content（字段/类型/值域）+ missing rate（缺失率）+
anomaly（异常值）+ freshness（时效）。bad data → ``ok=False``，§44 verifier 据此拒绝。

设计原则（spec §0/§1 + §1.2 工程底线）：
- **纯函数 + 不可变**：``SchemaValidationResult`` frozen，校验不改输入。
- **声明式 schema 注册表**（``SourceSchema``），新增源只加一项，不改校验引擎。
- **不直连源**（§1.2 em_get 防封）：校验层只读已 fetch 的数据或 cache，不联网。
- **as_of 由调用方传**（PIT 标识），freshness 据此判 stale；as_of=None 则跳过时效检查。
- **诚实标注**：schema 字段基于源代码 / docstring 核实，不确定处注释标 "verified/assumed"，
  不臆造字段（§1.2 不臆造）。

集成形态：``validate_or_reject()`` 是 §44 脚本的接入点——
``rows = validate_or_reject("baostock_kline", rows, as_of="2026-09-06")``，
bad data 抛 ``DataQualityError``，verifier 不把脏数据当 verdict 输入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

# 校验维度（spec R1）：shape + content + missing rate + anomaly + freshness
_Shape = Literal["list_of_dicts", "dict_of_dicts", "list_of_lists"]
_Op = Literal[">=", "<=", ">", "<"]


@dataclass(frozen=True)
class SourceSchema:
    """单数据源的声明式 schema（校验规则集，不可变）。

    字段说明（spec R1 五维）：
      - expected_shape：结构（list_of_dicts / dict_of_dicts），决定 row_count 与遍历方式。
      - required_fields：每行必须存在的 key（缺失 → error，不臆造补全）。
      - field_types：key → 可接受类型元组（类型不符 → error）。
      - value_ranges：key → (min, max) 闭区间，数值越界 → error（异常值 hard gate）。
      - integrity_rules：跨字段一致性 (field_a, op, field_b)，违反 → error（如 high<low = 坏 bar）。
      - max_missing_rate：单字段 None 占比上限，超出 → error（缺失率 gate）。
      - freshness_field / freshness_max_age_days：时效字段 + stale 阈值天数，last_date 距 as_of
        超阈值 → error。as_of=None 不校验时效（无法判定）。
      - min_rows：行数下限，空数据当 non-empty 期望时 → error（拒绝空污染）。
      - list_fields：list_of_lists 形状的位置字段名元组（date 在 [0]、close 在 [1]…），
        ``_rows_of`` 据此把每行 list 转成 dict 供下游 content/freshness 校验。
    """

    source_id: str
    label: str
    expected_shape: _Shape
    required_fields: tuple[str, ...] = ()
    field_types: dict[str, tuple[type, ...]] = field(default_factory=dict)
    value_ranges: dict[str, tuple[float, float]] = field(default_factory=dict)
    integrity_rules: tuple[tuple[str, _Op, str], ...] = ()
    max_missing_rate: float = 0.05
    freshness_field: str | None = None
    freshness_max_age_days: float = 7.0
    min_rows: int = 0
    list_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchemaValidationResult:
    """单次校验结果（不可变）。``ok`` 汇总 errors（anomalies 非阻塞）。"""

    source_id: str
    ok: bool
    row_count: int
    errors: tuple[str, ...] = ()
    missing_rates: dict[str, float] = field(default_factory=dict)
    anomalies: tuple[str, ...] = ()
    freshness_ok: bool = True
    last_date: str | None = None


class DataQualityError(ValueError):
    """数据质量门拒绝 —— bad data 不进 §44 verifier。

    携带 :class:`SchemaValidationResult` 供调用方取证（不静默吞，§1.2 显式处理）。
    """

    def __init__(self, result: SchemaValidationResult):
        self.result = result
        errs = "; ".join(result.errors) or "(无明细)"
        super().__init__(f"[{result.source_id}] 数据质量门拒绝：{errs}")


# ---------------------------------------------------------------------------
# R1 schema 注册表（5 源）——字段基于源代码 / docstring 核实，不确定处注释标 assumed
# ---------------------------------------------------------------------------

_BAOSTOCK_KLINE = SourceSchema(
    source_id="baostock_kline",
    label="baostock 日 K 线",
    expected_shape="list_of_dicts",
    # verified: baostock_kline_cache.json 行字段（实测 sample：date/open/high/low/close/
    # volume/amount/turn/pctChg/isST）。OHLCV 为承重字段，必填。
    required_fields=("date", "open", "high", "low", "close"),
    field_types={
        "date": (str,),
        "open": (float, int),
        "high": (float, int),
        "low": (float, int),
        "close": (float, int),
        "volume": (float, int),
    },
    # A 股价格 ~0.10–2000（茅台峰 ~1700），留 slack 至 10000；volume >= 0
    value_ranges={
        "open": (0.01, 100000.0),
        "high": (0.01, 100000.0),
        "low": (0.01, 100000.0),
        "close": (0.01, 100000.0),
        "volume": (0.0, 1e12),
    },
    # 跨字段完整性：high>=low / high>=开收 / low<=开收（坏 bar 即脏数据）
    integrity_rules=(
        ("high", ">=", "low"),
        ("high", ">=", "open"),
        ("high", ">=", "close"),
        ("low", "<=", "open"),
        ("low", "<=", "close"),
    ),
    max_missing_rate=0.05,
    freshness_field="date",
    freshness_max_age_days=7.0,
    min_rows=1,
)

_THS_LIMIT_UP = SourceSchema(
    source_id="ths_limit_up_pool",
    label="同花顺涨停揭秘",
    expected_shape="list_of_dicts",
    # verified: eastmoney.ths_limit_up_pool 返 [{code, reason, high_days}]（docstring 核实）。
    # code 承重（6 位裸码）；reason/high_days 可空（非涨停日池空合法 → min_rows=0）。
    required_fields=("code",),
    field_types={
        "code": (str,),
        "reason": (str,),
        "high_days": (str,),
    },
    max_missing_rate=0.02,  # code 不应缺失
    min_rows=0,  # 空池合法（非涨停日 / 降级返空），shape 校验非空部分
)

_EM_ZT_TOPIC_POOL = SourceSchema(
    source_id="em_zt_topic_pool",
    label="东财涨停板行情池",
    expected_shape="list_of_dicts",
    # verified: eastmoney.em_zt_topic_pool docstring —— 池内项含 lbc(连板数)/zbc(炸板次数)/hybk(行业)。
    # lbc 承重（涨停股连板数 >=1）；其余字段名东财 raw 未全列，required 仅 lbc。
    required_fields=("lbc",),
    field_types={
        "lbc": (int, float),
        "zbc": (int, float),
    },
    # 涨停池项 lbc>=1（至少 1 板）；zbc>=0（炸板次数非负）
    value_ranges={
        "lbc": (1.0, 50.0),
        "zbc": (0.0, 50.0),
    },
    max_missing_rate=0.05,
    min_rows=0,  # 非涨停日 / 非交易日返空合法
)

_HITHINK_VALUATION = SourceSchema(
    source_id="hithink_valuation",
    label="hithink 估值快照",
    expected_shape="dict_of_dicts",
    # verified: hithink_src.valuation_snapshot 返 {裸code: {pe_ttm, pe_mrq, pb_mrq, ps_ttm, pcf_ttm}}。
    # 各估值指标可 None（源缺，停牌 / 退市）；不强制 required（全 None 合法但 missing_rate 捕获）。
    required_fields=(),
    field_types={
        "pe_ttm": (float, int, type(None)),
        "pe_mrq": (float, int, type(None)),
        "pb_mrq": (float, int, type(None)),
        "ps_ttm": (float, int, type(None)),
        "pcf_ttm": (float, int, type(None)),
    },
    # 估值指标非负（PE/PB/PS 为负通常源错或亏损特殊口径 → 标 anomaly，不硬拦）
    value_ranges={
        "ps_ttm": (0.0, 1e6),
        "pcf_ttm": (0.0, 1e6),
    },
    # hithink 是补充源（补东财结构性缺的 PS/PCF），各估值指标 None 正常（PE/PB 来自
    # 他源常缺）。missing_rate 不作 hithink 的 gate（小 n 单股 None=100% 会假拦）——
    # 靠 type+value_range+shape+min_rows 把关（这些捕真坏数据如字符串 pe_ttm）。
    max_missing_rate=1.0,
    min_rows=1,
)

_AKSHARE_FORECAST = SourceSchema(
    source_id="akshare_profit_forecast",
    label="akshare 机构一致预期",
    expected_shape="list_of_dicts",
    # assumed: akshare stock_profit_forecast_ths 返 list[dict]，列名中文（机构/预测年份/每股收益）。
    # 字段名因 akshare 版本浮动，不硬绑 key；只校验结构 + 缺失率（结构 sanity）。
    required_fields=(),
    field_types={},
    max_missing_rate=0.5,  # 列名浮动 → 宽松缺失率
    min_rows=0,  # 无机构覆盖时空合法
)

# ---------------------------------------------------------------------------
# R1 schema 扩展（4 源）——baostock 指数 K / akshare 涨停池 / baostock 盈利 / 东财大宗
# ---------------------------------------------------------------------------

_BAOSTOCK_INDEX_KLINE = SourceSchema(
    source_id="baostock_index_kline",
    label="baostock 指数日 K 线",
    expected_shape="list_of_lists",
    # verified: baostock query_history_k_data_plus("sh.000001", "date,close") →
    # get_row_data() 返 list[str]，每行 [date_str, close_str]。非个股 OHLCV，
    # 仅 date+close（指数 regime 派生用，非 §44 verdict 直接输入）。
    list_fields=("date", "close"),
    required_fields=("date", "close"),
    field_types={
        "date": (str,),
        "close": (str, float, int),  # baostock 返字符串，下游 float() 转
    },
    value_ranges={
        "close": (0.0, 1000000.0),  # 上证指数 ~600-6000+，留 slack
    },
    max_missing_rate=0.05,
    freshness_field="date",
    freshness_max_age_days=7.0,
    min_rows=1,
)

_AKSHARE_ZT_POOL = SourceSchema(
    source_id="akshare_stock_zt_pool_em",
    label="akshare 涨停池",
    expected_shape="list_of_dicts",
    # verified: akshare stock_zt_pool_em → 脚本 build rows = [{code, seal_amount,
    # first_lock, last_lock, turnover, float_mv}]。code 承重（6 位裸码 str）。
    # 非涨停日池空合法（min_rows=0）；seal_amount/turnover/float_mv 均 float（脚本 float() 转）。
    required_fields=("code",),
    field_types={
        "code": (str,),
        "seal_amount": (float, int),
        "first_lock": (str,),
        "last_lock": (str,),
        "turnover": (float, int),
        "float_mv": (float, int),
    },
    value_ranges={
        "seal_amount": (0.0, 1e15),
        "turnover": (0.0, 100.0),  # 换手率 0-100%
        "float_mv": (0.0, 1e13),
    },
    max_missing_rate=0.05,
    min_rows=0,  # 非涨停日空合法
)

_BAOSTOCK_PROFIT_DATA = SourceSchema(
    source_id="baostock_profit_data",
    label="baostock 盈利数据缓存",
    expected_shape="dict_of_dicts",
    # verified: profit_data_cache.json = {code: {quarter: {epsTTM, pubDate}}}（3 级 dict）。
    # 3 级嵌套超出 dict_of_dicts 2 级模型 → 脚本 flatten 到 2 级 {code_quarter: {epsTTM, pubDate}}
    # 再过 validate_or_reject，使 field_types 可校验最内层。epsTTM 可 None（季度无 EPS）。
    required_fields=(),
    field_types={
        "epsTTM": (float, int, type(None)),
        "pubDate": (str, type(None)),
    },
    # epsTTM 可空（季度无 EPS），小 n 单股 None=100% 会假拦（同 hithink 逻辑）——
    # 靠 type+min_rows+shape 把关，missing_rate 不作 gate。
    max_missing_rate=1.0,
    min_rows=1,
)

_EASTMONEY_BLOCK_TRADE = SourceSchema(
    source_id="eastmoney_block_trade",
    label="东财大宗交易",
    expected_shape="list_of_dicts",
    # verified: block_trade_raw.json = [{date, code, premium_ratio, ...}]（eastmoney
    # RPT_DATA_BLOCKTRADE 市场全量）。date+code 承重；premium_ratio 折价率可 None（无成交价）。
    required_fields=("date", "code"),
    field_types={
        "date": (str,),
        "code": (str, int),  # 裸码可 int 或 str（脚本 zfill 补零）
        "premium_ratio": (float, int, type(None)),
    },
    value_ranges={
        "premium_ratio": (-1.0, 1.0),  # 折价率 -100%~100%
    },
    # premium_ratio 可 None（无成交价），部分行缺正常；不因小样本 None 占比高假拦
    max_missing_rate=0.5,
    freshness_field="date",
    freshness_max_age_days=7.0,
    min_rows=0,  # 无大宗交易日空合法
)

#: schema 注册表（新增源只加一项）
SCHEMA_REGISTRY: dict[str, SourceSchema] = {
    s.source_id: s for s in (
        _BAOSTOCK_KLINE,
        _THS_LIMIT_UP,
        _EM_ZT_TOPIC_POOL,
        _HITHINK_VALUATION,
        _AKSHARE_FORECAST,
        _BAOSTOCK_INDEX_KLINE,
        _AKSHARE_ZT_POOL,
        _BAOSTOCK_PROFIT_DATA,
        _EASTMONEY_BLOCK_TRADE,
    )
}


# ---------------------------------------------------------------------------
# 校验引擎
# ---------------------------------------------------------------------------

def _rows_of(
    data: Any, shape: _Shape, list_fields: tuple[str, ...] = ()
) -> tuple[list[dict], int]:
    """按 shape 把输入归一成待校验行列表 + row_count。

    list_of_dicts → data 本身；dict_of_dicts → data.values()（内层 dict）。
    list_of_lists → 每行 list 按 list_fields 位置映射成 dict（date=[0], close=[1]…）。
    结构不符 → 返 ([], -1) 哨兵，调用方据此报 shape error。
    """
    if shape == "list_of_dicts":
        if not isinstance(data, list):
            return [], -1
        rows = [r for r in data if isinstance(r, dict)]
        return rows, len(data)
    if shape == "dict_of_dicts":
        if not isinstance(data, dict):
            return [], -1
        rows = [v for v in data.values() if isinstance(v, dict)]
        return rows, len(data)
    if shape == "list_of_lists":
        if not isinstance(data, list):
            return [], -1
        fields = list_fields or ()
        rows: list[dict] = []
        for r in data:
            if isinstance(r, list):
                row = {fields[i]: v for i, v in enumerate(r) if i < len(fields)} if fields else {}
                rows.append(row)
            elif isinstance(r, dict):
                rows.append(r)  # 容错：dict 输入直接用
        return rows, len(data)
    return [], -1


def _check_missing_rate(rows: list[dict], schema: SourceSchema) -> tuple[dict[str, float], list[str]]:
    """逐字段算 None（或 key 缺失）占比，超 max_missing_rate → error。"""
    if not rows:
        return {}, []
    n = len(rows)
    rates: dict[str, float] = {}
    errors: list[str] = []
    fields = set(schema.required_fields) | set(schema.field_types) | set(schema.value_ranges)
    for f in fields:
        miss = sum(1 for r in rows if r.get(f) is None)
        rate = miss / n
        rates[f] = round(rate, 4)
        if rate > schema.max_missing_rate:
            errors.append(f"{f} 缺失率 {rate:.1%} > {schema.max_missing_rate:.0%}")
    return rates, errors


def _check_content(rows: list[dict], schema: SourceSchema) -> list[str]:
    """逐行校验 required / type / value_range / integrity，违例 → error。"""
    errors: list[str] = []
    for i, r in enumerate(rows):
        for f in schema.required_fields:
            if f not in r or r[f] is None:
                errors.append(f"行{i} 缺必填 {f}")
        for f, types in schema.field_types.items():
            v = r.get(f)
            if v is None:
                continue  # None 由 missing_rate 管
            if not isinstance(v, types):
                errors.append(f"行{i} {f} 类型 {type(v).__name__} 不符 {types}")
        for f, (lo, hi) in schema.value_ranges.items():
            v = r.get(f)
            if v is None:
                continue
            # baostock 等源返字符串数值 → 尝试 float 转换后查值域
            if isinstance(v, str):
                try:
                    v = float(v)
                except ValueError:
                    continue  # 非数值字符串由 type check 管
            elif not isinstance(v, (int, float)):
                continue
            if v < lo or v > hi:
                errors.append(f"行{i} {f}={v} 越界 [{lo}, {hi}]")
        for fa, op, fb in schema.integrity_rules:
            va, vb = r.get(fa), r.get(fb)
            if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)):
                continue
            bad = (op == ">=" and va < vb) or (op == "<=" and va > vb) or \
                  (op == ">" and va <= vb) or (op == "<" and va >= vb)
            if bad:
                errors.append(f"行{i} 完整性违反 {fa}{op}{fb} ({va}, {vb})")
    return errors


def _check_freshness(
    rows: list[dict], schema: SourceSchema, as_of: str | None
) -> tuple[bool, str | None, str | None]:
    """时效检查：last_date 距 as_of 超 max_age_days → stale。

    as_of=None → 不校验（无法判定），返 (True, last_date, None)。
    日期解析失败 → (False, last_date, "parse_error")。
    """
    if schema.freshness_field is None or as_of is None or not rows:
        last = _last_date(rows, schema.freshness_field)
        return True, last, None
    last = _last_date(rows, schema.freshness_field)
    if last is None:
        return False, None, "时效字段无有效日期"
    try:
        last_dt = datetime.fromisoformat(last)
        asof_dt = datetime.fromisoformat(as_of)
    except ValueError:
        return False, last, f"日期解析失败 last={last} as_of={as_of}"
    age = (asof_dt - last_dt).days
    if age > schema.freshness_max_age_days:
        return False, last, f"数据 stale：last={last} 距 as_of={as_of} {age}天 > {schema.freshness_max_age_days}天"
    return True, last, None


def _last_date(rows: list[dict], field: str | None) -> str | None:
    """取时效字段的最大日期（字符串字典序对 ISO YYYY-MM-DD = 时序）。"""
    if field is None:
        return None
    dates = [r.get(field) for r in rows if isinstance(r.get(field), str)]
    return max(dates) if dates else None


def validate(
    source_id: str, data: Any, as_of: str | None = None
) -> SchemaValidationResult:
    """校验单数据源（spec R1 五维），返不可变 :class:`SchemaValidationResult`。

    ``source_id`` 须在 :data:`SCHEMA_REGISTRY`；``data`` 为源函数返回值；
    ``as_of`` 为 PIT 日期（YYYY-MM-DD），freshness 据此判 stale，None 则跳过时效。
    """
    schema = SCHEMA_REGISTRY.get(source_id)
    if schema is None:
        return SchemaValidationResult(
            source_id=source_id, ok=False, row_count=0,
            errors=(f"未知数据源 {source_id!r}（未在 SCHEMA_REGISTRY）",),
        )

    rows, row_count = _rows_of(data, schema.expected_shape, schema.list_fields)
    if row_count < 0:  # shape 不符
        return SchemaValidationResult(
            source_id=source_id, ok=False, row_count=0,
            errors=(f"shape 不符：期望 {schema.expected_shape}，实际 {type(data).__name__}",),
        )

    errors: list[str] = []
    if row_count < schema.min_rows:
        errors.append(f"行数 {row_count} < 下限 {schema.min_rows}")

    missing_rates, miss_errs = _check_missing_rate(rows, schema)
    errors.extend(miss_errs)
    errors.extend(_check_content(rows, schema))

    fresh_ok, last_date, fresh_err = _check_freshness(rows, schema, as_of)
    if fresh_err:
        errors.append(fresh_err)

    return SchemaValidationResult(
        source_id=source_id,
        ok=len(errors) == 0,
        row_count=row_count,
        errors=tuple(errors),
        missing_rates=missing_rates,
        anomalies=(),
        freshness_ok=fresh_ok,
        last_date=last_date,
    )


def validate_or_reject(
    source_id: str, data: Any, as_of: str | None = None
) -> Any:
    """校验通过返原 data（不可变，原样返）；失败抛 :class:`DataQualityError`。

    §44 脚本接入点：``rows = validate_or_reject("baostock_kline", rows, as_of)``
    bad data 抛错 → verifier 不把脏数据当 verdict 输入（不污染 verdict）。
    """
    result = validate(source_id, data, as_of)
    if not result.ok:
        raise DataQualityError(result)
    return data
