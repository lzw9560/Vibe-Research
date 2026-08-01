# 技术方案 · S005 中长线价值选股漏斗

> 对应 spec：`spec.md`（已通过 2026-07-29）
> 性质：技术实现方案（spec 已签字，本文件进入文件/函数级设计，受 `CLAUDE.md` §0 SDD 约束）
> 作者：Claude ｜日期：2026-07-29
> 与短线 S002 并列独立，不共享粗筛口径。

---

## 0. 依据与复用清单

| spec 要求 | 复用的现有能力（不重造） |
|---|---|
| L1 全市场扫描（行业/主题/指数） | `astock.concept_blocks`/`hot_concepts`（概念板块）、`astock.industry_comparison`（行业排名）、`astock` 搜索接口 |
| L2 去劣 7 条（ROE/FCF/利息覆盖/毛利率/利润质量/净利率/股本膨胀） | `astock.finance`/`financials`（财务三表 5-10 年）、`astock.tencent_quote`（股本/市值）、经营 CF/资本开支（现金流表） |
| 护城河软层（客观代理） | `astock.industry_comparison`（市占/排名）、毛利率持续性、ROE 稳定性（主指标历史） |
| L3 精细分析骨架 | 复用 `astock.full_valuation`/`valuation_percentile`（估值位置）、研报 `astock.eastmoney_reports` |
| L4 四大师骨架 → AI | 依赖 `routers/chat.py`（**S001 修复后**），`chat.run_chat_stream` function-calling |
| 限流/熔断 | `astock.em_get`、`circuit_breaker`、`app.cache_response(ttl)` |
| 验算 | `~/tools/financial_rigor.py`（AC8 复算核对） |

**新增**：中长线价值漏斗子包 + 去劣计算 + 护城河代理 + L3/L4 骨架 + 1 路由 + 前端价值漏斗页。**不新增**数据层、通知、状态机；**本期只 A 股**，港股/美股预留。

---

## 1. 目录结构

### 1.1 后端新增/改动

```
backend/
├── value_funnel/                    # 【新增】中长线价值漏斗子包
│   ├── __init__.py
│   ├── models.py                    # 核心数据模型（Pydantic）
│   ├── funnel.py                    # L1→L2→L3→L4 编排
│   ├── quality.py                   # 去劣7条计算 + 3豁免 + 双口径通过率
│   ├── moat.py                      # 护城河客观代理信号（软层，不评分）
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── l1_scan.py               # 全市场扫描（行业/主题/指数成分）
│   │   ├── l2_financials.py         # 7条指标取数（财务三表，经 em_get，5-10年）
│   │   ├── l3_analysis.py           # 精细分析骨架（结构化要点）
│   │   └── l4_deep_skeleton.py      # 四大师骨架（要点清单，文字交AI）
│   └── tests/
│       ├── test_models.py
│       ├── test_quality.py
│       ├── test_moat.py
│       └── test_funnel.py
├── routers/
│   └── value_funnel.py              # 【新增】价值漏斗路由（挂 app.py）
├── app.py                           # 【改动】include_router(value_funnel.router)
└── config.py                        # 【改动】增价值漏斗默认配置字段
```

### 1.2 前端新增/改动

```
frontend/src/
├── pages/
│   └── ValueFunnel.tsx              # 【新增】价值漏斗主页（输入方向→四层收敛）
├── components/
│   └── value_funnel/
│       ├── FunnelLayers.tsx         # 四层检视（输入/输出/被弃+原因）
│       ├── QualityCard.tsx          # 去劣7条 + 双口径通过率 + 豁免 + 护城河代理
│       ├── AnalysisSkeleton.tsx     # L3精细分析骨架
│       └── DeepSkeleton.tsx         # L4四大师骨架 + "交AI"按钮（依赖S001）
├── lib/
│   └── value_funnel.ts              # 【新增】价值漏斗 API 客户端
└── router.tsx                       # 【改动】注册 /value-funnel 路由
```

