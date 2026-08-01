# Vibe-Research 打板策略模块设计文档

> 📌 **前身设计**：打板策略的正式 SDD 实现以 `../specs/S002-打板工作流重构/spec.md` 为准（P1 已实现）。
> 本文档为模块级设计背景，实现细节与验收以 S002 spec/plan/验收报告为准。

> 版本: V2.0 · 2026-07-19  
> 状态: 修订版（Oracle 审查后）  
> 作者: Orchestrator + @oracle review  
> 修订记录: V1.0 → V2.0，修复 4 个 Blocking 问题 + 6 个 Suggestion

---

## 一、背景与目标

### 1.1 为什么在 Vibe-Research 中做打板策略？

Vibe-Research 已有「每日复盘」页面中的**短线情绪面板**（涨停家数/连板梯队/封板率/炸板率），数据来自东财涨停板四池（`push2ex`），覆盖了**客观数据呈现**。

但缺少**策略分析层**——用户看到连板股清单后，无法获得：
- 该股的涨停基因得分（历史统计特征）
- 策略逻辑的条件匹配说明（教育性展示）
- AI 解读（用户自有 AI 分析）

**关键定位差异**：Vibe-Research 遵循弱合规口径（CLAUDE.md §1.1，2026-07-30）——系统可给研判/推荐/买卖时机，仅挂轻量风险提醒「历史统计特征，市场有风险」。打板策略模块的定位是**策略逻辑教育展示 + 客观数据呈现**（设计选择），非个股信号推送。

这与 `trading-agents` 有本质区别：

| 维度 | trading-agents | Vibe-Research |
|------|---------------|---------------|
| **定位** | 多 Agent 投研框架 | 个人 AI 投研看板 |
| **打板策略** | 完整策略引擎（31 策略 + 回测 + 批量扫描） | **策略逻辑教育展示**，不推送个股信号 |
| **数据层** | mootdx TCP + 东财 HTTP | 东财 HTTP（akshare 惰性依赖） |
| **前端** | Streamlit | React 19 + Vite + Tailwind |
| **AI** | 内置多 Agent 辩论 | 接入用户自己的 AI |
| **合规** | 生成建议 + 用户确认 | **轻量风险提醒（§1.1）** → 客观数据 + 策略逻辑为主（设计选择） |
| **实时性** | 盘中实时监控 | **被动查询** → 盘前预案/历史信号回放 |

### 1.2 设计目标

1. **直接复用数据层**：`astock.em_zt_topic_pool()` 获取涨停池原始数据，不通过 `market.py` 间接获取
2. **基因得分展示**：对涨停股计算五维因子得分（Wilson 区间校正），**仅展示客观数据**
3. **策略逻辑教育**：展示"如果某股满足以下条件，策略会发出XX信号"的**条件说明**，而非"这只股应该XX"的**行动建议**
4. **AI 增强**：通过现有 `/api/chat` 流式接口，让用户自己的 AI 解读策略逻辑
5. **合规优先**：所有展示标注「历史统计特征，非投资建议」

### 1.3 成功指标

| 指标 | 目标 |
|------|------|
| 策略页面加载 < 2s | ✅ |
| 回测数据可追溯（数据来源标签） | ✅ |
| 所有展示标注「非投资建议」 | ✅ |
| 与现有短线情绪面板数据一致 | ✅ |
| 基因得分计算与 Limit-Up Sniper 一致 | ✅ |
| 不出现"排板/扫板/回避"等行动建议标签 | ✅ |

---

## 二、架构设计

### 2.1 模块边界

```
Vibe-Research/
├── backend/
│   ├── market.py              ← 已有：短线情绪（连板/封板率/炸板率）
│   ├── astock.py              ← 已有：东财涨停板四池
│   ├── limitup_screener.py    ← 新增：涨停基因选股器（直接调 astock）
│   ├── limitup_strategy.py    ← 新增：策略逻辑分析引擎
│   ├── limitup_backtest.py    ← 新增：回测验证（可选，Phase 2）
│   └── app.py                 ← 修改：注册新路由
│
├── frontend/
│   ├── src/pages/
│   │   ├── LimitUpStrategy.tsx ← 新增：打板策略页面（客观数据展示）
│   │   └── DailyReview.tsx    ← 已有：短线情绪面板（复用数据）
│   ├── src/lib/
│   │   ├── api.ts             ← 修改：新增策略 API 类型定义
│   │   └── limitup-config.ts  ← 新增：用户配置管理（localStorage）
│   └── src/components/ui/
│       ├── GeneScoreCard.tsx  ← 新增：基因得分卡片组件（无行动建议）
│       └── GeneScoreChart.tsx ← 新增：基因得分可视化（雷达图）
│
└── docs/
    └── limitup-design.md      ← 本文档
```

