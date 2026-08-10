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
    auction_open_pct: Optional[float] = None
    chip_profit_ratio: Optional[float] = None
    block_trade_premium: Optional[float] = None
    holder_num_change: Optional[float] = None
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
    """

    code: str
    name: str
    indicators: IndicatorSet
    activity: ActivityAssessment
    stabilization: StabilizationSignals
    risk_flags: list[str] = []  # ST/新股/停牌/极端估值 等客观标注
    as_of: datetime


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