---

## 2. 核心数据模型（Pydantic，`value_funnel/models.py`）

```python
from datetime import datetime
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, Field

# ---------- 去劣7条 ----------
class QualityMetric(BaseModel):
    """单条去劣指标"""
    index: int                       # 1-7
    name: str                        # 10年平均ROE / 5年累计FCF ...
    value: Optional[float] = None    # 计算值
    threshold: Optional[float] = None
    passed: Optional[bool] = None    # 通过/未通过
    inapplicable: bool = False       # 不适用（银行保险第3条/数据不足）
    inapplicable_reason: Optional[str] = None
    exempt: bool = False             # 命中豁免
    exempt_rule: Optional[str] = None  # 豁免A/B/C
    evidence: str = ""               # 取数时点+年份区间+口径（可复现）
    missing: bool = False            # 数据缺失

class MoatSignals(BaseModel):
    """护城河客观代理（软层，不评分、不剔除）"""
    gross_margin_persistence: Optional[bool] = None   # 多年毛利率>30%
    market_share_rank: Optional[int] = None           # 行业排名
    roe_stability: Optional[float] = None            # ROE均值与稳定性
    identifiable_moat: list[str] = []                 # 可识别客观证据
    note: str = "护城河综合判断交用户AI，系统不输出主观评分"

class QualityAssessment(BaseModel):
    metrics: list[QualityMetric]     # 7条
    moat: MoatSignals
    pass_count: int                  # 通过条数
    inapplicable_count: int          # 不适用条数
    pass_rate_absolute: float        # N/7
    pass_rate_adjusted: Optional[float] = None  # N/(7-不适用)
    data_years: Optional[int] = None            # 实际可用年数
    data_years_note: Optional[str] = None       # "不足10年"降级标注
    as_of: datetime

# ---------- L3精细分析骨架 ----------
class CompanyAnalysis(BaseModel):
    code: str
    name: str
    business_model: str = ""         # 商业模式要点
    moat_evidence: str = ""          # 护城河证据（客观）
    financials_summary: str = ""    # 财务摘要
    valuation_position: str = ""     # 估值位置（只标位置不划买卖线）
    risks: list[str] = []
    counter_arguments: list[str] = [] # 反面论据（合规：呈现正反两面）
    as_of: datetime

# ---------- L4四大师骨架 ----------
class MasterPerspective(BaseModel):
    master: str                     # 巴菲特/芒格/段永平/李录
    framework: str                   # 护城河/逆向/对的生意+人/文明趋势
    data_skeleton: str               # 系统备的数据要点
    key_questions: list[str] = []    # 引导性问题清单
    ai_text: Optional[str] = None    # AI填的文字（交用户AI，依赖S001）

class DeepAnalysisSkeleton(BaseModel):
    code: str
    name: str
    perspectives: list[MasterPerspective]  # 4个
    as_of: datetime
    ai_pending: bool = True          # 文字待AI产出

# ---------- 漏斗层 ----------
class ValueFilterRecord(BaseModel):
    code: str
    name: Optional[str]
    layer: str                       # L1/L2/L3/L4
    reason: str                      # 被弃原因（可复现）

class ValueFunnelLayer(BaseModel):
    layer_id: str                    # L1/L2/L3/L4
    name: str
    as_of: datetime
    input_count: int
    output_count: int
    filtered_out: list[ValueFilterRecord] = []
    output_codes: list[str] = []

class ValueFunnelResult(BaseModel):
    run_id: str
    direction: str                   # 用户输入的行业/主题/指数
    layers: list[ValueFunnelLayer]
    l2_assessments: dict[str, QualityAssessment] = {}   # code -> 去劣
    l3_analyses: dict[str, CompanyAnalysis] = {}
    l4_finals: list[DeepAnalysisSkeleton] = []           # 3家
    as_of: datetime
```

---

## 3. 接口定义