### 2.2 数据流

```
┌─────────────────────────────────────────────────────────────┐
│                        用户操作                               │
│  1. 打开「打板策略」页面                                       │
│  2. 查看今日涨停股基因得分清单（客观数据）                      │
│  3. 点击「让 AI 解读」                                        │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     前端 (React 19)                           │
│  LimitUpStrategy.tsx                                         │
│  ├── 调用 api.limitupScreener() → 获取今日基因得分清单         │
│  ├── 调用 api.limitupAnalysis(code) → 获取个股深度分析        │
│  ├── 调用 api.limitupBacktest(code) → 获取回测数据（Phase 2） │
│  └── 调用 /api/chat → 流式 AI 解读                           │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     后端 (FastAPI)                             │
│  limitup_screener.py                                         │
│  ├── 直接调用 astock.em_zt_topic_pool() 获取涨停池原始数据     │
│  ├── 对每只涨停股计算基因得分 (Wilson 区间校正)                │
│  └── 输出基因得分清单（客观数据，无行动建议）                  │
│                                                              │
│  limitup_strategy.py                                         │
│  ├── 策略逻辑分析                                             │
│  ├── 条件匹配说明（教育性展示）                                │
│  └── 风控规则说明（知识性展示）                               │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     数据源                                    │
│  ├── astock.em_zt_topic_pool() → 涨停板四池（已有缓存）       │
│  ├── astock._akshare() → 市场活动数据（惰性依赖）             │
│  └── 后端 .env 配置（阈值可覆盖）                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、后端设计

### 3.1 涨停基因选股器 (`limitup_screener.py`)

#### 3.1.1 核心算法

参考 Limit-Up Sniper 的涨停基因选股逻辑，对近 N 个交易日（默认 250 日）计算 5 项因子：

| 因子 | 计算方式 | 权重 | 说明 |
|------|---------|------|------|
| 次日溢价率 | 涨停次日收盘 > 买入价的比例 | 25% | 核心盈利能力 |
| 红盘率 | 首板次日收盘为正的比例 | 25% | 稳定性 |
| 封板率 | 首板封住的比例 | 25% | 涨停质量 |
| 炸板后溢价 | 涨停/炸板后次日开盘平均溢价 | 15% | 容错能力 |
| 涨停频次 | 近 N 日涨停次数 | 10% | 活跃度 |

**Wilson 区间校正**：对小样本股票（涨停次数少）自动降低置信度，避免偶然性涨停被高估。

```python
def wilson_lower_bound(successes: int, trials: int, z: float = 1.96) -> float:
    """Wilson 95% 置信区间下界。"""
    if trials == 0:
        return 0.0
    p = successes / trials
    denominator = 1 + z**2 / trials
    center = (p + z**2 / (2 * trials)) / denominator
    margin = (z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2))) / denominator
    return max(0.0, center - margin)
```

#### 3.1.2 数据结构

```python
class GeneScore(BaseModel):
    """单只股票的涨停基因得分（客观数据，非行动建议）。"""
    code: str
    name: str
    total_score: float          # 0-100
    factors: dict[str, float]   # 五维因子得分
    wilson_adjusted: float      # Wilson 校正后得分
    qualify: bool               # 是否合格（>= 阈值）
    high_gene: bool             # 高基因（>= 高阈值）
    last_zt_dates: list[str]    # 最近涨停日期
    zt_count_250d: int          # 近 250 日涨停次数

class ScreenerResult(BaseModel):
    """全市场选股结果（客观数据展示）。"""
    date: str
    gene_scores: list[GeneScore]        # 所有涨停股的基因得分
    qualified: list[GeneScore]          # 基因合格的
    high_gene: list[GeneScore]          # 高基因的（前 10-15%）
    updated: str                        # 更新时间
    disclaimer: str                     # 轻量风险提醒
