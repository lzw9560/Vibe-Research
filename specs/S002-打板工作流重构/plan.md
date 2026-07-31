# 技术方案 · S002 P1 候选池诊断统一

> 对应 spec：`spec.md`（已通过）
> 性质：技术实现方案（spec 已签字，本文件进入文件/函数级设计，受 `CLAUDE.md` §0 SDD 约束）
> 作者：Claude ｜日期：2026-07-28

---

## 0. 依据与复用清单

| spec 要求 | 复用的现有能力（不重造） |
|---|---|
| R1 涨停基因+连板梯队 | `limitup_screener/`（基因得分）、`astock.em_zt_topic_pool`（涨停四池，聚合不输出个股名）、`market._emotion`（连板梯队/封板率/炸板率/晋级率） |
| R2 活跃度+资金流 | `astock.tencent_quote`（换手/量比/成交额/振幅）、`astock.stock_fund_flow_120d`、`astock.dragon_tiger_board` |
| R3 竞价+公告+板块 | `auction_screener.py`（集合竞价）、`astock.announcements`、`astock.concept_blocks`/`hot_concepts` |
| 自适应阈值 | `limitup_sti/`（STI 短线情绪指数）、`routers/sentiment_weather.py`/`routers/sti.py`（情绪温度） |
| 限流/熔断 | `astock.em_get`（东财统一限流）、`circuit_breaker.get_breaker("eastmoney")`、`app.cache_response(ttl)` |
| 自选/手动 | `routers/watchlist.py`、`lib/watchlist.ts` |
| 推送（P2 用，本期预留） | `notification/` |
| 验算工具 | `~/tools/financial_rigor.py`（AC5 复算核对） |

**新增**：候选池漏斗引擎 + 诊断卡聚合 + 自适应阈值解析 + 1 个路由 + 前端候选池/诊断卡页。**不新增**数据层、通知系统、状态机持久化（本期不动）。

> 实现要点（2026-07-29 live 复核补注，见 `验收报告.md` 修订记录）：
> - `sources/activity.py`：`astock.tencent_quote` 返回 `amount_wan`（万），须 `/10000` 换算到 `IndicatorSet.amount_yi`（亿）；勿用 `or` 兜底以免吞 0.0（HIGH-1）。
> - `sources/fund_flow.py`：`astock.stock_fund_flow_120d` 的 `main_net` 单位是**元**，须 `/10000` 换算到万；`dragon_tiger_board.institution.net_amt` 已是万，不二次换算（HIGH-3）。
> - `sources/gene.py`：`limitup_screener.get_screener_result` 是 `async def`，sync 上下文须用 `_await()`（`asyncio.run` 或独立线程新 loop）跑，否则返回 coroutine → `gene_scores=None` → R1 静默空（HIGH-4）。
> - `cli_runtime`：订阅 CLI 子进程必须 `encoding="utf-8"`，否则 Windows cp936 解码 UTF-8 stdout 报错被吞 → 流式零输出（HIGH-5）。
> - source↔astock 键名/单位契约由 `candidate_funnel/tests/test_sources_contract.py`（14 用例）离线锁定，`test_sources_live.py`（7 用例）联网复核。

---

## 1. 目录结构

### 1.1 后端新增/改动

```
backend/
├── candidate_funnel/                 # 【新增】候选池漏斗 + 诊断卡 子包
│   ├── __init__.py
│   ├── models.py                     # 核心数据模型（Pydantic）
│   ├── funnel.py                    # 漏斗编排：R1→R2→R3 + 自选并行
│   ├── diagnosis.py                  # 诊断卡聚合（六类指标→DiagnosisCard）
│   ├── thresholds.py                 # 自适应阈值解析（基数+情绪调整）
│   ├── sources/                      # 各来源采集器（均复用 astock.em_get 限流）
│   │   ├── __init__.py
│   │   ├── gene.py                   # R1: 涨停基因得分
│   │   ├── board_ladder.py           # R1: 连板梯队
│   │   ├── activity.py               # R2: 全市场活跃度(换手/量比/成交额)
│   │   ├── fund_flow.py              # R2: 主力净流/龙虎榜机构/北向
│   │   ├── auction.py                # R3: 集合竞价异动
│   │   ├── catalyst.py               # R3: 公告催化/板块联动
│   │   └── watchlist_in.py           # 自选/手动并行通道
│   └── tests/
│       ├── test_models.py
│       ├── test_funnel.py
│       ├── test_diagnosis.py
│       └── test_thresholds.py
├── routers/
│   └── candidates.py                 # 【新增】候选池路由（挂到 app.py）
├── app.py                            # 【改动】include_router(candidates.router)
└── config.py                         # 【改动】AssistantDefaultConfig 增候选池默认配置字段
```

