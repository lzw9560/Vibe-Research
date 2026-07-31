"""S005 中长线价值选股漏斗 — 核心数据模型（Pydantic）。

合规：只出客观数据与可复现分档；护城河不主观评分；L4 文字交用户 AI。
对应 spec: specs/S005-中长线价值选股漏斗.md
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------- 去劣 7 条 ----------

class QualityMetric(BaseModel):
    """单条去劣指标"""
    index: int                                  # 1-7
    name: str                                   # 10年平均ROE / 5年累计FCF ...
    value: Optional[float] = None               # 计算值
    threshold: Optional[float] = None           # 阈值
    passed: Optional[bool] = None                # 通过/未通过
    inapplicable: bool = False                  # 不适用（银行保险第3条/数据不足）
    inapplicable_reason: Optional[str] = None
    exempt: bool = False                        # 命中豁免
    exempt_rule: Optional[str] = None            # 豁免A/B/C
    evidence: str = ""                          # 取数时点+年份区间+口径（可复现）
    missing: bool = False                       # 数据缺失


class MoatSignals(BaseModel):
    """护城河客观代理（软层，不评分、不剔除）"""
    gross_margin_persistence: Optional[bool] = None    # 多年毛利率>30%
    market_share_rank: Optional[int] = None           # 行业排名
    roe_stability: Optional[float] = None            # ROE 均值与稳定性
    identifiable_moat: list[str] = []                 # 可识别客观证据
    note: str = "护城河综合判断交用户AI，系统不输出主观评分"


class QualityAssessment(BaseModel):
    metrics: list[QualityMetric]                # 7 条
    moat: MoatSignals
    pass_count: int = 0                         # 通过条数
    inapplicable_count: int = 0                  # 不适用条数
    pass_rate_absolute: float = 0.0             # N/7
    pass_rate_adjusted: Optional[float] = None  # N/(7-不适用)
    data_years: Optional[int] = None            # 实际可用年数
    data_years_note: Optional[str] = None       # "不足10年"降级标注
    as_of: datetime = Field(default_factory=datetime.now)


# ---------- L3 精细分析骨架 ----------

class CompanyAnalysis(BaseModel):
    code: str
    name: str
    business_model: str = ""                    # 商业模式要点
    moat_evidence: str = ""                     # 护城河证据（客观）
    financials_summary: str = ""                # 财务摘要
    valuation_position: str = ""                # 估值位置（只标位置不划买卖线）
    risks: list[str] = []
    counter_arguments: list[str] = []           # 反面论据（合规：呈现正反两面）
    as_of: datetime = Field(default_factory=datetime.now)


# ---------- L4 四大师骨架 ----------

class MasterPerspective(BaseModel):
    master: str                                 # 巴菲特/芒格/段永平/李录
    framework: str                              # 护城河/逆向/对的生意+人/文明趋势
    data_skeleton: str = ""                     # 系统备的数据要点
    key_questions: list[str] = []               # 引导性问题清单
    ai_text: Optional[str] = None               # AI 填的文字（交用户 AI，依赖 S001）


class DeepAnalysisSkeleton(BaseModel):
    code: str
    name: str
    perspectives: list[MasterPerspective]       # 4 个
    as_of: datetime = Field(default_factory=datetime.now)
    ai_pending: bool = True                     # 文字待 AI 产出


# ---------- 漏斗层 ----------

class ValueFilterRecord(BaseModel):
    code: str
    name: Optional[str] = None
    layer: str                                  # L1/L2/L3/L4
    reason: str                                 # 被弃原因（可复现）


class ValueFunnelLayer(BaseModel):
    layer_id: str                               # L1/L2/L3/L4
    name: str
    as_of: datetime = Field(default_factory=datetime.now)
    input_count: int = 0
    output_count: int = 0
    filtered_out: list[ValueFilterRecord] = []
    output_codes: list[str] = []


class ValueFunnelResult(BaseModel):
    run_id: str
    direction: str                              # 用户输入的行业/主题/指数
    layers: list[ValueFunnelLayer] = []
    l2_assessments: dict[str, QualityAssessment] = {}
    l3_analyses: dict[str, CompanyAnalysis] = {}
    l4_finals: list[DeepAnalysisSkeleton] = []
    as_of: datetime = Field(default_factory=datetime.now)