```

#### 3.1.3 用户配置

通过 `.env` 覆盖默认阈值（**开发者配置，非用户配置**）：

```bash
# .env
LIMITUP_GENE_QUALIFY_THRESHOLD=60    # 基因合格阈值（默认 60）
LIMITUP_GENE_HIGH_THRESHOLD=75       # 高基因阈值（默认 75）
LIMITUP_LOOKBACK_DAYS=250            # 回看天数（默认 250）
```

> **注意**：Vibe-Research 是被动查询型产品，不支持用户级阈值配置（那是 trading-agents 的功能）。阈值调整作为开发者配置，通过 `.env` 覆盖。如需用户级配置，可在 Phase 2+ 通过前端 Settings 页面实现。

### 3.2 策略逻辑分析引擎 (`limitup_strategy.py`)

> **重要定位变更**：本模块不再输出"入场信号"或"行动建议"，而是提供**策略逻辑的条件匹配说明**和**风控规则的知识性展示**。

#### 3.2.1 条件匹配展示（教育性）

展示"如果某股满足以下条件，策略逻辑上会触发XX条件"，而非"该股应该XX"：

| 条件类型 | 触发条件 | 展示方式 |
|---------|---------|---------|
| **高封单比** | 封单金额 / 成交额 > 0.1 | "该股的封单比为 X，策略逻辑上属于高封单比" |
| **竞价放量** | 竞价量 / 昨日均量 > 3.0 | "该股的竞价量比为 X，策略逻辑上属于竞价放量" |
| **基因高分** | 基因得分 >= 75 | "该股的基因得分为 X，属于高基因股票" |
| **低封板率** | 封板率 < 0.5 | "该股的封板率为 X%，策略逻辑上属于低封板率" |

#### 3.2.2 风控规则知识展示

展示策略逻辑中的风控规则，而非对该股的具体风控建议：

```python
class RiskRuleKnowledge(BaseModel):
    """风控规则知识（教育性展示）。"""
    rule_name: str           # 规则名称
    description: str         # 规则说明
    default_value: str       # 默认值
    configurable: bool       # 是否可配置
    example: str             # 示例
```

| 规则 | 默认值 | 说明 |
|------|--------|------|
| 硬性止损 | -7% | 策略逻辑上，亏损达到 7% 时止损 |
| 追踪止损 | 10 档 | 盈利越多，回撤容忍越小 |
| 时间止损 | 持仓 3 日 | 策略逻辑上，3 日未盈利则退出 |
| 5 日线止损 | 跌破 5 日线 | 策略逻辑上，跌破 5 日线强制离场 |
| 单股基准仓位 | 总资产 1/6 | 策略逻辑上的基准仓位 |
| 最大单股仓位 | 20% | 策略逻辑上的最大仓位限制 |

#### 3.2.3 数据结构

```python
class StrategyLogicMatch(BaseModel):
    """策略逻辑条件匹配结果（教育性展示）。"""
    code: str
    name: str
    matches: list[dict]     # 匹配的条件列表
    logic_description: str   # 策略逻辑说明
    disclaimer: str          # 轻量风险提醒

class LimitUpAnalysis(BaseModel):
    """个股策略分析（客观数据 + 逻辑说明）。"""
    code: str
    name: str
    date: str
    gene_score: GeneScore
    strategy_logic: StrategyLogicMatch  # 策略逻辑匹配
    risk_rules: list[RiskRuleKnowledge]  # 风控规则知识
    disclaimer: str
```

#### 3.2.4 API 端点

```python
# 全市场基因得分清单
@app.get("/api/limitup/screener")
def get_screener(date: str = None):
    """获取今日/指定日期的全市场涨停股基因得分（客观数据）。"""
    ...

# 个股策略分析
@app.get("/api/limitup/analysis/{code}")
def get_analysis(code: str, date: str = None):
    """获取个股的基因得分 + 策略逻辑匹配 + 风控规则知识。"""
    ...

# 回测数据（Phase 2）
@app.get("/api/limitup/backtest/{code}")
def get_backtest(code: str, start_date: str, end_date: str):
    """获取个股的历史回测表现。"""
    ...
```

### 3.3 与现有数据的集成

#### 3.3.1 直接调用 `astock.py` 获取涨停池数据

**不通过 `market.py` 间接获取**，直接调用 `astock.em_zt_topic_pool()`：

```python
# limitup_screener.py
import astock

def fetch_zt_pool(date: str) -> list[dict]:
    """从东财涨停板四池获取数据。"""
    zt = astock.em_zt_topic_pool("getTopicZTPool", date, "fbt:asc")
    yzt = astock.em_zt_topic_pool("getYesterdayZTPool", date, "zs:desc")
    zb = astock.em_zt_topic_pool("getTopicZBPool", date, "fbt:asc")
    return {"zt": zt, "yzt": yzt, "zb": zb}