### 1.2 前端新增/改动

```
frontend/src/
├── pages/
│   └── Candidates.tsx                # 【新增】候选池漏斗主页（各层检视+最终候选）
├── components/
│   └── candidate/                    # 【新增】
│       ├── FunnelLayers.tsx          # 漏斗各层卡片（输入/输出/过滤原因）
│       ├── DiagnosisCard.tsx         # 个股诊断卡（六类指标+活跃度档+企稳信号）
│       └── ThresholdPanel.tsx        # 阈值配置面板（auto/suggest/manual）
├── lib/
│   └── candidates.ts                 # 【新增】候选池 API 客户端（复用 lib/api.ts）
└── router.tsx                        # 【改动】注册 /candidates 路由
```

---

## 2. 核心数据模型（Pydantic，`candidate_funnel/models.py`）

```python
from datetime import datetime
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, Field

# ---------- 指标层 ----------
class Announcement(BaseModel):
    title: str
    date: str
    type: Optional[str] = None

class IndicatorSet(BaseModel):
    """单只股票六类短线指标快照（取不到的字段为 None 并记入 missing）"""
    code: str
    name: str
    # 量价
    price: Optional[float] = None
    change_pct: Optional[float] = None
    turnover_pct: Optional[float] = None        # 换手
    vol_ratio: Optional[float] = None           # 量比
    amount_yi: Optional[float] = None           # 成交额(亿)
    amplitude_pct: Optional[float] = None       # 振幅
    limit_up: Optional[float] = None
    limit_down: Optional[float] = None
    # 情绪梯队
    consec_boards: Optional[int] = None         # 连板数
    seal_rate: Optional[float] = None          # 封板率
    bomb_rate: Optional[float] = None          # 炸板率
    advance_rate: Optional[float] = None       # 晋级率
    # 资金流
    main_net_inflow: Optional[float] = None     # 主力净流入(万)
    main_net_5d: Optional[float] = None
    dragon_tiger_inst_net: Optional[float] = None
    northbound: Optional[float] = None
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
    # 数据缺失透明
    missing: dict[str, str] = {}                # field -> 原因

# ---------- 活跃度分档 ----------
class ActivityTier(str, Enum):
    COLD = "冷"
    ACTIVE = "活跃"
    HOT = "热"

class BaseThreshold(BaseModel):
    """基数阈值（spec §5.2 签字固化）"""
    turnover_cold: float = 8.0
    turnover_hot: float = 20.0
    vol_ratio_active: float = 2.0
    amount_yi_min: float = 10.0
    amplitude_high: float = 8.0

class ThresholdConfig(BaseModel):
    mode: Literal["auto", "suggest", "manual"] = "suggest"
    base: BaseThreshold = Field(default_factory=BaseThreshold)
    adjustment: Optional[dict] = None            # 情绪调整项(可复现)
    sentiment_phase: Optional[str] = None        # 来自 STI/情绪天气
    effective: Optional[BaseThreshold] = None   # 解析后实际生效阈值

class ActivityAssessment(BaseModel):
    tier: ActivityTier
    rules_applied: list[str] = []                # 命中规则(可复现)
    threshold_basis: Optional[ThresholdConfig] = None

# ---------- 企稳信号 ----------
class StabilizationSignals(BaseModel):
    fewer_limit_downs: Optional[bool] = None     # 跌停家数减少(市场级)
    volume_stop_falling: Optional[bool] = None
    main_flow_turning_positive: Optional[bool] = None
    board_height_rising: Optional[bool] = None
    evidence: dict[str, str] = {}                 # 每信号的依据

# ---------- 诊断卡 ----------
class DiagnosisCard(BaseModel):
    code: str
    name: str
    indicators: IndicatorSet
    activity: ActivityAssessment
    stabilization: StabilizationSignals
    risk_flags: list[str] = []                   # ST/新股/停牌/极端估值 等客观标注
    as_of: datetime
    # 合规：不含"回撤/出货/健康"等方向结论词

# ---------- 漏斗 ----------
class FilterRecord(BaseModel):
    code: str
    name: Optional[str]
    reason: str                                  # 被过滤原因(可复现)

class FunnelLayer(BaseModel):
    layer_id: str                                # R1/R2/R3/SELF
    name: str
    as_of: datetime
    input_count: int
    output_count: int
    filtered_out: list[FilterRecord] = []
    output_codes: list[str] = []

class FunnelResult(BaseModel):
    run_id: str
    date: str                                     # T 日
    layers: list[FunnelLayer]
    final_candidates: list[DiagnosisCard]
    threshold_config: ThresholdConfig
    sentiment_phase: Optional[str] = None
    as_of: datetime
```