### 3.1 HTTP 路由（`routers/value_funnel.py`，挂 `/api/value-funnel/*`）

| 方法 | 路径 | 入参 | 出参 | 映射 AC |
|---|---|---|---|---|
| POST | `/api/value-funnel/scan` | `direction`（行业/主题/指数） | L1 候选 list[str] | AC1 |
| POST | `/api/value-funnel/run` | `direction`、`stage`(L1/L2/L3/L4/all) | `ValueFunnelResult` | AC2 |
| GET | `/api/value-funnel/result` | `run_id` | `ValueFunnelResult` | AC2 |
| GET | `/api/value-funnel/layers` | `run_id` | `list[ValueFunnelLayer]` | AC2（每层可检视） |
| GET | `/api/value-funnel/{code}/quality` | path `code` | `QualityAssessment` | AC3/AC6/AC7 |
| POST | `/api/value-funnel/{code}/deep-ai` | path `code` | 调 `chat.run_chat_stream` 填 L4 文字（依赖 S001） | AC5 |
| GET | `/api/value-funnel/{code}/analysis` | `code` | `CompanyAnalysis`（L3 骨架） | AC4 |

- 路由级缓存：`GET` 用 `cache_response(ttl)`（TTL ~5min，财务数据低频）。
- 合规：响应仅客观数据+骨架，无方向结论词、无参考价位。
- 鉴权：遵循 `VR_API_KEY`。

### 3.2 内部函数接口（`value_funnel/`）

```python
# quality.py
def compute_quality(code: str) -> QualityAssessment:
    """去劣7条 + 3豁免 + 双口径通过率 + 数据年限降级。
    财务三表经 astock.em_get 取数；<5年标不适用，5-10年降级标"不足10年"。
    银行/保险第3条标不适用。"""

def _metric_1_roe(code, years) -> QualityMetric: ...      # 10年平均ROE
def _metric_2_fcf(code, years) -> QualityMetric: ...      # 5年累计FCF
def _metric_3_interest(code) -> QualityMetric: ...         # 利息覆盖
def _metric_4_gross_margin(code) -> QualityMetric: ...
def _metric_5_cash_quality(code) -> QualityMetric: ...    # 经营CF/净利润5年均值
def _metric_6_net_margin(code) -> QualityMetric: ...
def _metric_7_share_dilution(code) -> QualityMetric: ...  # 5年股本膨胀
def _check_exemptions(metrics, code) -> None: ...         # 豁免A/B/C标注（提示性）

# moat.py
def moat_signals(code: str) -> MoatSignals:
    """护城河客观代理（毛利率持续性/行业排名/ROE稳定性），不评分。"""

# sources/l1_scan.py
def scan_universe(direction: str) -> list[str]:
    """按行业/主题/指数成分扫描主要上市公司（30-60家），复用概念板块/行业排名/搜索。"""

# sources/l3_analysis.py
def build_analysis_skeleton(code: str) -> CompanyAnalysis:
    """结构化要点 + 反面论据占位（客观证据系统填，结论交AI）。"""

# sources/l4_deep_skeleton.py
def build_deep_skeleton(code: str) -> DeepAnalysisSkeleton:
    """四大师框架+数据要点+引导问题清单；文字 ai_text 留空待AI。"""

# funnel.py
def run_value_funnel(direction: str, stage: str) -> ValueFunnelResult:
    """L1→L2→L3→L4 编排；每层输出为下轮输入；空层提示。
    L4 文字默认待AI（ai_pending=True），用户点"交AI"触发 deep-ai 端点。"""
```