```

#### 3.3.2 涨停板四池字段映射

基因得分计算需要的东财字段：

| 东财字段 | 含义 | 用途 |
|---------|------|------|
| `c` | 股票代码 | 标识个股 |
| `n` | 股票名称 | 展示用 |
| `lbc` | 连板数 | 连板判断 |
| `p` | 价格（除以1000） | 价格计算 |
| `zdp` | 涨停百分比 | 涨停幅度 |
| `amount` | 成交额 | 封单比计算 |
| `ltsz` | 流通市值 | 市值分层 |
| `hybk` | 概念/行业 | 板块归类 |

#### 3.3.3 复用 `astock.py` 的工具函数

```python
# 复用 astock 的数字解析
import astock

def _numf(v) -> float | None:
    """复用 astock 的数字解析。"""
    return astock._numf(v)
```

#### 3.3.4 基因得分计算的数据源

基因得分需要**历史涨停数据**（近 250 日），数据源：

1. **今日涨停池**：`astock.em_zt_topic_pool("getTopicZTPool", date)` → 获取今日涨停股
2. **历史涨停池**：回溯 N 日 → `astock.em_zt_topic_pool("getTopicZTPool", prev_date)` → 获取历史涨停记录
3. **K 线数据**（可选）：`astock.kline(code, ktype="D", start_date, end_date)` → 获取次日收盘价

> **性能注意**：对全市场涨停股（通常 30-100 只）每只回溯 250 日，需要在**日频预计算**后缓存结果，不在 API 请求时实时计算。

---

## 四、前端设计

### 4.1 页面结构 (`LimitUpStrategy.tsx`)

```
┌─────────────────────────────────────────────────────────┐
│  打板策略                                                │
│  涨停基因选股 · 策略逻辑教育 · 历史统计特征                │
│                                    [问 AI] [刷新]        │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌─────────────────┐  ┌─────────────────┐              │
│  │  基因合格        │  │  高基因股票       │              │
│  │  SCORE≥60: X 只  │  │  SCORE≥75: X 只  │              │
│  └─────────────────┘  └─────────────────┘              │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  涨停股基因得分清单（客观数据，非推荐）                │  │
│  │  ┌──────┬──────┬──────┬──────┬──────┬────────┐   │  │
│  │  │ 代码  │ 名称  │ 基因分│ 溢价率│ 红盘率│ 封板率│   │  │
│  │  ├──────┼──────┼──────┼──────┼──────┼────────┤   │  │
│  │  │600xxx│ xxx  │ 82   │ 65%  │ 72%  │ 80%    │   │  │
│  │  │000xxx│ xxx  │ 65   │ 45%  │ 58%  │ 62%    │   │  │
│  │  └──────┴──────┴──────┴──────┴──────┴────────┘   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  个股策略逻辑分析（点击行展开）                       │  │
│  │  ┌─────────────────────────────────────────────┐  │  │
│  │  │ 基因五维因子雷达图                             │  │  │
│  │  │ 条件匹配说明（教育性展示）                      │  │  │
│  │  │ 风控规则知识（知识性展示）                      │  │  │
│  │  │ AI 解读（流式）                               │  │  │
│  │  └─────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ⚠️ 风险提醒：所有数据基于历史统计特征，市场有风险。        │
└─────────────────────────────────────────────────────────┘
```

### 4.2 组件设计

#### 4.2.1 GeneScoreCard（基因得分卡片）

> **重要变更**：不再使用 `SignalCard`（含"排板/扫板/回避"等行动建议标签），改为 `GeneScoreCard`（仅展示客观数据）。

```tsx
interface GeneScoreCardProps {
  score: GeneScore;
  onClick?: (code: string) => void;
}