---

## 3. 接口定义

### 3.1 HTTP 路由（`routers/candidates.py`，挂 `/api/workflow/candidates/*`）

| 方法 | 路径 | 入参 | 出参 | 映射 AC |
|---|---|---|---|---|
| POST | `/api/workflow/candidates/funnel` | `stage`(R1/R2/R3/all)、`date`(T日，可空=今日) | `FunnelResult` | AC1/AC7/AC9 |
| GET | `/api/workflow/candidates` | `date`(可空) | `list[DiagnosisCard]`（最终候选） | AC1 |
| GET | `/api/workflow/candidates/{code}/diagnosis` | path `code` | `DiagnosisCard` | AC3/AC4/AC6 |
| GET | `/api/workflow/funnel/layers` | `run_id` | `list[FunnelLayer]`（各层检视） | AC1（每层可检视） |
| GET | `/api/workflow/funnel/config` | — | `ThresholdConfig` + 来源开关 | AC2 |
| PUT | `/api/workflow/funnel/config` | `ThresholdConfig` + `sources: dict[str,bool]` | 更新后配置 | AC2 |

- 路由级缓存：`GET` 类用 `app.cache_response(ttl)`（TTL ~60s，避免多用户重复打东财）。
- 合规：所有响应仅客观数据，无方向/买卖/参考价位。
- 鉴权：遵循 `VR_API_KEY`（本地留空=开放）。

### 3.2 内部函数接口（`candidate_funnel/`）

```python
# thresholds.py
def resolve_thresholds(cfg: ThresholdConfig, sti_phase: str | None) -> BaseThreshold:
    """基数 + 情绪调整 → 生效阈值。
    mode=auto/suggest 按 sti_phase 调整档位边界；manual 直接用 base。
    调整项写入 cfg.adjustment 以便可复现。"""

# diagnosis.py
def build_diagnosis_card(code: str, cfg: ThresholdConfig) -> DiagnosisCard:
    """聚合六类指标(复用 astock 端点) → IndicatorSet → 活跃度分档 → 企稳信号 → DiagnosisCard。
    任一取数失败记入 indicators.missing，不补全。"""

def assess_activity(ind: IndicatorSet, eff: BaseThreshold) -> ActivityAssessment:
    """规则可复现的分档（换手/量比/成交额/振幅），不引入方向判断。"""

def detect_stabilization(ind: IndicatorSet, market_ctx: dict) -> StabilizationSignals:
    """企稳四信号命中判定，evidence 记依据。"""

# funnel.py
def run_funnel(stage: str, date: str, cfg: ThresholdConfig) -> FunnelResult:
    """R1→R2→R3 漏斗编排；每轮输出为下轮输入；任一层空则下游无输入并提示。
    R1 全市场扫描走批次 50 + em_get 限流 + 路由缓存。"""

def _r1_wide_sources(universe, cfg) -> FunnelLayer: ...      # 涨停基因+连板梯队
def _r2_activity_fund_flow(input_codes, cfg) -> FunnelLayer: ...
def _r3_auction_announcement(input_codes, cfg) -> FunnelLayer: ...
def _watchlist_parallel(cfg) -> list[str]: ...               # 自选/手动并行
```