- 各 `sources/*.py` 财务端点**必须经 `astock.em_get`**，复用熔断器。
- ST/*ST/退市在 L1 即剔除；未上市候选标"未上市"直接进 L3 人工（去劣不适用）。

---

## 4. 实施阶段

每阶段结束跑 `pytest -m "not live"` + 对应 AC 自查；去劣计算跑 `financial_rigor.py` 复算（AC8）。

| 阶段 | 内容 | 产出 | 映射 AC |
|---|---|---|---|
| **A. 模型与去劣计算** | `models.py` 全量；`quality.py` 7条计算+豁免+双口径+年限降级；单测 | 去劣可单测 | AC3/AC6/AC8 |
| **B. L1 全市场扫描** | `sources/l1_scan.py`（行业/主题/指数，复用概念板块/行业排名） | scan 可调 | AC1 |
| **C. L2 去劣+护城河** | `quality.compute_quality` + `moat.moat_signals`；财务三表经 em_get，5-10年；银行保险第3条不适用；ST/新股处理 | QualityAssessment 可生成 | AC3/AC6/AC7 |
| **D. L3 精细分析骨架** | `sources/l3_analysis.py`（结构化要点+反面论据占位） | CompanyAnalysis 可生成 | AC4 |
| **E. L4 四大师骨架+AI出口** | `sources/l4_deep_skeleton.py` + `deep-ai` 端点（调 chat，依赖S001） | 骨架可生成；AI 文字依赖 S001 | AC5 |
| **F. API 路由** | `routers/value_funnel.py` 7端点 + `app.py` 注册 + 缓存 | HTTP 可调 | AC1-AC10 |
| **G. 前端** | `ValueFunnel.tsx` + 4组件 + `lib/value_funnel.ts` + 路由 | 页面可用 | US1-US9 |
| **H. 验收** | 逐条 AC + `financial_rigor.py` 复算去劣指标 + 合规自查 + pytest 全过 | 验收报告 | 全 AC |

依赖：E 依赖 A-D + S001；F 依赖 A-E；G 依赖 F；H 依赖 F-G。A-D 可部分并行（B/C/D 依赖 A）。

---

## 5. 合规自查与技术约束

- **合规边界（CLAUDE.md §1.1，2026-07-30）**：所有模型/接口/前端实现不出现买卖方向、参考价位、收益预测、主观评分（实现时口径）；`MoatSignals` 明确"综合判断交AI，系统不输出主观评分"；`CompanyAnalysis` 估值位置只标位置不划买卖线（设计选择）；研判/推荐类表述如出现，仅挂轻量风险提醒「历史统计特征，市场有风险」。
- **去劣客观**：7条每条 `passed/inapplicable/exempt` + `evidence`（取数时点+年份+口径），可 `financial_rigor.py` 复算；豁免为"提示性标注"，最终认定交 AI/用户。
- **双口径通过率**：`pass_rate_absolute`(N/7) + `pass_rate_adjusted`(N/(7−不适用)) 同时输出。
- **数据年限**：≥5 年可算（降级标 `data_years_note="不足10年"`）；<5 年标不适用；银行/保险第3条标不适用。
- **正反两面**：L3 `counter_arguments` 必填反面论据占位（与 ai-berkshire 原则一致）。
- **L4 AI 依赖**：`deep-ai` 端点调 `chat.run_chat_stream`，依赖 S001 修复；未修前 `ai_pending=True`、按钮禁用+提示。
- **限流**：财务三表取数经 `astock.em_get` + 熔断 + 路由缓存（5min）；全市场扫描走批次。
- **跨市场**：本期只 A 股；港股/美股端点预留接口但不实现（标"未取得"）。

---

## 6. 风险与回滚

- **财务取数封 IP**：经 em_get 限流 + 熔断 + 缓存；超限时对应条标"未取得"不补全。
- **L4 AI 不可用**：S001 未修前 L4 仅出骨架，不阻塞漏斗前三层。
- **护城河主观化风险**：moat 层严格只出客观代理信号，综合判断交 AI（设计选择），避免主观评分污染客观代理层。
- **回滚**：本期为新增子包 + 1 路由 + 前端页，不改动 S002/数据层/状态机；回滚=移除 `value_funnel/`、`routers/value_funnel.py`、前端页与路由注册，不影响其余功能。