export function GeneScoreCard({ score, onClick }: GeneScoreCardProps) {
  // 使用中性颜色（blue/amber/gray），而非语义色彩（danger/success）
  const scoreColor = score.total_score >= 75 ? "text-primary"
    : score.total_score >= 60 ? "text-blue-400"
    : "text-gray-400";

  return (
    <GlassCard className="cursor-pointer hover:shadow-glow" onClick={() => onClick?.(score.code)}>
      <div className="flex items-center justify-between">
        <div>
          <p className="font-medium">{score.name}</p>
          <p className="text-xs text-muted-foreground">{score.code}</p>
        </div>
        <div className={`text-lg font-bold ${scoreColor}`}>
          {score.total_score}
        </div>
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <div>
          <p className="text-muted-foreground">溢价率</p>
          <p className="font-mono font-bold">{score.factors["次日溢价率"]}%</p>
        </div>
        <div>
          <p className="text-muted-foreground">红盘率</p>
          <p className="font-mono font-bold">{score.factors["红盘率"]}%</p>
        </div>
        <div>
          <p className="text-muted-foreground">封板率</p>
          <p className="font-mono font-bold">{score.factors["封板率"]}%</p>
        </div>
      </div>
    </GlassCard>
  );
}
```

#### 4.2.2 GeneScoreChart（基因得分雷达图）

使用 ECharts 绘制五维因子雷达图：

```tsx
interface GeneScoreChartProps {
  factors: Record<string, number>;
  wilsonAdjusted: number;
}

export function GeneScoreChart({ factors, wilsonAdjusted }: GeneScoreChartProps) {
  const option = {
    radar: {
      indicator: Object.keys(factors).map((k) => ({ name: k, max: 100 })),
    },
    series: [{
      type: "radar",
      data: [{
        value: Object.values(factors),
        name: "基因因子",
        areaStyle: { color: "rgba(251, 146, 60, 0.3)" },
        lineStyle: { color: "#fb923c" },
      }],
    }],
  };

  return <EChartsReact option={option} style={{ height: 200 }} />;
}
```

### 4.3 路由配置

在 `router.tsx` 中新增：

```tsx
import { LimitUpStrategy } from "@/pages/LimitUpStrategy";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      // ... 现有路由
      { path: "/limitup", element: <LimitUpStrategy /> },
    ],
  },
]);
```

在 `Layout.tsx` 的侧边栏中新增导航项：

```tsx
{
  title: "打板策略",
  path: "/limitup",
  icon: Flame,  // 复用 lucide-react 的 Flame 图标
},
```

### 4.4 配置管理

**不再使用前端 localStorage 配置**（与后端 .env 双层配置冗余且不一致）。

阈值配置统一由后端 `.env` 控制（开发者配置）。如需用户级配置，可在 Phase 2+ 通过前端 Settings 页面实现，届时将配置通过 API 请求参数传递给后端。

---

## 五、API 类型定义 (`api.ts`)

```typescript
// 打板策略相关类型（客观数据，非行动建议）

export interface GeneScore {
  code: string;
  name: string;
  total_score: number;        // 0-100
  factors: Record<string, number>;  // 五维因子
  wilson_adjusted: number;
  qualify: boolean;
  high_gene: boolean;
  last_zt_dates: string[];
  zt_count_250d: number;
}

export interface StrategyLogicMatch {
  code: string;
  name: string;
  matches: Array<{
    condition: string;    // 条件名称（如"高封单比"）
    value: string;        // 条件值（如"封单比 0.15"）
    description: string;  // 策略逻辑说明
  }>;
  logic_description: string;
  disclaimer: string;
}

export interface RiskRuleKnowledge {
  rule_name: string;
  description: string;
  default_value: string;
  configurable: boolean;
  example: string;
}

export interface LimitUpAnalysis {
  code: string;
  name: string;
  date: string;
  gene_score: GeneScore;
  strategy_logic: StrategyLogicMatch;
  risk_rules: RiskRuleKnowledge[];
  disclaimer: string;
}

export interface ScreenerResult {
  date: string;
  gene_scores: GeneScore[];
  qualified: GeneScore[];
  high_gene: GeneScore[];
  updated: string;
  disclaimer: string;
}

