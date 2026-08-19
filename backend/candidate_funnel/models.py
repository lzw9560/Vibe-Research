# -*- coding: utf-8 -*-
"""candidate_funnel 核心数据模型（Pydantic v2）。

对齐 specs/S002-plan.md §2 与 specs/S002-打板工作流重构.md §5。
合规：DiagnosisCard 无方向结论词（AC10）；IndicatorSet.missing 透明（AC6）。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- 指标层 ----------
class Announcement(BaseModel):
    """个股公告（客观呈现，不含行动建议）。"""

    title: str
    date: str  # YYYY-MM-DD
    type: Optional[str] = None


class IndicatorSet(BaseModel):
    """单只股票六类短线指标快照（取不到的字段为 None 并记入 missing）。"""

    code: str
    name: str
    # 量价
    price: Optional[float] = None
    change_pct: Optional[float] = None
    turnover_pct: Optional[float] = None  # 换手
    vol_ratio: Optional[float] = None  # 量比
    amount_yi: Optional[float] = None  # 成交额(亿)
    amplitude_pct: Optional[float] = None  # 振幅
    limit_up: Optional[float] = None
    limit_down: Optional[float] = None
    # 情绪梯队
    consec_boards: Optional[int] = None  # 连板数（个股自身；市场级三率移盘前简报市场情绪区）
    # 资金流（单位：万；source 层须保证换算到万，见 activity/fund_flow）
    main_net_inflow: Optional[float] = None  # 主力净流入(万)
    main_net_5d: Optional[float] = None      # 5日主力累计(万)
    dragon_tiger_inst_net: Optional[float] = None  # 龙虎榜机构净额(万)
    northbound: Optional[float] = None      # 北向(万)
    dragon_tiger_hot_money_relay: Optional[float] = None  # 龙虎榜游资接力频次(万，S044 R4)
    # 催化剂
    announcements: list[Announcement] = []
    concepts: list[str] = []
    sector_flow: Optional[float] = None
    # 技术位(辅助)
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    boll_upper: Optional[float] = None
    boll_lower: Optional[float] = None
    macd: Optional[float] = None
    # 补充参考信号(客观呈现)
    seal_amount: Optional[float] = None
    seal_delta: Optional[float] = None  # S085 B3：日内封单 delta（末-首，from intraday_features 表 trajectory）
    auction_open_pct: Optional[float] = None
    chip_profit_ratio: Optional[float] = None
    block_trade_premium: Optional[float] = None
    holder_num_change: Optional[float] = None
    # S057：八项标准所需字段
    float_market_cap: Optional[float] = None  # 流通市值（元）；activity source 已有，build_indicator_set 塞入
    # S081：PRD 2 战法因子（从 K线扩展算，消除 match_strategies 重复取数）
    max_high_pct: Optional[float] = None       # 当日最高涨幅 = (high/prev_close - 1)*100
    shadow_length_pct: Optional[float] = None  # 上影线长度 = (high/close - 1)*100
    ma_5_status: Optional[str] = None          # 5日均线状态 "Upward"/"Downward"/"Flat"
    prev_turnover_pct: Optional[float] = None  # 前日换手率（供 vol_ratio_1d 计算）
    # S084：选股池战法解耦 — tencent_quote 扩展 + 板块资金 + 前日成交额
    #   limit_up/limit_down 复用既有 L38-39，不新增同名
    #   取数路径分两路（B4 决议）：
    #     - kline prev_bar 复算（历史日可取）：open / change_amt / last_close / prev_amount_yi
    #     - tencent_quote 当日取（口径=当前估值非 T-1）：pe_ttm / mcap_yi / pb
    last_close: Optional[float] = None       # 昨收（前日 K线 bar.close）
    open: Optional[float] = None             # 开盘（前日 K线 bar.open；盘中实时另取）
    change_amt: Optional[float] = None       # 涨跌额（前日 close - prev_close）
    pe_ttm: Optional[float] = None           # 市盈率TTM（tencent_quote 当日，口径=当前估值非 T-1）
    mcap_yi: Optional[float] = None          # 总市值(亿)（tencent_quote 当日）
    pb: Optional[float] = None              # 市净率（tencent_quote 当日）
    sector_net_inflow: Optional[float] = None  # 板块净流入（market.get_overview 昨日，行业级）
    sector_inflow: Optional[float] = None      # 板块流入（行业级）
    sector_outflow: Optional[float] = None     # 板块流出（行业级）
    prev_amount_yi: Optional[float] = None     # 前日成交额(亿)（前日 bar.amount/1e8）
    # 数据缺失透明（AC6）：field -> 原因
    missing: dict[str, str] = {}


# ---------- 活跃度分档 ----------
class ActivityTier(str, Enum):
    """活跃度三档（客观可复现，非方向判断）。"""

    COLD = "冷"
    ACTIVE = "活跃"
    HOT = "热"


class BaseThreshold(BaseModel):
    """基数阈值（spec §5.2 签字固化）。"""

    turnover_cold: float = 8.0
    turnover_hot: float = 20.0
    vol_ratio_active: float = 2.0
    amount_yi_min: float = 10.0
    amplitude_high: float = 8.0
    northbound_abs_min: float = 0.0  # S044 R5：北向净额绝对值下限(万)；默认0=有北向数据即保留，非方向占位口径


class ThresholdConfig(BaseModel):
    """阈值配置：mode/auto/suggest/manual + base + adjustment + sentiment_phase + effective。"""

    mode: Literal["auto", "suggest", "manual"] = "suggest"
    base: BaseThreshold = Field(default_factory=BaseThreshold)
    adjustment: Optional[dict] = None  # 情绪调整项(可复现)
    sentiment_phase: Optional[str] = None  # 来自 STI/情绪天气
    effective: Optional[BaseThreshold] = None  # 解析后实际生效阈值


class ActivityAssessment(BaseModel):
    """活跃度评估：档位 + 命中规则 + 阈值依据（AC5 可复现）。"""

    tier: ActivityTier
    rules_applied: list[str] = []  # 命中规则(可复现)
    threshold_basis: Optional[ThresholdConfig] = None


# ---------- 企稳信号 ----------
class StabilizationSignals(BaseModel):
    """企稳四信号（市场级客观判定，每信号带 evidence）。"""

    fewer_limit_downs: Optional[bool] = None  # 跌停家数减少
    volume_stop_falling: Optional[bool] = None
    main_flow_turning_positive: Optional[bool] = None
    board_height_rising: Optional[bool] = None
    evidence: dict[str, str] = {}  # 每信号的依据


# ---------- 诊断卡 ----------
class DiagnosisCard(BaseModel):
    """个股诊断卡：六类指标 + 活跃度档 + 企稳信号 + 客观风险标。

    合规 AC10：不含"回撤/出货/健康/买卖"等方向结论词，方向交用户 AI。
    S057：增 eight_standards（八项标准三态判定）+ capped/cap_reason（封顶标记）。
    """

    code: str
    name: str
    indicators: IndicatorSet
    activity: ActivityAssessment
    stabilization: StabilizationSignals
    risk_flags: list[str] = []  # ST/新股/停牌/极端估值 等客观标注
    as_of: datetime
    eight_standards: Optional["EightStandardResult"] = None
    capped: bool = False  # 八项未过≥3 → 最终得分封顶 55
    cap_reason: Optional[str] = None
    # S084：选股池战法解耦 3 子对象（各默认 None，既有快照无字段降级；Q6=B）
    # 用 Optional[dict] 而非 GeneScore 模型：避免跨模块 import 耦合 + model_dump(mode='json') 序列化安全
    gene_score: Optional[dict] = None        # 涨停基因完整对象 dump（total_score/factors/zt_count_250d/...）
    pool_item: Optional[dict] = None         # 涨停池原始 dict（lbc/zbc/fbt/zdp/zje/hybk，走 em_get 限流）
    derived: Optional[dict] = None           # S070 R7 分时派生（broken_duration_min/max_drop_pct/last_lock_time），盘前未采集时 None 降级
    # S085 B2：游资席位聚合子对象（聚合 only，守 S018 R11 不放个体席位名/花名）。
    # {buy_one_ratio, buy_seat_types, sell_seat_types, score_modifier, risk_label, data_status}
    # 无龙虎榜/取数失败 → None 降级（不臆造）。不参与 capped/胜率/结算，仅选股池呈现。
    seat_detail: Optional[dict] = None


# ---------- S057 八项标准 ----------
class EightStandardItem(BaseModel):
    """八项标准单条检查结果：pass / fail / missing 三态。

    missing 不计入通过数也不计入未过数（独立第三态，守不臆造红线）。
    """

    key: str  # 1-8 编号
    label: str
    status: Literal["pass", "fail", "missing"]
    actual: Optional[str] = None  # 实际值（missing 时为 None）
    expected: str  # 期望区间/条件（人类可读）
    note: Optional[str] = None


class EightStandardResult(BaseModel):
    """八项标准检查结果汇总。"""

    items: list[EightStandardItem] = []
    fail_count: int = 0
    missing_count: int = 0


# ---------- 漏斗 ----------
class FilterRecord(BaseModel):
    """被过滤标的 + 原因（可复现）。"""

    code: str
    name: Optional[str] = None
    reason: str


class FunnelLayer(BaseModel):
    """漏斗单层：输入/输出/被过滤原因（AC1 每层可检视）。"""

    layer_id: str  # R1/R2/R3/SELF
    name: str
    as_of: datetime
    input_count: int
    output_count: int
    filtered_out: list[FilterRecord] = []
    output_codes: list[str] = []
    # S023：每层筛选条件（可读描述+情绪档位标注）、通过候选、数据状态
    conditions: list[str] = []
    passed: list[dict] = []
    data_status: Optional[str] = None  # None=正常 / "未取得"=采集失败
    data_reason: Optional[str] = None  # 失败原因


class FunnelResult(BaseModel):
    """漏斗结果：各层 + 最终候选 + 阈值配置 + 情绪档。"""

    run_id: str
    date: str  # T 日
    layers: list[FunnelLayer]
    final_candidates: list[DiagnosisCard]
    threshold_config: ThresholdConfig
    sentiment_phase: Optional[str] = None
    as_of: datetime
    # S085 B1：run 级市场聚合上下文（4 率 + lianban_stocks + date），复用 get_market_emotion_raw
    # shared cache 透传（零额外外调）。非个股 IndicatorSet 字段（S049 B 已剥离——全市场同值
    # 塞个股无信息量）。仅展示/审计，不参与 capped/胜率/结算（final_candidates 仍唯一承重出口）。
    market_context: Optional[dict] = None