- 各 `sources/*.py` 采集器签名统一：`fetch(codes: list[str], as_of) -> dict[str, IndicatorSet片段]`，东财端点**必须经 `astock.em_get`**。
- ST/新股/停牌过滤在各采集器入口做，剔除或标注入 `risk_flags`。

---

## 4. 实施阶段

每阶段结束跑 `pytest -m "not live"` + 对应 AC 自查；涉及数据输出的跑 `financial_rigor.py` 复算（AC5）。

| 阶段 | 内容 | 产出 | 映射 AC |
|---|---|---|---|
| **A. 模型与口径** | `models.py` 全量；`thresholds.py` 基数+解析；单元测试口径一致性 | 数据模型 + 阈值解析可单测 | AC3/AC5 |
| **B. 漏斗引擎** | `funnel.py` + R1/R2/R3/自选 `sources/*`；批次 50、em_get 限流、路由缓存；空层提示 | 漏斗可端到端跑（离线 mock） | AC1/AC7/AC9 |
| **C. 诊断卡聚合** | `diagnosis.py`（build_diagnosis_card/assess_activity/detect_stabilization）；六类指标复用 astock；missing 透明 | DiagnosisCard 可生成 | AC3/AC4/AC6 |
| **D. 自适应阈值** | `thresholds.resolve_thresholds` 对接 `limitup_sti`/`sentiment_weather` 取情绪 phase；auto/suggest/manual 三模式；情绪缺失降级基数 | 自适应可切、可复现 | AC2 |
| **E. API 路由** | `routers/candidates.py` 6 端点 + `app.py` 注册 + 路由缓存 | HTTP 可调 | AC1-AC10 |
| **F. 前端** | `Candidates.tsx` + `FunnelLayers/DiagnosisCard/ThresholdPanel` + `lib/candidates.ts` + 路由注册 | 页面可用 | US1-US7 |
| **G. 验收** | 逐条 AC 核对；`financial_rigor.py` 复算候选排序/分档；合规自查（§5）；`pytest -m "not live"` 全过 | 验收报告 | 全 AC |

依赖：E 依赖 A-D；F 依赖 E；G 依赖 E-F。A-D 可部分并行（C 依赖 A，D 依赖 A）。

---

## 5. 合规自查与技术约束

- **红线**：所有模型/接口/前端**不出现**买卖方向、参考价位、收益预测、主观评分；`DiagnosisCard` 无位置结论词（方向交用户 AI，本期前端诊断卡可留"交 AI 判断"入口但 AI 走 S001 修复后的 `/api/chat`，本期可仅留按钮占位）。
- **涨停四池**：`sources/board_ladder.py` 聚合成连板梯队/封板率等无个股名指标；候选池本身的个股清单属用户选定标的的客观列出，不构成推荐。
- **限流**：R1 全市场扫描走批次 50 + `em_get` 限流 + 熔断器 + 路由缓存，优先腾讯行情层（不封 IP）。
- **数据缺失**：`IndicatorSet.missing` 必填原因，分档降级不补全（AC6）。
- **可复现**：`ActivityAssessment.rules_applied` + `ThresholdConfig.adjustment` + `as_of` 满足 `financial_rigor.py` 复算（AC5）。
- **ST/新股/停牌**：入口过滤或标注（AC8/§8）。
- **依赖 S001**：诊断卡"交 AI 判断"功能依赖 `/api/chat` 修复（S001）；前端按钮在 S001 未修前可禁用或提示。

---

## 6. 风险与回滚

- **东财单次全市场扫描封 IP 风险**：批次 50 + 缓存 + 熔断 + 腾讯层优先；超限时该批标"未取得"而非整体失败（§8）。
- **STI/情绪天气接口变动**：`thresholds.py` 对情绪 phase 取值做防御，缺失降级基数并标"情绪档未取得"。
- **回滚**：本期为新增子包 + 1 路由 + 前端页，不改动现有状态机/数据层；回滚=移除 `candidate_funnel/`、`routers/candidates.py`、前端页与路由注册即可，不影响其余功能。