// API 客户端扩展
export const api = {
  // ... 现有方法
  limitupScreener: (date?: string) =>
    get<ScreenerResult>(`/limitup/screener${date ? `?date=${date}` : ""}`),
  limitupAnalysis: (code: string, date?: string) =>
    get<LimitUpAnalysis>(`/limitup/analysis/${code}${date ? `?date=${date}` : ""}`),
};
```

---

## 六、实施计划

### Phase 1: 核心骨架（第 1-2 周）

**目标**：跑通「涨停池 → 基因选股 → 基因得分清单 → 前端展示」的最小闭环

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 新建 `limitup_screener.py`（直接调 astock） | 后端 | 2 天 |
| 新建 `limitup_strategy.py`（策略逻辑分析） | 后端 | 2 天 |
| 在 `app.py` 注册新路由 | 后端 | 0.5 天 |
| 基因得分日频预计算 + 内存缓存 | 后端 | 1 天 |
| 新建 `LimitUpStrategy.tsx`（客观数据展示） | 前端 | 2 天 |
| 扩展 `api.ts` 类型定义 | 前端 | 0.5 天 |
| 新增侧边栏导航项 | 前端 | 0.5 天 |
| **联调测试** | | 1 天 |

**验收标准**：
- 页面可加载今日基因得分清单
- 基因得分计算正确（与 Limit-Up Sniper 一致）
- 基因得分卡片显示正确（无行动建议标签）
- 轻量风险提醒显示
- 数据源标注清晰

### Phase 2: 深度分析（第 3-4 周）

**目标**：个股策略逻辑分析 + AI 解读

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 个股策略逻辑分析 API | 后端 | 2 天 |
| 基因五维雷达图 | 前端 | 1.5 天 |
| AI 解读集成 | 前后端 | 2 天 |
| **联调测试** | | 1 天 |

**验收标准**：
- 点击基因得分行可展开个股策略逻辑分析
- 基因五维因子雷达图渲染正确
- AI 解读流式输出
- 条件匹配说明清晰（教育性展示）

### Phase 3: 回测验证（第 5-6 周，可选）

**目标**：历史回测 + 基因得分与次日表现的统计关系

| 任务 | 文件 | 工作量 |
|------|------|--------|
| 简化版回测（基因得分 vs 次日表现散点图） | 后端 | 2 天 |
| 回测数据 API | 后端 | 1 天 |
| 回测结果可视化 | 前端 | 2 天 |
| **联调测试** | | 1 天 |

### Phase 4: 优化与打磨（第 7-8 周，可选）

- 用户级阈值配置（前端 Settings 页面 → 后端 API 参数）
- 与 a-Plate-Sentinel STI 情绪引擎集成
- 性能优化（前端虚拟滚动、后端缓存策略）

---

## 七、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| akshare 惰性依赖失败 | 数据获取失败 | 降级返回空，页面显示"数据源暂不可用" |
| 东财接口限流 | API 响应慢 | 基因得分日频预计算 + 内存缓存，API 请求直接返回缓存 |
| 基因得分计算量大 | 页面加载慢 | 日频预计算，不在 API 请求时实时计算 |
| 策略逻辑被误解为建议 | 用户亏损 | 明确标注「非投资建议」+ AI 二次过滤 + 教育性说明 |
| 策略拥挤导致 Alpha 衰减 | 长期效果下降 | 定期更新因子权重 + Walk-Forward 验证（Phase 3） |

---

## 七、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| akshare 惰性依赖失败 | 数据获取失败 | 降级返回空，页面显示"数据源暂不可用" |
| 东财接口限流 | API 响应慢 | 复用 market.py 的 5 分钟缓存 |
| 基因得分计算量大 | 页面加载慢 | 异步计算 + 前端 loading 状态 |
| 信号误报 | 用户亏损 | 明确标注「非投资建议」+ AI 二次过滤 |
| 策略拥挤导致 Alpha 衰减 | 长期效果下降 | 定期更新因子权重 + Walk-Forward 验证 |

---

## 八、风险提醒

所有打板策略模块输出的信号和分析，必须包含以下声明：

> **风险提醒**：本页面展示的信号和评分基于历史统计特征，不代表未来行为，市场有风险。所有分析由用户自己的 AI 给出，Vibe-Research 仅提供数据呈现工具。

---

## 九、与 trading-agents 的关系

| 维度 | trading-agents | Vibe-Research |
|------|---------------|---------------|
| **基因选股算法** | ✅ 完整实现（5 因子 + Wilson） | 复用核心算法 |
| **策略引擎** | ✅ 31 策略并行打分 | 仅打板 3 策略 |
| **回测引擎** | ✅ BacktestEngine + Walk-Forward | Phase 2 可选 |
| **风控体系** | ✅ RiskRuleEngine + CircuitBreaker | 简化版（硬编码阈值 + .env 配置） |
| **批量扫描** | ✅ Celery 分布式 | 单页加载，不批量 |
| **前端** | Streamlit | React 19 独立页面 |
| **AI 解读** | 内置多 Agent | 用户自有 AI |
| **数据层** | mootdx TCP + 东财 HTTP | 仅东财 HTTP |

**核心原则**：Vibe-Research 的打板策略模块是 trading-agents 的**精简展示层**，不追求功能完整，追求**用户体验 + AI 解读**。
