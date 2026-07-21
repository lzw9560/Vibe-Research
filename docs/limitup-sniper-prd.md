# PRD: 打板策略模块 — LimitUp Sniper

| 版本 | 日期 | 状态 | 变更说明 |
|------|------|------|---------|
| V1.0 | 2026-07-19 | Draft | 初版 PRD |
| V1.1 | 2026-07-19 | Draft | Oracle 审查修订：移除 akshare 依赖、增加用户配置层、集成现有风控模块、修正过拟合阈值、调整回测目标 |
| V1.2 | 2026-07-19 | Draft | 补充 Vibe-Research 打板策略模块实施进展、实际运行数据、封板率计算修正、缓存优化方案 |
| V1.4 | 2026-07-21 | Draft | 核心变更：a-Plate-Sentinel 新增功能作为独立模块在本项目内实现（非跨系统集成）。STI 情绪引擎、席位引擎、竞价扫描、个股深度页、通知推送全部在本项目中实现为独立模块 |
| V1.6 | 2026-07-21 | **Final** | **最终定稿**：4 维度深度评审（量化研究员/核心研发/风控合规/QA）后修订 — 权重归一化公式明确化、炸板率移除(seal/break冗余)、百分位排名 equal 补偿、动态分位数分布修正(P5/P20/50/80/95)+3日平滑、source_ok=False 返回 null 不伪造 0 分、momentum→change_from_yesterday 重命名、回填节流 0.1s→1.2s、合规增强(视觉隔离/免责声明增强/标签解释) |
| V1.5 | 2026-07-21 | Draft | STI 情绪引擎设计修正：5 位专家（架构师、系统设计师、资深工程师、资深运维、领域专家/Quant）联合审查后修订 — 9 维指标体系（新增昨日涨停表现、连板高度）、百分位归一化替代 Min-Max、动态分位数阈值替代固定阈值、权重校准（总权重 0.56→1.00）、路由命名 `/api/market/sti/*`、取消用户级权重配置、API 合并 `/latest`+`/detail` |

---

## 1. 问题陈述

trading-agents 当前已有 3 个打板专用策略（`limitup_quality` / `dragon_tiger` / `fund_flow_confirm`），但它们存在以下根本性问题：

1. **数据源不足**：仅依赖东财涨停股池和龙虎榜，缺少集合竞价数据、实时行情、涨停基因因子数据
2. **无选股逻辑**：只有"涨停后分析"，没有"涨停前选股"（即 Limit-Up Sniper 的涨停基因选股）
3. **无入场时机控制**：不知道何时挂单（集合竞价 9:25-9:26），只有收盘后静态评分
4. **无风控体系**：没有止损、追踪止损、仓位管理等机制
5. **无回测验证**：虽有通用回测引擎，但打板策略没有专属的回测框架和 Walk-Forward 验证
6. **无市场状态感知**：不知道当前是震荡市还是趋势市，无法动态调整策略参数

**与现有打板策略的关系**：新模块不是替换，而是**升级和扩展**。现有 3 个打板策略作为后置评分器保留，新模块的涨停基因选股器作为前置过滤器。整合关系：

```
涨停基因选股器（前置过滤）→ 现有3个打板策略（后置评分）→ 综合排序 → 入场决策
```

**核心痛点**：现有模块是"涨停后分析器"，不是"打板交易系统"。

---

## 2. 目标

构建一个**独立的打板策略模块**，覆盖打板交易的完整生命周期：

```
选股（涨停基因）→ 预判（集合竞价）→ 入场（排板/扫板）→ 持仓（风控）→ 退出（止盈止损）→ 验证（回测）
```

### 2.1 成功指标

| 指标 | 目标值 | 测量方式 |
|------|--------|---------|
| 选股准确率 | >50% | 涨停基因选股 → 次日涨停比例 |
| 打板胜率 | >50% | 实际/模拟打板交易胜率（考虑成交率） |
| 盈亏比 | >1.2 | 平均盈利/平均亏损（打板策略特征是小赢） |
| 最大回撤 | <30% | 模拟账户回撤 |
| 日胜率 | >70% | 龙头战法子模块（二板模型） |
| 系统可用性 | >99% | 模块正常运行时间 |
| 成交率 | >30% | 信号实际成交比例（打板核心瓶颈） |

---

## 3. 模块架构

### 3.1 目录结构

```
trading-agents/tradingagents/modules/limitup_sniper/
├── __init__.py
├── config.py                    # 模块配置（阈值/参数/开关）
├── gene_selector.py             # 1. 涨停基因选股器
├── auction_analyzer.py          # 2. 集合竞价分析器
├── entry_controller.py          # 3. 入场控制器（排板/扫板）
├── risk_manager.py              # 4. 风控管理器
├── ai_filter.py                 # 5. AI 过滤（XGBoost）
├── backtester.py                # 6. 回测引擎（专属）
├── walk_forward.py              # 7. Walk-Forward 验证
├── notifier.py                  # 8. 通知推送（飞书/企微/微信）
├── models.py                    # Pydantic 数据模型
├── data_fetcher.py              # 数据获取层（多源聚合）
├── engine.py                    # 主引擎（串联全流程）
└── daily_job.py                 # 定时任务入口
```

### 3.2 模块依赖

```
limitup_sniper/
├── tradingagents/dataflows/a_stock.py    # 东财/同花顺/新浪数据源（统一走 _em_get() 限流）
├── tradingagents/dataflows/utils.py      # safe_ticker_component
├── tradingagents/storage/models.py       # 共用 Pydantic 模型
├── tradingagents/storage/repository.py   # 共用 SQLite 存储
├── tradingagents/risk/rules.py           # 复用现有风控规则引擎
├── tradingagents/risk/position.py        # 复用现有仓位管理器
├── tradingagents/risk/circuit_breaker.py # 复用现有熔断器
├── tradingagents/notifications/           # 复用现有通知系统
├── xgboost                                 # 新增依赖：AI 过滤
├── scikit-learn                            # 新增依赖：特征工程
└── joblib/pickle                           # 模型序列化（stdlib）
```

> **注意**：项目 v0.2.5 已完全移除 akshare，所有数据通过直连 HTTP API 获取。集合竞价数据和��场宽度数据通过东财 push2/datacenter HTTP 接口获取，走 `_em_get()` 节流入口。

---

## 4. 功能模块详解

### 4.1 涨停基因选股器 (`gene_selector.py`)

**来源**: Limit-Up Sniper (guoyaohua/limit-up-sniper)

#### 4.1.1 核心逻辑

对全市场 A 股（剔除 ST/\*ST/新股）的近 250 个交易日，计算 5 项涨停基因因子：

| 因子 | 定义 | 权重 | 计算频率 |
|------|------|------|---------|
| **溢价因子** | 涨停次日收盘溢价 >5% 的比例 | 25% | 每日更新 |
| **红盘因子** | 首板次日收盘红盘率 | 25% | 每日更新 |
| **封板因子** | 首板封板率（封住不炸板的比例） | 25% | 每日更新 |
| **开盘溢价因子** | 首板涨停/炸板后次日开盘平均溢价 | 15% | 每日更新 |
| **活跃度因子** | 近 250 日涨停次数 | 10% | 每日更新 |

#### 4.1.2 Wilson 区间校正

对每项因子使用 Wilson 95% 置信区间下界排序，避免小样本偏差：

```
Wilson_lower = (p + z²/2n ± z√(p(1-p)/n + z²/4n²)) / (1 + z²/n)
其中 p=因子值, n=涨停次数, z=1.96
```

#### 4.1.3 选股流程

```
1. 每日 15:30 收盘后，拉取全市场涨停股列表
2. 对每只涨停股，回溯其近 250 日 K 线数据
3. 计算 5 项因子值
4. 基因得分加权求和 → 基因得分 (0-100)
5. 基因得分 ≥ `GENE_QUALIFY_THRESHOLD`（默认 60，可配置） → 进入"基因合格池"
6. 基因得分 ≥ `GENE_HIGH_THRESHOLD`（默认 75，可配置） → 标记为"高基因股"（优先关注）
```

#### 4.1.4 输入/输出

**输入**:
- `trade_date`: 交易日
- `limit_up_stocks`: 当日涨停股列表 `[{ticker, name, limit_up_time, seal_amount}, ...]`

**输出**:
```python
GeneResult(
    ticker: str,
    name: str,
    gene_score: float,          # 0-100
    factor_values: Dict[str, float],  # 5 项因子原始值
    wilson_lower: Dict[str, float],   # 5 项 Wilson 下界
    qualifies: bool,            # 是否基因合格
    is_high_gene: bool,         # 是否高基因股
    next_day_expected_pnl: float # 预期次日收益 (%)
)
```

---

### 4.2 集合竞价分析器 (`auction_analyzer.py`)

**来源**: 龙头战法 + 集合竞价抢筹模型

#### 4.2.1 核心逻辑

在 **9:15-9:25** 集合竞价时段，实时分析每只候选股的竞价数据，判断是否值得参与：

| 时段 | 关键指标 | 阈值 |
|------|---------|------|
| 9:15-9:20 | 虚拟匹配量 | > 昨日全天成交量 3% |
| 9:20-9:25 | 撤单率 | < 25% |
| 9:25 | 开盘涨幅 | 0% ~ 6%（高开不过多） |
| 9:25 | 竞价量比 | > 3.0 |
| 9:25 | 竞价金额 | > 500 万 |

#### 4.2.2 三种战法信号

| 战法 | 触发条件 | 信号强度 |
|------|---------|---------|
| **一进二** | 昨日首板 + 今日高开 0-6% + 竞价量>昨日全天 3% | ⭐⭐⭐⭐⭐ |
| **首板低开** | 昨日涨停但今日低开 3-4.5% + 近2月相对位置<50% | ⭐⭐⭐ |
| **弱转强** | 昨日摸涨停未封住 + 今日平开/高开 0.98-1.09 + 竞价放量 | ⭐⭐⭐⭐⭐ |

#### 4.2.3 情绪评分

> **与 a-Plate-Sentinel STI 集成**：竞价情绪分以 a-Plate-Sentinel 的情绪温度指数（STI）为基础分，在此基础上叠加竞价特有维度（竞价量比、开盘涨幅等）作为修正因子，避免两套情绪系统各自维护。

综合全市场竞价数据，计算 **竞价情绪分 (0-100)**：

```
auction_sentiment = STI_base × 0.6 + (
    高开占比 × 0.10 +
    竞价放量股数 × 0.08 +
    昨日涨停股今日溢价 × 0.08 +
    炸板率 × 0.06 +
    连板高度 × 0.04 +
    板块共振度 × 0.04
)
```

- 情绪分 ≥ 动态强势阈值 → 强势市场，可积极打板
- 动态强势阈值 ~ 震荡阈值 → 震荡市场，谨慎参与
- 情绪分 < 动态弱势阈值 → 弱势市场，暂停打板

> **阈值动态校准**：所有情绪分阈值基于历史滚动窗口（90日）分位数动态计算，不硬编码固定分值，符合 AGENTS.md 硬性约定。

#### 4.2.4 输入/输出

**输入**:
- `auction_data`: 竞价实时数据 `[{ticker, open_price, match_volume, unmatched_volume, ...}, ...]`
- `yesterday_limit_up`: 昨日涨停股列表

**输出**:
```python
AuctionSignal(
    ticker: str,
    strategy: str,             # "one_to_two" / "low_open" / "weak_to_strong"
    signal_strength: int,      # 1-5 星
    opening_change_pct: float, # 开盘涨跌幅
    auction_volume_ratio: float,  # 竞价量比
    auction_amount: float,     # 竞价金额(万)
    cancel_rate: float,        # 撤单率
    emotion_score: float,      # 情绪分
    should_participate: bool,  # 是否参与
    suggested_action: str      # "bid_limit_up" / "wait" / "avoid"
)
```

---

### 4.3 入场控制器 (`entry_controller.py`)

**来源**: Limit-Up Sniper 排板/扫板双模式

#### 4.3.1 排板模式 (Queue Position)

**触发条件**（全部满足）:
1. 最新价 == 买一价 == 涨停价
2. 卖一档位为空（无人卖出）
3. 封单金额 ≥ 情绪动态门槛（强势≥500万，震荡≥1000万，弱势≥2000万）
4. 撤单次数 ≤ 25 次
5. 板块共振达标（同板块≥3只涨停）

**操作**: 在买一档挂涨停价排队

#### 4.3.2 扫板模式 (Snipe)

**触发条件**（全部满足）:
1. 未完全封板，但卖一档 = 涨停价
2. 市场情绪分 ≥ 4 分
3. 吃涨停价卖盘 ≤ 300 万且卖盘正在缩小
4. 板块共振达标

**操作**: 主动吃掉涨停价卖盘

#### 4.3.3 入场决策树

```
                    ┌─────────────┐
                    │ 基因合格？   │──否──→ 跳过
                    └──────┬──────┘
                           是
                    ┌─────────────┐
                    │ 情绪分≥40？ │──否──→ 暂停
                    └──────┬──────┘
                           是
                    ┌─────────────┐
              ┌────│ 封板？       │────是──→ 排板模式
              │    └─────────────┘
              │
              │否
              │    ┌─────────────┐
              └────│ 卖一=涨停价？│────是──→ 扫板模式
                   └─────────────┘
                           否
                           └──→ 等待/放弃
```

#### 4.3.4 输入/输出

**输入**:
- `realtime_quote`: 实时行情 `{ticker, price, bid1_price, bid1_volume, ask1_price, ask1_volume, ...}`
- `auction_signal`: 竞价分析结果
- `emotion_score`: 情绪分

**输出**:
```python
EntryDecision(
    ticker: str,
    entry_mode: str,           # "queue" / "snipe" / "wait" / "skip"
    entry_price: float,        # 建议入场价
    position_size_pct: float,  # 仓位比例 (% of total)
    stop_loss: float,          # 止损价
    take_profit_levels: List[float],  # 分批止盈位
    urgency: str,              # "high" / "medium" / "low" / "none"
    requires_user_confirmation: bool,  # 是否需要用户确认（硬性约定）
    confirmation_timeout_sec: int,     # 确认超时时间（秒）
)
```

> **用户确认拦截点**：所有 `requires_user_confirmation=True` 的信号在推送后必须等待用户通过飞书/企微**交互式确认**（如按钮回调），确认后才会进入 `simulate_trade()` 流程。信号推送 ≠ 用户确认，二者严格分离。

---

#### 4.4 风控管理器 (`risk_manager.py`)

> **与现有风控模块集成**：本模块不重写风控逻辑，而是**组合/委托**现有 `RiskRuleEngine` + `CircuitBreaker` + `PositionManager`，在此基础上叠加打板特化逻辑。

**集成关系**：

```
risk_manager.py (打板特化层)
├── tradingagents/risk/rules.py (RiskRuleEngine)  ← 组合！复用仓位/评分/行业限制
├── tradingagents/risk/position.py (PositionManager) ← 组合！复用评分→仓位映射，叠加情绪系数×基因系数
└── tradingagents/risk/circuit_breaker.py (CircuitBreaker) ← 复用！传入更敏感的日亏损阈值(-3%)
```

**打板特化规则**（作为扩展规则注入现有规则引擎）：
- 追踪止损 10 档
- 时间止损 T+3
- 5 日线止损

#### 4.4.1 仓位管理

> 基础仓位由 `PositionManager` 评分→仓位映射提供，本模块在此基础上叠加调整系数：

| 因子 | 调整系数 | 说明 |
|------|---------|------|
| 基准仓位 | 1/6 (~16.7%) | 来自 PositionManager 默认评分 |
| 振幅 > 7% | × 0.7 | 高波动降仓 |
| 振幅 5-7% | × 0.85 | 中等波动 |
| 振幅 < 5% | × 1.0 | 正常 |
| 基因得分 ≥ 75 | × 1.2 | 高基因加分 |
| 情绪分 ≥ 强势阈值 | × 1.1 | 强势市场加分 |
| 情绪分 < 弱势阈值 | × 0.0 | 暂停 |

#### 4.4.2 止损体系

> 止损规则通过扩展注入现有 `RiskRuleEngine`。打板特化规则如下：

| 类型 | 规则 | 触发条件 |
|------|------|---------|
| **硬性止损** | -7%（默认，可配置） | 买入价 × 0.93 |
| **追踪止损** | 10 档阶梯 | 盈利越多，回撤容忍越小 |
| **时间止损** | T+3 未盈利 | 持仓 3 天未盈利 → 清仓 |
| **5日线止损** | 跌破 MA5 | 收盘价 < MA5 → 次日开盘卖出 |

> **参数说明**：硬性止损默认 -7% 而非 -5%，因为打板次日低开常见 -3~-8%，-5% 可能过早止损。该阈值支持用户配置。

**追踪止损 10 档**:

| 浮盈 | 回撤阈值 | 止损价 |
|------|---------|--------|
| 0-5% | 5% | 买入价 × 0.95 |
| 5-10% | 4% | 最高价 × 0.96 |
| 10-15% | 3.5% | 最高价 × 0.965 |
| 15-20% | 3% | 最高价 × 0.97 |
| 20-25% | 2.75% | 最高价 × 0.9725 |
| 25-30% | 2.5% | 最高价 × 0.975 |
| >30% | 2.5% | 最高价 × 0.975 |

> **参数说明**：硬性止损默认 -7% 而非 -5%，因为打板次日低开常见 -3~-8%，-5% 可能过早止损。该阈值支持用户配置（`LIMITUP_STOP_LOSS`）。

#### 4.4.3 止盈体系

| 档位 | 条件 | 操作 |
|------|------|------|
| 第一档 | 浮盈 ≥ 8% | 减仓 25% |
| 第二档 | 浮盈 ≥ 12% | 再减仓 25% |
| 第三档 | 浮盈 ≥ 18% | 再减仓 25% |
| 清仓 | 浮盈 ≥ 25% 或 14:50 仍未涨停 | 全部清仓 |

#### 4.4.4 风控检查清单

```python
class RiskCheck:
    position_limit_ok: bool      # 单股仓位 ≤ MAX_SINGLE_POSITION（可配置，默认20%）
    total_position_ok: bool      # 总仓位 ≤ MAX_TOTAL_POSITION（可配置，默认80%）
    stop_loss_triggered: bool    # 止损是否触发
    take_profit_triggered: bool  # 止盈是否触发
    time_stop_triggered: bool    # 时间止损是否触发
    max_correlation_ok: bool     # 持仓相关性 ≤ 0.7
    daily_loss_ok: bool          # 当日总亏损 ≤ 3%（比通用模块更敏感）
```

#### 4.4.5 输入/输出

**输入**:
- `position`: 当前持仓 `{ticker, entry_price, quantity, entry_date, highest_price}`
- `current_price`: 当前价格
- `market_state`: 市场状态

**输出**:
```python
RiskStatus(
    ticker: str,
    action: str,                 # "hold" / "reduce" / "sell_all" / "add"
    reason: str,                 # 触发原因
    stop_loss_price: float,      # 当前止损价
    take_profit_price: float,    # 下一止盈位
    position_adjust_pct: float,  # 建议仓位调整
    urgency: str                 # "critical" / "warning" / "normal"
)
```

---

### 4.5 AI 过滤器 (`ai_filter.py`)

**来源**: N字反弹策略 XGBoost 过滤

#### 4.5.1 特征工程

| 类别 | 特征 | 来源 |
|------|------|------|
| **价格** | 30日涨幅、5日涨幅、距涨停价幅度 | K线数据 |
| **量能** | 量比、5日均量比、换手率 | 成交量数据 |
| **技术** | MA5偏离度、RSI、布林带位置 | 技术指标 |
| **打板** | 封板天数、炸板次数、封单金额变化 | 涨停数据 |
| **板块** | 板块强度、板块内排名、板块共振数 | 板块数据 |
| **基因** | 涨停基因得分、Wilson下界 | 基因选股器 |
| **竞价** | 竞价量比、开盘涨幅、撤单率 | 竞价分析器 |
| **风控** | 当前浮盈/浮亏、持仓天数 | 持仓数据 |

共 **20+ 特征**，每日收盘后自动更新。

#### 4.5.2 模型训练

```
训练数据:
  - 正样本: 次日收盘价/买入价 - 1 > 0 的股票 (label=1)
    - 买入价模拟为集合竞价开盘价或首次触及涨停价（考虑 T+1 约束）
  - 负样本: 次日收盘价/买入价 - 1 ≤ 0 的股票
    - 从"策略可触达但未参与"的股票中抽取（非全市场随机抽样）
    - 确保训练分布与推理分布一致
  - 时间范围: 最近 2 年交易日
  - 样本平衡: SMOTE 过采样 / 类别权重

模型:
  - XGBoost Classifier
  - max_depth=5, learning_rate=0.1, n_estimators=200
  - eval_metric=logloss
  - 置信度阈值: ≥0.60 才通过（默认，可配置）
    - 0.55 接近抛硬币，建议提高或通过代价敏感学习调整

验证:
  - Walk-Forward 滚动验证 (见 4.7)
  - 每日重训练 (增量更新)
```

#### 4.5.3 过滤流程

```
候选股 → 提取特征 → XGBoost 预测 → P(上涨) ≥ 0.60?
                                      ├──是──→ 加入推荐池
                                      └──否──→ 过滤掉
```

#### 4.5.4 输入/输出

**输入**:
- `candidates`: 候选股列表
- `features_df`: 特征 DataFrame

**输出**:
```python
AIPrediction(
    ticker: str,
    predicted_probability: float,  # P(次日上涨)
    feature_importance: Dict[str, float],  # 特征重要性
    passed_filter: bool,           # 是否通过
    model_version: str,            # 模型版本
    last_trained: str              # 最后训练时间
)
```

---

### 4.6 回测引擎 (`backtester.py`)

**来源**: 自建（基于 trading-agents 现有 `backtest_engine.py` 扩展）

#### 4.6.1 回测范围

| 维度 | 范围 |
|------|------|
| 时间跨度 | 最近 3 年（至少涵盖牛/熊/震荡市） |
| 股票池 | 全市场 A 股（剔除 ST/\*ST/新股/停牌） |
| 数据频率 | 日线 + 分钟线（5分钟） |
| 初始资金 | 100 万 |
| 手续费 | 佣金 0.03% + 印花税 0.1% |
| 滑点 | 扫板 0.5% / 排板 0.2% | 打板策略滑点敏感，需区分模式 |

#### 4.6.2 回测指标

| 指标 | 计算方式 | 目标值 |
|------|---------|--------|
| 总收益率 | (期末-期初)/期初 | >50% |
| 年化收益率 | (期末/期初)^(252/交易日)-1 | >20% |
| 胜率 | 盈利交易数/总交易数 | >55% |
| 盈亏比 | 平均盈利/平均亏损 | >2:1 |
| 夏普比率 | (年化收益-无风险)/年化波动率 | >1.0 |
| 最大回撤 | 峰值到谷底最大跌幅 | <20% |
| Profit Factor | 总盈利/总亏损 | >1.5 |
| 卡尔玛比率 | 年化收益/最大回撤 | >1.0 |
| 日均持仓数 | 平均每日持仓股票数 | 3-8 只 |
| 换手率 | 月均调仓频率 | <50% |

#### 4.6.3 回测报告结构

```python
class LimitUpBacktestReport:
    strategy_version: str
    backtest_period: Tuple[str, str]
    universe_size: int
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    annual_return: float
    calmar_ratio: float
    avg_holding_days: float
    avg_pnl_per_trade: float
    
    # 分年度表现
    yearly_performance: List[YearlyReport]
    
    # 分策略表现
    strategy_breakdown: List[StrategyPerformance]
    
    # 错误分析
    false_signals: List[FalseSignal]      # 预测涨但跌了
    missed_opportunities: List[MissedOpportunity]  # 预测不涨但涨了
    
    # 敏感性分析
    sensitivity: Dict[str, float]  # 参数变化对结果的影响
```

---

### 4.7 Walk-Forward 验证 (`walk_forward.py`)

**目的**: 防止过拟合，确保策略在未见数据上有效

#### 4.7.1 验证方法

```
时间轴:  [====训练====][测试][====训练====][测试][====训练====][测试]
         ←──── 250 日 ────→← 50 日 →←──── 300 日 ────→← 50 日 →
```

| 步骤 | 操作 |
|------|------|
| 1 | 用前 250 个交易日数据训练模型/参数 |
| 2 | 在接下来 50 个交易日上回测 |
| 3 | 滑动窗口：增加 50 天数据，重新训练 |
| 4 | 重复步骤 2-3，直到覆盖整个回测期 |
| 5 | 汇总所有 OOS (Out-of-Sample) 结果 |

#### 4.7.2 过拟合检测

> **多指标体系**：除 overfit_ratio 外，还包含 OOS 胜率衰减、OOS 盈亏比衰减。Walk-Forward 结果优先级 > 单次 IS/OOS 对比。

```
overfit_ratio = IS_sharpe / OOS_sharpe

判定（综合三项指标）:
  1. overfit_ratio < 1.2  → 通过 (无明显过拟合)
  2. 1.2 ≤ overfit_ratio < 1.5  → 警告 (轻度过拟合)
  3. overfit_ratio ≥ 1.5  → 失败 (严重过拟合，策略不可用)
  
  4. OOS_win_rate 衰减 > 15%  → 警告
  5. OOS_profit_factor 衰减 > 30%  → 警告
  
  任一指标触发"失败" → 策略不可用
```

#### 4.7.3 稳定性检验

| 检验项 | 标准 |
|--------|------|
| 各段 OOS 胜率 | 标准差 < 10% |
| 各段 OOS 收益 | 标准差 < 年化收益的 30% |
| 参数敏感性 | 参数±10% 时，Sharpe 下降 < 20% |
| 日期稳定性 | 任意去掉一段 OOS，结论不变 |

---

### 4.8 通知推送 (`notifier.py`)

#### 4.8.1 推送场景

| 场景 | 时间 | 渠道 | 内容 |
|------|------|------|------|
| **盘前预案** | 09:10 | 飞书/企微 | 今日竞价关注列表 + 基因高分股 |
| **竞价信号** | 09:25-09:30 | 飞书/企微 | 排板/扫板信号 + 推荐仓位 |
| **盘中提醒** | 实时 | 飞书/企微 | 炸板提醒 / 封板确认 |
| **风控警报** | 实时 | 飞书/企微 + 微信 | 止损触发 / 仓位超限 |
| **收盘复盘** | 15:30 | 飞书/企微 | 今日交易总结 + 明日预案 |
| **周报/月报** | 周一/月初 | 飞书/企微 | 策略绩效 + 参数调整建议 |

#### 4.8.2 消息模板

```markdown
## 🔥 打板信号 - 2026-07-19 09:25

| 股票代码 | 股票名称 | 战法 | 信号强度 | 基因得分 | 建议操作 |
|---------|---------|------|---------|---------|---------|
| 600XXX | 某某股份 | 一进二 | ⭐⭐⭐⭐⭐ | 82 | 涨停价排板 15% |

**市场情绪**: 68/100 (震荡偏强)
**昨日涨停**: 45只 | **今日高开**: 28只 | **板块共振**: 科技+新能源

⚠️ 注意: 基因得分仅供参考，不构成投资建议
```

---

### 4.9 数据获取层 (`data_fetcher.py`)

#### 4.9.1 数据源矩阵

| 数据类型 | 来源 | 频率 | 延迟 | 备注 |
|---------|------|------|------|------|
| **K线数据** | mootdx (TCP 7709) | 日线/分钟 | 分钟级 | 已有 |
| **实时行情** | 腾讯财经 (HTTP) | 3秒 | 3秒 | 已有 |
| **涨停股池** | 东财 datacenter | 每日 | T+0 | 已有 |
| **龙虎榜** | 东财 datacenter | 每日 | T+1 | 已有 |
| **资金流** | 东财 push2 | 分钟 | 分钟 | 已有 |
| **板块数据** | 东财 push2 | 每日 | T+0 | 已有 |
| **集合竞价** | AkShare (`stock_zh_a_tick_em`) | 每日 | T+0 | **新增** |
| **涨停基因因子** | mootdx + AkShare | 每日 | T+1 | **新增计算** |
| **北向资金** | 东财/新浪 | 每日 | T+0 | 已有 |
| **市场宽度** | AkShare | 每日 | T+0 | **新增** |

#### 4.9.2 防封限流

遵循 trading-agents 现有约定（v0.2.11）：
- 东财接口统一走 `_em_get()` 节流入口
- 模块级串行限流：间隔 `1.0s` + 随机抖动 `0.1-0.5s`
- 复用 `requests.Session`（Keep-Alive）+ 默认 UA
- AkShare 接口独立限流：间隔 `0.5s`

---

## 5. 主引擎流程 (`engine.py`)

### 5.1 T+1 收盘分析模式

```
每日 15:10-15:30 自动触发

1. [data_fetcher] 拉取当日涨停股列表 + 全市场K线
2. [gene_selector] 计算每只涨停股的涨停基因得分
3. [ai_filter] 对基因合格股进行 XGBoost 过滤
4. [auction_analyzer] 分析次日竞价预案（基于历史竞价模式）
5. [entry_controller] 生成次日入场预案（排板/扫板信号）
6. [risk_manager] 计算仓位管理和止损止盈位
7. [backtester] 更新回测数据（如有新交易）
8. [notifier] 推送盘前预案 + 写入 SQLite
```

### 5.2 盘中实时监控模式

```
每日 09:15-15:00 循环触发（5秒轮询）

09:10 → [notifier] 推送盘前预案
09:15 → [data_fetcher] 开始监听集合竞价
09:25 → [auction_analyzer] 分析竞价数据
        → [entry_controller] 生成排板/扫板信号
        → [notifier] 推送竞价信号
09:30 → [data_fetcher] 切换到实时行情
        → [risk_manager] 监控持仓风控
        → [entry_controller] 扫板信号持续监控
14:50 → [risk_manager] 强制止盈检查
15:00 → [backtester] 记录当日交易
        → [notifier] 推送收盘复盘
```

### 5.3 引擎接口

```python
class LimitUpSniperEngine:
    """打板策略主引擎"""
    
    def daily_analysis(self, trade_date: str) -> DailyReport:
        """T+1 收盘分析：生成次日竞价预案"""
        
    def realtime_monitor(self, callback: Callable) -> None:
        """盘中实时监控：通过回调推送信号"""
        
    def simulate_trade(self, signal: EntryDecision) -> TradeResult:
        """模拟交易（不实际下单）"""
        
    def run_backtest(self, start_date: str, end_date: str) -> LimitUpBacktestReport:
        """运行回测"""
        
    def walk_forward_validate(self) -> WalkForwardResult:
        """Walk-Forward 验证"""
        
    def get_status(self) -> ModuleStatus:
        """获取模块运行状态"""
```

---

## 6. 数据模型

### 6.1 新增 Pydantic 模型 (`models.py`)

```python
# 涨停基因
class GeneFactor(BaseModel):
    ticker: str
    trade_date: str
    premium_factor: float        # 溢价因子
    red_plate_factor: float     # 红盘因子
    seal_factor: float          # 封板因子
    open_premium_factor: float  # 开盘溢价因子
    activity_factor: float      # 活跃度因子
    gene_score: float           # 综合基因得分
    wilson_lower: Dict[str, float]

# 竞价信号
class AuctionData(BaseModel):
    ticker: str
    trade_date: str
    open_price: float
    open_change_pct: float
    auction_volume: int
    auction_amount: float
    auction_volume_ratio: float
    cancel_rate: float
    match_volume_before_920: int
    match_volume_after_920: int

# 基因结果
class GeneResult(BaseModel):
    ticker: str
    name: str
    gene_score: float
    factor_values: Dict[str, float]
    wilson_lower: Dict[str, float]
    qualifies: bool
    is_high_gene: bool
    next_day_expected_pnl: float

# 入场决策
class EntryDecision(BaseModel):
    ticker: str
    entry_mode: str  # "queue" | "snipe" | "wait" | "skip"
    entry_price: float
    position_size_pct: float
    stop_loss: float
    take_profit_levels: List[float]
    urgency: str

# 风控状态
class RiskStatus(BaseModel):
    ticker: str
    action: str  # "hold" | "reduce" | "sell_all" | "add"
    reason: str
    stop_loss_price: float
    take_profit_price: float
    position_adjust_pct: float
    urgency: str

# AI预测
class AIPrediction(BaseModel):
    ticker: str
    predicted_probability: float
    feature_importance: Dict[str, float]
    passed_filter: bool
    model_version: str
    last_trained: str

# 回测报告
class LimitUpBacktestReport(BaseModel):
    strategy_version: str
    backtest_period: Tuple[str, str]
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown: float
    annual_return: float
    calmar_ratio: float
    overfit_ratio: float

# 每日报告
class DailyReport(BaseModel):
    trade_date: str
    market_regime: str  # "bull" | "bear" | "sideways"
    emotion_score: float
    limit_up_count: int
    limit_down_count: int
    gene_qualifying: List[GeneResult]
    auction_signals: List[AuctionSignal]
    entry_decisions: List[EntryDecision]
    risk_alerts: List[RiskStatus]
    ai_predictions: List[AIPrediction]
```

---

## 7. 配置 (`config.py`)

> **硬性约定遵守**：所有金额类阈值、止损线、仓位比例等必须支持用户级别配置，通过 `.env` / YAML / 数据库加载用户偏好，不得以默认值为唯一标准。

```python
# ============================================
# 默认配置（开发/测试环境可接受默认值）
# ============================================
class LimitUpSniperDefaultConfig:
    """默认配置 — 仅作为参考值，生产环境必须通过用户配置层覆盖"""
    
    # === 基因选股 ===
    GENE_LOOKBACK_DAYS = 250
    GENE_QUALIFY_THRESHOLD = 60       # 可从 .env LIMITUP_GENE_QUALIFY_THRESHOLD 覆盖
    GENE_HIGH_THRESHOLD = 75
    GENE_FACTORS_WEIGHT = {
        "premium": 0.25,
        "red_plate": 0.25,
        "seal": 0.25,
        "open_premium": 0.15,
        "activity": 0.10,
    }
    
    # === 竞价分析 ===
    AUCTION_OPEN_RANGE = (0.0, 0.06)       # 高开 0-6%
    AUCTION_VOLUME_RATIO_MIN = 3.0
    AUCTION_AMOUNT_MIN = 5_000_000          # 500万
    AUCTION_CANCEL_RATE_MAX = 0.25          # 25%
    # 情绪分阈值：基于历史滚动窗口（90日）分位数动态计算，不硬编码
    
    # === 入场控制 ===
    QUEUE_SEAL_AMOUNT_MIN = {
        "strong": 5_000_000,
        "normal": 10_000_000,
        "weak": 20_000_000,
    }
    SNIPE_SELL_REDUCE_MAX = 3_000_000     # 300万
    BOARD_SECTOR_RESONANCE_MIN = 3         # 同板块≥3只
    
    # === 风控 ===
    BASE_POSITION_PCT = 1.0 / 6            # 单股基准 16.7%
    MAX_SINGLE_POSITION = 0.20             # 单股上限 20%
    MAX_TOTAL_POSITION = 0.80              # 总仓位上限 80%
    HARD_STOP_LOSS = -0.07                 # -7% 止损（可配置: LIMITUP_STOP_LOSS）
    TIME_STOP_DAYS = 3                      # 3天未盈利清仓
    TRACKING_STOP_LEVELS = [              # 10档追踪止损
        (0.05, 0.05), (0.10, 0.04), (0.15, 0.035),
        (0.20, 0.03), (0.25, 0.0275), (0.30, 0.025),
    ]
    TAKE_PROFIT_LEVELS = [0.08, 0.12, 0.18, 0.25]
    
    # === AI 过滤 ===
    AI_CONFIDENCE_THRESHOLD = 0.60         # 置信度阈值（可配置: LIMITUP_AI_THRESHOLD）
    AI_MODEL_VERSION = "v1.0"
    AI_RETRAIN_DAYS = 1                     # 每日重训
    AI_FEATURE_COUNT = 20                   # 特征数量
    
    # === 回测 ===
    BACKTEST_INITIAL_CAPITAL = 1_000_000
    BACKTEST_COMMISSION = 0.0003
    BACKTEST_STAMP_TAX = 0.001
    BACKTEST_SLIPPAGE_SNIPE = 0.005        # 扫板 0.5%
    BACKTEST_SLIPPAGE_QUEUE = 0.002        # 排板 0.2%
    BACKTEST_LOOKBACK_DAYS = 250
    BACKTEST_TEST_DAYS = 50
    
    # === Walk-Forward ===
    WF_TRAIN_DAYS = 250
    WF_TEST_DAYS = 50
    WF_OVERFIT_THRESHOLD = 1.2             # 学术惯例 1.2-1.3
    
    # === 通知 ===
    NOTIFICATION_CHANNELS = ["feishu", "wechat"]
    NOTIFICATION_THROTTLE = {
        "same_ticker_interval_sec": 300,   # 同股票 5 分钟不重复推送
        "max_daily_per_ticker": 3,          # 单股每日最多 3 条
    }
    NOTIFICATION_SCHEDULE = {
        "pre_auction": "09:10",
        "auction_signal": "09:25",
        "realtime_alert": "continuous",
        "daily_review": "15:30",
        "weekly_report": "Monday 18:00",
        "monthly_report": "1st 18:00",
    }


# ============================================
# 用户配置层（从 .env / YAML / 数据库加载）
# ============================================
class LimitUpSniperUserConfig:
    """用户可覆盖的配置层 — 所有金额类阈值必须支持用户配置"""
    
    # 基因选股
    gene_qualify_threshold: float = None       # 覆盖 GENE_QUALIFY_THRESHOLD
    gene_high_threshold: float = None          # 覆盖 GENE_HIGH_THRESHOLD
    
    # 竞价分析
    auction_open_range_low: float = None       # 覆盖 AUCTION_OPEN_RANGE[0]
    auction_open_range_high: float = None      # 覆盖 AUCTION_OPEN_RANGE[1]
    auction_amount_min: float = None           # 覆盖 AUCTION_AMOUNT_MIN
    emotion_strong_threshold: float = None     # 动态强势阈值
    emotion_weak_threshold: float = None       # 动态弱势阈值
    
    # 入场控制
    queue_seal_amount_min_strong: float = None
    queue_seal_amount_min_normal: float = None
    queue_seal_amount_min_weak: float = None
    snipe_sell_reduce_max: float = None
    
    # 风控（金额类阈值 — 硬性约定）
    hard_stop_loss: float = None               # 覆盖 HARD_STOP_LOSS
    time_stop_days: int = None                 # 覆盖 TIME_STOP_DAYS
    base_position_pct: float = None            # 覆盖 BASE_POSITION_PCT
    max_single_position: float = None          # 覆盖 MAX_SINGLE_POSITION
    max_total_position: float = None           # 覆盖 MAX_TOTAL_POSITION
    tracking_stop_levels: list = None          # 覆盖 TRACKING_STOP_LEVELS
    take_profit_levels: list = None            # 覆盖 TAKE_PROFIT_LEVELS
    
    # AI 过滤
    ai_confidence_threshold: float = None      # 覆盖 AI_CONFIDENCE_THRESHOLD
    
    # 回测
    backtest_slippage_snipe: float = None      # 覆盖 BACKTEST_SLIPPAGE_SNIPE
    backtest_slippage_queue: float = None      # 覆盖 BACKTEST_SLIPPAGE_QUEUE
    
    # 通知
    feishu_webhook: str = None
    wecom_webhook: str = None
    wechat_webhook: str = None
    
    # 市值分层竞价金额阈值
    auction_amount_min_small: float = None     # 市值<50亿
    auction_amount_min_mid: float = None       # 市值50-200亿
    auction_amount_min_large: float = None     # 市值>200亿
    
    def resolve(self, defaults: LimitUpSniperDefaultConfig) -> dict:
        """合并默认配置和用户配置，返回最终生效配置"""
        config = {}
        for key, default_val in vars(defaults).items():
            user_val = getattr(self, key, None)
            config[key] = user_val if user_val is not None else default_val
        return config
```

> **配置加载优先级**：用户配置（最高） > 环境变量 > 默认配置（最低）
> 
> **环境变量映射**：`LIMITUP_GENE_QUALIFY_THRESHOLD` → `gene_qualify_threshold`，`LIMITUP_STOP_LOSS` → `hard_stop_loss`，等等。

---

## 8. 与非功能需求

### 8.1 性能

| 指标 | 目标 |
|------|------|
| 收盘分析耗时 | < 5 分钟（全市场） |
| 竞价分析延迟 | < 3 秒（9:25-9:28 密集期） |
| 实时轮询间隔 | 5 秒 |
| 内存占用 | < 500MB |

### 8.2 可靠性

| 要求 | 措施 |
|------|------|
| 数据异常 | 每层数据源独立异常处理，降级到上一交易日数据 |
| 网络中断 | 重试 3 次 + 指数退避 + 本地缓存兜底 |
| 模型失效 | AI 模型连续 5 日 OOS 胜率 < 45% → 自动告警 + 回滚 |
| 系统崩溃 | 进程守护（systemd/supervisor）+ 自动重启 |

### 8.3 安全性

| 要求 | 措施 |
|------|------|
| 资金安全 | 默认"生成建议 + 用户确认"模式，**禁止自动下单** |
| 合规声明 | 所有推送消息附带免责声明 |
| 数据隐私 | 本地 SQLite 存储，不上传任何交易数据 |
| 模型安全 | XGBoost 模型文件签名验证，防止篡改 |

### 8.4 合规

| 要求 | 措施 |
|------|------|
| 免责声明 | 所有 AI 生成内容标注"历史统计特征，不代表未来行为" |
| 游资标签 | 龙虎榜席位标注"历史统计特征，不构成投资建议" |
| 合规评审 | 涉及资金操作的自动化功能需法务/合规评审 |

---

## 9. 迭代计划

### Phase 1: 核心骨架 (2周)

| 任务 | 产出 |
|------|------|
| 模块目录搭建 + config.py | 模块骨架 |
| data_fetcher.py 数据层 | 多源数据聚合 |
| gene_selector.py 涨停基因选股 | 基因得分计算 |
| models.py 数据模型 | Pydantic 模型 |
| daily_job.py 定时任务入口 | 可运行的每日分析 |

### Phase 2: 竞价 + 入场 (2周)

| 任务 | 产出 |
|------|------|
| auction_analyzer.py 竞价分析 | 三种战法信号 |
| entry_controller.py 入场控制 | 排板/扫板决策 |
| notifier.py 通知推送 | 飞书/企微推送 |
| 盘前预案 + 竞价信号推送 | 完整推送链路 |

### Phase 3: 风控 + AI (2周)

| 任务 | 产出 |
|------|------|
| risk_manager.py 风控管理器 | 止损/止盈/仓位 |
| ai_filter.py XGBoost 过滤 | 特征工程 + 模型训练 |
| 盘中实时监控模式 | 5秒轮询 + 实时推送 |

### Phase 4: 回测 + 验证 (2周)

| 任务 | 产出 |
|------|------|
| backtester.py 回测引擎 | 完整回测报告 |
| walk_forward.py Walk-Forward | 过拟合检测 |
| 策略参数优化 | 最佳参数集 |
| 回测报告 + 可视化 | 策略绩效 Dashboard |

### Phase 5: 打磨 + 上线 (1周)

| 任务 | 产出 |
|------|------|
| 端到端集成测试 | 模拟盘运行 1 周 |
| 性能优化 | 收盘分析 < 5 分钟 |
| 文档 + 部署脚本 | 一键部署 |
| 合规审查 | 免责声明 + 合规标注 |

---

## 10. 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 集合竞价数据延迟 | 错过入场时机 | 中 | 本地缓存 + 快速分析管线 |
| XGBoost 模型过拟合 | 虚高回测胜率 | 高 | Walk-Forward 强制验证 + 保守阈值 + 多指标检测 |
| 策略拥挤导致 Alpha 衰减 | 胜率逐年下降 | 中 | 季度参数重校准 + 多策略并行 |
| 滑点和冲击成本 | 回测vs实盘差距大 | 高 | 回测中区分扫板/排板滑点 + 实盘小资金验证 |
| 东财接口变更 | 数据获取失败 | 中 | 多数据源冗余 + 接口健康检查 |
| 涨停板买不进 | 信号有效但无法成交 | 高 | 模拟交易验证成交率 + 扫板备选方案 |
| 用户不确认信号 | 错过交易机会 | 低 | 超时自动取消，不强制执行 |
| 通知轰炸 | 用户疲劳/忽略 | 中 | 信号去重（同票300秒不重复）+ 每日上限3条 |

---

## 11. 成功标准与验收

### 11.1 技术验收

- [ ] 模块可独立安装：`pip install tradingagents[limitup-sniper]`
- [ ] 每日收盘分析可在 5 分钟内完成全市场扫描
- [ ] 竞价信号延迟 < 3 秒
- [ ] 回测结果可复现（固定种子 + 固定数据）
- [ ] Walk-Forward 过拟合检测通过（overfit_ratio < 1.2 且 OOS 各项衰减 < 阈值）

### 11.2 策略验收

> **注意**：以下指标区分"回测指标"和"实盘/模拟盘指标"。回测假设信号一定成交，实盘需考虑成交率。

- [ ] 涨停基因选股准确率 > 50%
- [ ] 模拟打板胜率 > 50%（考虑成交率）
- [ ] 模拟交易盈亏比 > 1.2（打板策略特征是小赢）
- [ ] 模拟交易最大回撤 < 30%
- [ ] AI 过滤器查准率 > 60%
- [ ] 信号实际成交率 > 30%
- [ ] 回测滑点敏感度分析通过（扫板 0.5%、排板 0.2%）

### 11.3 运营验收

- [ ] 飞书/企微推送正常送达
- [ ] 盘中实时监控稳定运行（7×8小时）
- [ ] 日志完整记录（信号/决策/推送）
- [ ] 异常告警及时触发
- [ ] 用户确认流程正常工作（信号推送 → 用户确认 → 执行）
- [ ] 通知去重机制生效（同票300秒不重复，每日上限3条）

---

## 12. 实施路线图

> 本节记录 Vibe-Research 项目中打板策略模块的实际实施情况，作为 PRD 的补充和验证。

### 12.1 模块定位

Vibe-Research 打板策略模块与 trading-agents 有本质区别：

| 维度 | trading-agents | Vibe-Research |
|------|---------------|---------------|
| **定位** | 多 Agent 投研框架，完整策略引擎 | 个人 AI 投研看板，策略逻辑教育展示 |
| **合规** | 生成建议 + 用户确认 | **零标的红线** — 仅展示客观数据 |
| **实时性** | 盘中实时监控 | **被动查询** — 盘前预案/历史信号回放 |
| **数据层** | mootdx TCP + 东财 HTTP | 仅东财 HTTP（`astock.em_zt_topic_pool()`） |
| **前端** | Streamlit | React 19 + Vite + Tailwind CSS |
| **AI** | 内置多 Agent 辩论 | 接入用户自己的 AI |

### 12.2 已实现功能

#### 后端

**文件**: `backend/limitup_screener.py` (346 行)

| 功能 | 状态 | 说明 |
|------|------|------|
| Wilson 区间校正 | ✅ | `wilson_lower_bound(successes, trials, z=1.96)` |
| 五维因子计算 | ✅ | 次日溢价率(25%) + 红盘率(25%) + 封板率(25%) + 炸板后溢价(15%) + 涨停频次(10%) |
| 基因得分加权合成 | ✅ | `_calc_total_score(factors)` |
| 东财涨停板四池 | ✅ | `em_zt_topic_pool("getTopicZTPool/getYesterdayZTPool/getTopicZBPool")` |
| 批量历史回溯 | ✅ | `_collect_zt_history_batch()` — 10 天一批，内存中分组 |
| TTL 内存缓存 | ✅ | 12 小时 TTL，覆盖整个交易日 |
| 并发保护 | ✅ | `_COMPUTING` 锁，重复请求自动等待 |
| 后台预计算调度 | ✅ | `LIMITUP_PRECOMPUTE=true` 开关 |

**文件**: `backend/limitup_strategy.py` (300 行)

| 功能 | 状态 | 说明 |
|------|------|------|
| 条件匹配展示 | ✅ | 高封板率/基因高分/低封板率/高频涨停/高次日溢价 |
| 风控规则知识 | ✅ | 6 条预定义规则（硬性止损/追踪止损/时间止损/5日线止损/基准仓位/最大仓位） |
| 教育性表述 | ✅ | 所有文字使用"策略逻辑上""历史统计特征"等中性表述 |

**路由**: `backend/app.py`

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/limitup/screener?date=YYYY-MM-DD` | GET | 全市场基因得分清单 |
| `/api/limitup/analysis/{code}?date=YYYY-MM-DD` | GET | 个股策略分析 |

#### 前端

**文件**: `frontend/src/pages/LimitUpStrategy.tsx` (394 行)

| 组件 | 说明 |
|------|------|
| `GeneScoreChart` | ECharts 五维因子雷达图 |
| `GeneScoreDetail` | 展开的个股策略逻辑分析（雷达图 + 条件匹配 + 风控规则） |
| `ExpandableTable` | 可展开的基因得分清单表格 |
| `RowElement` | 表格行组件（点击展开个股详情） |

**集成**:

| 文件 | 变更 |
|------|------|
| `frontend/src/lib/api.ts` | 新增 5 个 TS 接口 + 2 个 API 方法 |
| `frontend/src/router.tsx` | 新增 `/limitup` 路由 |
| `frontend/src/components/layout/Layout.tsx` | 新增侧边栏"打板策略"菜单项（Flame 图标） |

### 12.3 实际运行数据

#### 封板率计算修正

**问题**：原始 PRD 中封板率用全市场炸板池总数计算，导致 Wilson 下界极低（2-5%）。

**修正**：改用平均封板时间（fbt）归一化——
- `fbt=92500`（9:25 一字板）→ 100 分
- `fbt=145000`（14:50 封板）→ 0 分
- 线性插值：`seal_rate = max(0, min(100, (1 - (avg_fbt - 92500) / (145000 - 92500)) * 100))`

#### 回溯天数调整

- PRD 默认：250 日
- 实际 MVP：10 日（`LOOKBACK_DAYS=10`）
- 原因：250 日回溯导致 10+ 次 HTTP 调用，耗时 44 秒；10 日降至 15.8 秒

#### 多日期验证（2026-07-10 至 2026-07-18）

| 日期 | 涨停股 | 基因合格(≥60) | 高基因(≥75) | 最高分 | 备注 |
|------|--------|-------------|------------|--------|------|
| 07-10 | 92 | 0 | 0 | 51 | 印证"无差别追涨停=负期望" |
| 07-11 | 45 | 0 | 0 | 55 | — |
| 07-14 | 38 | 0 | 0 | 53 | — |
| 07-15 | 41 | 0 | 0 | 52 | — |
| 07-16 | 36 | 0 | 0 | 54 | — |
| 07-17 | 40 | 0 | 0 | 56 | — |
| 07-18 | 33 | **1** | 0 | **60.23** | 云创退(920305) |

**核心发现**：
- 云创退(920305) 连续 4 天基因得分最高（54-60 分），基因稳定
- 仅 07-18 有 1 只合格（≥60），印证筛选严格的必要性
- 07-10 有 92 只涨停但最高分仅 51，印证"无差别追涨停=负期望"

#### 性能优化效果

| 指标 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| 冷启动耗时 | 44s (250日) → 15.8s (10日) | 16.5s (10日) | — |
| 缓存命中 | N/A | **4ms** | **4000 倍加速** |
| 并发请求 | 重复计算 | 自动等待 | 零开销 |

### 12.4 与 PRD 的差异

| PRD 设计 | 实际实现 | 原因 |
|---------|---------|------|
| 250 日回溯 | 10 日（MVP） | 250 日耗时过长，后续改为日频预计算 |
| akshare 依赖 | 不依赖 akshare | 项目 v0.2.5 已完全移除 akshare，走东财 HTTP |
| 实时竞价分析 | 未实现 | Vibe-Research 是被动查询型产品，不支持实时竞价 |
| 排板/扫板信号 | 未实现（改为条件匹配） | 遵守"零标的红线"，不输出行动建议 |
| XGBoost AI 过滤 | 未实现 | Phase 3 可选，MVP 阶段基因得分已提供足够信息 |
| 回测引擎 | 未实现 | Phase 3 可选 |
| 用户级阈值配置 | `.env` 开发者配置 | MVP 阶段够用，Phase 2+ 通过前端 Settings 实现 |
| 通知推送 | 未实现 | Vibe-Research 是被动查询型，不涉及实时推送 |
| 与 a-Plate-Sentinel STI 集成 | 未实现 | 当前独立计算，Phase 4 可选 |

### 12.5 合规验证

| 要求 | 状态 | 验证方式 |
|------|------|---------|
| 零标的红线 | ✅ | 无"排板/扫板/回避"等行动建议标签 |
| 教育性展示 | ✅ | 所有文字使用"策略逻辑上""历史统计特征"等中性表述 |
| 免责声明 | ✅ | 页面底部 + API 返回均包含 |
| 数据溯源 | ✅ | 所有数据标注来源（东财涨停板四池） |
| 游资标签合规 | ✅ | 未涉及龙虎榜席位标签 |

### 12.6 服务状态

```
后端: http://127.0.0.1:8900  ✅
前端: http://127.0.0.1:5899/limitup  ✅
测试: 72 个全部通过 (15 原有 + 20 新增 + 37 其他)
TypeScript: 编译通过（0 新增错误）
Vite: 构建成功（17.67s）
```

---

---

## 12.9 a-Plate-Sentinel 核心设计抽取与独立模块实施方案

> **来源**：`a-Plate-Sentinel/docs/prd.md` (V2.1, 881 行) + `module-design.md` (V1.0, 912 行)  
> **核心决策**：a-Plate-Sentinel 中的 STI 情绪引擎、席位引擎、竞价扫描、个股深度页、通知推送等功能，**不作为跨系统集成**，而是作为**独立模块在本项目内实现**。Vibe-Research 是本项目的载体，a-Plate-Sentinel 是参考设计源。

### 12.9.1 模块映射关系

| a-Plate-Sentinel 模块 | Vibe-Research 独立模块 | 实现策略 | 优先级 |
|---|---|---|---|
| 模块一：实时情绪看板 + STI 情绪温度引擎 | `limitup_sti.py` — 情绪温度合成引擎 | 读取 market.py 输出的 5 维客观数据，新增 3 维（涨停环比增速、首板溢价、连板高度）合成 8 维 STI（移除了与封板率冗余的炸板率） | **Phase 2 最高优先级** |
| 模块二：打板选股器（竞价爆量扫描 + 多因子筛选） | `auction_screener.py` — 竞价选股模块 | 盘后批量分析历史竞价数据（非实时），生成"今日竞价 TOP N"快照供前端查询 | **Phase 2** |
| 模块二：龙虎榜席位智能引擎 | `seat_engine.py` — 席位分析模块 | 冷启动批量回溯 90-180 天龙虎榜数据，建立席位标签库；盘后 T+1 更新 | **Phase 3** |
| 模块三：个股深度分析页 | `/api/stock/{code}/deep` — 个股深度 API | 整合 K 线/资金流向/龙虎榜/AI 摘要为一个深度端点 | **Phase 2** |
| 模块四：每日复盘 | `daily_review.py` — 复盘报告生成 | 盘后自动生成情绪/板块/个股复盘报告（无 AI Agent，MVP 阶段） | **Phase 2** |
| 模块五：持仓/自选 + 动态止盈止损 | 复用现有 `watchlist` + 扩展止盈止损建议线 | 在现有自选股基础上叠加止盈止损建议计算 | **Phase 2** |
| 模块六：回测系统 | `backtest_lite.py` — 简化版回测 | 基因得分 vs 次日表现散点图，提供策略可信度验证 | **Phase 3** |
| 模块七：风险预警 | 前端风控规则知识展示（已有） | 保持现状，不新增实时推送 | — |
| 模块八：设置与数据管理 | 前端 Settings 页面 | 用户级阈值配置 | **Phase 2** |

### 12.9.2 STI 情绪温度引擎（Phase 2 最高优先级）

#### 12.9.2.1 设计原则

- **只读 market.py 输出**：STI 模块直接调用 `market._emotion()` + `market._sentiment()` 两个内部函数，自主组装 8 维指标（移除了与封板率信息冗余的炸板率）。与 `get_short_term_emotion()` 完全解耦。
- **预计算入库**：对齐 `limitup_screener.py` 模式，每日 15:30-15:35 触发后台预计算，结果写入 SQLite `sti_timeline` 表。API 只读。
- **配置策略**：权重和阈值均为模块常量，**不支持用户级调整**。权重是方法论参数，不是用户偏好。可通过环境变量覆盖（如 `VR_STI_WEIGHT_SEAL_RATE=0.25`）。
- **零标的红线**：五阶段标签仅用于颜色标识，**不生成投资建议**。STI 卡片底部固定增强版免责声明（边框+背景色+图标，与全局 Disclaimer 同等显著）。
- **独立容错**：STI 是衍生数据，计算失败不阻塞数据更新流程。参考 `limitup_screener.py` 的超时降级模式。`source_ok=False` 时返回 `score: null, phase: null`（不伪造 0 分+退潮）。
- **合规隔离**：STI 卡片与个股数据（连板股清单、基因得分）之间必须增加 section divider 视觉隔离层。
- **标签解释**：五阶段标签旁增加解释性文字（"启动（情绪从低位回升，历史统计含义）"），降低游资黑话引导性。
- **回填节流**：`time.sleep(1.2)` 对齐 PRD 4.9.2 的东财限流约定，防止 IP 封禁。

#### 12.9.2.2 九维指标体系（专家审查修正版）

> **审查结论**：原 7 维体系遗漏关键情绪指标（昨日涨停表现、连板高度、核按钮），总权重 0.56 ≠ 1.0，涨跌比权重过高。经领域专家（Quant）审查后修正为 9 维体系。后因架构师与 Quant 联合审查发现 **封板率(seal_rate) 与炸板率(break_rate) 互为补数(seal_rate + break_rate = 1.0)**，合计权重 0.40 超过 1/3，存在严重信息冗余——移除炸板率，释放权重给 prev_zt_performance。最终体系为 **8 维加权 + 1 维独立过滤**。

| # | 指标 | 符号 | 权重 | 方向 | 数据源 | 说明 |
|---|------|------|------|------|--------|------|
| 1 | 涨停家数 | `limit_up_count` | 0.15 | 正向 | `market._emotion().zt_count` | 基础活跃度指标 |
| 2 | 跌停家数 | `limit_down_count` | -0.13 | 反向 | `market._emotion().dt_count` | 亏钱效应 |
| 3 | 封板率 | `seal_rate` | **0.25** | 正向 | `market._emotion().seal_rate` | **质量优先**，核心指标 |
| ~~4~~ | ~~炸板率~~ | ~~`break_rate`~~ | ~~-0.15~~ | ~~反向~~ | ~~移除~~ | **seal_rate + break_rate = 1.0，信息冗余，移除释放权重** |
| 4 | 涨跌比 | `advance_decline_ratio` | **0.10** | 正向 | `market._sentiment().up/down` | 对超短线参考有限，权重从 0.18 降至 0.10 |
| 5 | 晋级率 | `promotion_rate` | **0.22** | 正向 | `market._emotion().promotion_rate` | **情绪周期最敏感**，权重从 0.15 提升至 0.22 |
| 6 | 昨日涨停今日表现 | `prev_zt_performance` | **0.10** | 正向 | **新增**：`zt_count / yzt_count * 100` | **情绪惯性核心**，领域专家指出为重大遗漏。MVP 代理指标：今日涨停数/昨日涨停数，>100 表示情绪延续 |
| 7 | 连板高度因子 | `max_boards` | **0.05** | 正向 | `market._emotion().max_boards` | **情绪空间感知**，领域专家指出为重大遗漏 |
| 8 | 成交额调节 | `market_factor` | **0.00** | 独立过滤 | **新增**：滚动 60 日成交额中位数 | **移出主分数**，改为独立过滤条件（不参与加权合成） |

**归一化权重合计**：0.15 + 0.13 + 0.25 + 0.10 + 0.22 + 0.10 + 0.05 = **1.00**

> **归一化公式**：
> ```
> STI_raw = Σ(normalized_i × weight_i)    # normalized_i ∈ [0, 100], weight_i 全部取正值
> STI     = STI_raw / Σ(weight_i) × 100
>         = STI_raw / 1.00 × 100
>         = STI_raw
> ```
> 反向指标（跌停）通过 `direction=-1` 参数处理：`normalized = 100 - percentile_rank`，权重取绝对值。

**prev_zt_performance 数据源说明（MVP 代理指标）**：
- 真正的"昨日涨停今日表现"应计算昨日涨停股在今日的平均涨跌幅，需要逐只追踪昨涨停股的今日收盘价
- MVP 采用代理指标：`zt_count / yzt_count * 100`（今日涨停数 / 昨日涨停数）
  - > 100：情绪延续（今日涨停多于昨日）
  - < 100：情绪减弱（今日涨停少于昨日）
- Phase 3+ 可升级为真实涨跌幅计算

**成交额调节（独立过滤条件）**：
- 使用**滚动 60 日成交额中位数**（非硬编码 1 万亿，领域专家指出 1 万亿假设已过时）
- 作为信号过滤条件而非加权维度：
  - 成交额 < 0.8 万亿 → 极度缩量，STI 结果标记 `confidence: low`
  - 0.8-1.2 万亿 → 正常
  - 1.2-1.8 万亿 → 活跃
  - > 1.8 万亿 → 亢奋
- 2024-2025 年 A 股日均成交额中枢约 1.2-1.8 万亿

**STI 动量（衍生信号，重命名为 change_from_yesterday）**：
- `change_from_yesterday = 今日 STI - 昨日 STI`
- `Δ2d = 今日 STI - 2 日前 STI`
- 动量是方向判断的参考信号，STI 本身是状态描述
- 在 Vibe-Research 被动查询型产品定位下，单日 ΔSTI 噪声较大，建议前端展示"3 日移动平均 STI"替代单日差分，更平滑、更具参考价值
- 或改为趋势标签：连续 3 日上升 → "情绪改善中"，连续 3 日下降 → "情绪恶化中"

#### 12.9.2.3 归一化方法：百分位排名

> **审查结论**：Min-Max 对极端值敏感（牛市涨停 150 家 vs 熊市涨停 5 家，Min-Max 熊市数据全部挤在 0-5 区间）；滚动分位数裁剪（5th-95th）会丢失极端信号。领域专家建议百分位排名。

```python
def percentile_rank(value: float, lookback_series: list[float]) -> float:
    """将 value 映射到 lookback_series 的百分位排名 (0-100)。
    
    使用 Excel PERCENTRANK.INC 标准：(less + 0.5 * equal) / n
    天然 0-100 分布，保留极端值信号，无需裁剪。
    最小 warm-up 期：60 个交易日。
    """
    if len(lookback_series) < 60:
        return 50.0  # 数据不足，返回中性值
    
    less = sum(1 for v in lookback_series if v < value)
    equal = sum(1 for v in lookback_series if v == value)
    # Excel PERCENTRANK.INC 标准：相等值平分中间区域
    return ((less + 0.5 * equal) / len(lookback_series)) * 100.0
```

**负相关指标处理**：使用 `direction` 参数而非负号乘法：
```python
def normalize_score(value: float, history: list[float], direction: Literal[1, -1] = 1) -> float:
    score = percentile_rank(value, history)
    return 100 - score if direction == -1 else score
```

#### 12.9.2.4 五阶段阈值：动态分位数

> **审查结论**：15/30/60/85 纯主观设定，无统计依据。高潮阈值 85 可能永远达不到，冰点阈值 15 可能全年只覆盖 5-10 天。领域专家建议动态分位数阈值。

```python
# 基于近 252 交易日（1 年）STI 分布的动态分位数阈值
# 修正：非均匀分布，更符合实战认知
STI_THRESHOLDS = {
    "高潮": "P90",    # 历史 90 分位以上 → 高潮 (~10%)
    "启动": "P70",    # P70-P90 → 启动 (~20%)
    "分歧": "P40",    # P40-P70 → 分歧 (~30%)
    "冰点": "P15",    # P15-P40 → 冰点 (~25%)
    "退潮": "<P15",   # < P15 → 退潮 (~15%)
}

# 各档位覆盖时间比例（可控，非均匀分布）：
# 高潮: ~10%, 启动: ~20%, 分歧: ~30%, 冰点: ~25%, 退潮: ~15%
# 冰点 > 退潮 因为"真正的冰点"（全年只出现几次）应比"退潮"更稀有

# 相位平滑：使用 3 日移动平均 STI 分数，避免单日极端值导致相位抖动
def _classify_phase(score: float, history_scores: list[float]) -> STIPhase:
    # 第一步：计算 3 日移动平均（含历史数据）
    smoothed = _ema_3day(score, history_scores[-2:]) if len(history_scores) >= 2 else score
    # 第二步：基于 smoothed 做分位数分类
    ...
```

> **Warm-up 期说明**：
> - 百分位排名的 warm-up 期为 60 个交易日
> - 分位数阈值的 warm-up 期为 252 个交易日
> - 在 60-252 天过渡期内，百分位排名已有效，但阶段分类使用固定阈值降级：
>   ```python
>   _FALLBACK_PHASE_THRESHOLDS = {
>       "高潮": 80,  # P90 近似
>       "启动": 60,  # P70 近似
>       "分歧": 40,  # P40 近似
>       "冰点": 20,  # P15 近似
>   }
>   ```

#### 12.9.2.5 代码骨架

```python
# backend/limitup_sti.py
from enum import Enum
from pydantic import BaseModel
from typing import Optional

class STIPhase(str, Enum):
    HIGH潮 = "高潮"
    START = "启动"
    DIVERGENCE = "分歧"
    FREEZE = "冰点"
    DECLINE = "退潮"

class STIDimension(BaseModel):
    """八维指标归一化后的分数 (0-100)"""
    limit_up_count: float      # 涨停家数
    limit_down_count: float    # 跌停家数（反向）
    seal_rate: float           # 封板率
    advance_decline_ratio: float  # 涨跌比
    promotion_rate: float      # 晋级率
    prev_zt_performance: float # 昨日涨停今日表现
    max_boards: float          # 连板高度
    market_factor: float       # 成交额调节（独立过滤，不参与加权）

class STIResult(BaseModel):
    date: str
    score: float | None        # 0-100，source_ok=False 时为 null
    phase: STIPhase | None
    dimensions: STIDimension | None
    source_ok: bool            # 数据源是否可用
    confidence: str            # "high" / "medium" / "low"（基于成交额过滤）
    change_from_yesterday: float | None  # 今日 STI - 昨日 STI（衍生信号，重命名自 momentum）
    data_updated: str | None   # 数据更新时间（YYYY-MM-DD），用于 freshness 标注
    disclaimer: str = "情绪温度仅为历史统计维度之一，不构成任何操作建议。历史统计特征不代表未来行为。"

# 模块常量（权重 — 不可用户级调整）
STI_WEIGHTS = {
    "limit_up_count": 0.15,
    "limit_down_count": 0.13,       # 负向，计算时取绝对值归一化后反向
    "seal_rate": 0.25,
    "advance_decline_ratio": 0.10,
    "promotion_rate": 0.22,
    "prev_zt_performance": 0.10,
    "max_boards": 0.05,
}
# 权重合计: 1.00（已归一化）
# 归一化公式: STI = Σ(normalized_i × weight_i) / Σ(weight_i) × 100
# 其中 normalized_i = percentile_rank(value, history) 或 100 - percentile_rank（反向指标）

STI_ENV_OVERRIDE_PREFIX = "VR_STI_"  # 环境变量覆盖前缀

class STIEngine:
    """
    STI 情绪温度合成引擎（8 维加权 + 1 维独立过滤）。
    
    数据源：market._emotion() + market._sentiment()（直接调用内部函数，解耦）
    存储：sti_timeline SQLite 表（预计算入库）
    计算频率：日频，与基因选股器共用 15:35 调度器
    注意：market._emotion(date) 必须支持可选 date 参数
    """
    
    def __init__(self):
        self._db = None  # 复用现有 SQLite 连接
    
    def compute(self, emotion_data: dict, sentiment_data: dict) -> STIResult:
        """
        输入 market.py 输出的情绪数据，输出 STI 分数 + 阶段。
        
        防御：emotion_data 或 sentiment_data 为空时返回 source_ok=False，
        此时 score/phase/dimensions 均为 null，不伪造 0 分。
        """
        ...
    
    def _normalize_dimension(self, value: float, history: list[float], direction: int) -> float:
        """百分位排名归一化（Excel PERCENTRANK.INC 标准），direction=-1 表示反向指标"""
        ...
    
    def _classify_phase(self, score: float, history_scores: list[float]) -> STIPhase:
        """动态分位数阈值判定（使用 3 日移动平均平滑，避免相位抖动）"""
        ...
    
    def precompute_daily(self, date: str) -> STIResult:
        """每日预计算入口 — 由 app.py 15:35 调度器触发
        
        注意：market._emotion(date) 必须支持可选 date 参数，
        否则历史回填不可行（阻塞点 #1）。
        """
        ...
    
    def backfill(self, start_date: str, end_date: str | None = None) -> list[STIResult]:
        """历史回填 — 分批执行（每批 30 天），节流 time.sleep(1.2)"""
        ...
```

#### 12.9.2.6 API 设计

> **审查结论**：合并 `/latest` 和 `/detail` 为一个完整端点；路由命名改为 `/api/market/sti/*` 对齐 market 命名空间；`momentum` 重命名为 `change_from_yesterday`。

```python
@app.get("/api/market/sti/latest")
def get_sti_latest(date: str = None):
    """
    获取最新 STI 结果（含八维明细）。
    
    返回完整结构：
    {
        "date": "2026-07-21",
        "score": 72,
        "phase": "启动",
        "dimensions": { ... },
        "market_factor": 1.15,
        "market_factor_note": "活跃",
        "source_ok": true,
        "confidence": "high",
        "change_from_yesterday": +8,    # 重命名自 momentum
        "data_updated": "2026-07-21",    # 数据更新时间
        "disclaimer": "..."
    }
    
    降级（source_ok=False 时）：
    - 非交易日/数据源故障 → { score: null, phase: null, dimensions: null, 
                               source_ok: false, data_updated: null,
                               note: "数据未就绪" }
    - ⚠️ 不再伪造 0 分 + "退潮"相位（旧设计会误导用户认为市场处于极端弱势）
    - 表不存在（首次部署）→ 隐藏 STI 卡片
    """
    ...

@app.get("/api/market/sti/timeline")
def get_sti_timeline(days: int = 30):
    """
    获取 STI 时间线（用于前端趋势图）。
    查询 < 5ms，无需缓存。
    """
    ...
```

#### 12.9.2.7 前端集成

**颜色方案校准**（避免与涨跌色冲突）：

| 阶段 | 建议色 | Tailwind 类 | 理由 |
|------|--------|------------|------|
| 高潮 | 红色 | `text-danger` | 市场过热 |
| 启动 | 橙色 | `text-primary` | 项目主色，温和向上 |
| 分歧 | 黄色 | `text-yellow-400` | 中性观望 |
| 冰点 | 灰色 | `text-muted-foreground` | 冷清 |
| 退潮 | 紫色 | `text-purple-400` | 向下但不像"跌" |

**组件结构**：
```
<GlassCard glow onClick={() => setShowDetail(true)}>
  <STIScoreDisplay score={72} phase="启动" changeFromYesterday={+8} dataUpdated="2026-07-21" />
  <STIDisclaimer />  <!-- 增强版：边框 + 背景色 + 图标，与全局 Disclaimer 同等显著 -->
</GlassCard>

<Modal>
  <STIDetailView dimensions={...} marketFactor={...} weights={STI_WEIGHTS} />
  <!-- 展示权重分布饼图 + 每个维度的简要解释 -->
</Modal>
```

**集成位置与视觉隔离**（风控合规要求）：
- STI 卡片作为 `DailyReview.tsx` 的第一个数据卡片（大盘指数之后）
- **必须与个股数据（连板股清单、基因得分）之间增加 section divider 隔离层**
- 切断用户心智关联：STI 反映的是"市场整体情绪"，与"具体个股表现"无直接因果关系
- 卡片底部增加引导性提示："情绪温度反映的是市场整体统计状态，与具体个股表现无直接因果关系"

**五阶段标签解释**（降低游资黑话引导性）：
- 标签旁增加解释性文字：`启动（情绪从低位回升，历史统计含义）`
- 或增加英文术语对照：`启动 (Recovery)` / `退潮 (Decline)`
- UI 中为标签添加 tooltip，解释其纯粹是统计分位含义

**降级 UI**（四层降级策略，修正 source_ok=False 行为）：

| 场景 | 返回 | 前端表现 |
|------|------|---------|
| 非交易日/数据源故障 | `score: null, phase: null, source_ok: false` | 灰色卡片 + "数据未就绪" |
| 计算异常（旧数据可用） | 最近历史 + `stale: true` + `data_updated` | 旧数据 + "数据可能不是最新的（更新于 YYYY-MM-DD）" |
| 表不存在（首次部署） | `score: null, note: "STI 未初始化"` | 隐藏 STI 卡片 |
| HTTP 500 | ApiError catch | "情绪温度暂时不可用" |
| 数据陈旧（>2 交易日） | `score: 72, stale: true, data_updated: "2026-07-18"` | 显示分数 + "数据截至 2026-07-18（可能不是最新）" |

#### 12.9.2.8 存储设计

```sql
CREATE TABLE IF NOT EXISTS sti_timeline (
    date TEXT NOT NULL UNIQUE,           -- YYYY-MM-DD，唯一约束必须
    score REAL,                          -- 0-100，source_ok=False 时为 NULL
    phase TEXT,                          -- 高潮/启动/分歧/冰点/退潮，source_ok=False 时为 NULL
    dimension_limit_up_count REAL,       -- 涨停家数归一化分
    dimension_limit_down_count REAL,     -- 跌停家数归一化分
    dimension_seal_rate REAL,            -- 封板率归一化分
    dimension_advance_decline_ratio REAL, -- 涨跌比归一化分
    dimension_promotion_rate REAL,       -- 晋级率归一化分
    dimension_prev_zt_performance REAL,  -- 昨日涨停表现归一化分
    dimension_max_boards REAL,           -- 连板高度归一化分
    market_factor REAL,                  -- 成交额调节
    confidence TEXT,                     -- high/medium/low
    source_ok BOOLEAN DEFAULT 1,
    change_from_yesterday REAL,          -- STI 动量（重命名自 momentum）
    data_updated TEXT,                   -- 数据更新时间（YYYY-MM-DD）
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sti_date ON sti_timeline(date DESC);
```

**存储增长**：年增 ~250 行 × ~1.2KB/行 ≈ **300KB/年**，5 年 < **1.5MB**，SQLite 毫无压力。

**写入策略**：`INSERT OR REPLACE`（利用 date UNIQUE 约束），每日预计算覆盖更新。

#### 12.9.2.9 预计算与调度

```python
# app.py 中复用 15:35 调度器（与基因选股器同步）
def _precompute_sti():
    """与基因选股器同步预计算 STI 日终快照。"""
    from limitup_sti import STIEngine
    try:
        engine = STIEngine()
        for back in range(3):
            d = (datetime.now() - timedelta(days=back)).strftime("%Y-%m-%d")
            engine.precompute_daily(d)
        logger.info("STI 预计算完成")
    except Exception as e:
        logger.error(f"STI 预计算失败（不影响主流程）: {e}")
        # 不抛出异常，不阻塞后续流程（独立容错）

# market._emotion(date) 必须支持可选 date 参数，否则 precompute_daily(date) 调用会 TypeError
# 修改: def _emotion(date: str = None) -> dict:
#   - date=None: 自动定位最近交易日（现有逻辑）
#   - date="20260101": 直接使用指定日期
```

#### 12.9.2.10 历史回填

- 分批执行，每批 30 天（`--batch-size 30`）
- 涉及 HTTP 请求时加 30 秒超时保护
- 输出进度日志：`[2026-07-21 16:30:01] 已处理 150/300 天...`
- **节流**：`time.sleep(1.2)`（对齐 PRD 4.9.2 的东财限流约定，原 0.1s 过低可能触发 IP 封禁）
- **重试**：429/5xx 指数退避重试，不静默 pass
- **可中断**：支持用户随时暂停/恢复回填

#### 12.9.2.11 测试策略

参考 `test_limitup.py` 模式，STI 单测必须覆盖以下边界情况：

| 类别 | 测试用例 | 验证点 |
|------|---------|--------|
| 空数据 | 所有维度为 0 / None | 返回 null score + null phase + source_ok=False |
| 单点数据 | 历史序列只有 1 个点 | 分位数退化为 50 分 |
| 极端值 | 涨停 500 家 / 跌停 100 家 | 不归一化溢出 [0,100] |
| 负权重 | 跌停最多的一天 | 反向指标贡献最低分 |
| 相位边界 | score = 19.9, 20.0, 69.9, 70.0, 84.9, 85.0 | 相位不跳变 |
| 归一化退化 | min_val == max_val | 返回 50.0 |
| market_factor | 成交额 = 0 | 返回中性值 |
| 增量更新 | 新数据追加到历史序列 | 旧分位数不变，新值正确 |
| 数据源故障 | emotion_data = {} | source_ok=False, score=null |
| equal 补偿 | 历史中大量值等于当前值 | `(less + 0.5 * equal) / n` 结果正确 |
| 浮点精度 | 1.15 的除法 | 使用 Decimal 或硬编码 TOTAL_WEIGHT |
| 线程安全 | 并发预计算同一日期 | _db_lock 保护 INSERT OR REPLACE |
| 相位平滑 | 3 日移动平均 | 单日极端值不导致相位跳变 |

#### 12.9.2.12 监控

**最低可行方案**：数据新鲜度检查（每日 crontab 检查 `MAX(date)`）：
```bash
# monitor_sti_freshness.sh — 每日 18:00 执行
LAST_STI_DATE=$(sqlite3 vibe_research.db "SELECT date FROM sti_timeline ORDER BY date DESC LIMIT 1;")
DAYS_AGO=$(( ( $(date +%s) - $(date -d "$LAST_STI_DATE" +%s) ) / 86400 ))
if [ "$DAYS_AGO" -gt 2 ]; then
    echo "WARNING: STI 数据滞后 ${DAYS_AGO} 天"
fi
```

#### 12.9.2.13 必须解决的阻塞点

1. **`market._emotion(date)` 必须支持按日期查询** — 否则历史回填不可行。修改签名 `def _emotion(date: str = None)`，传入 date 时直接使用指定日期，不传时自动定位最近交易日。
2. **`prev_zt_performance`（昨日涨停今日表现）数据源已明确** — MVP 使用 `zt_count / yzt_count * 100` 代理指标（今日涨停/昨日涨停），Phase 3+ 升级为真实涨跌幅计算。
3. **STI 计算失败不应阻塞数据更新流程** — 独立容错，`source_ok=False` 时返回 `score: null, phase: null`（不伪造 0 分）。
4. **成交额假设已从硬编码 1 万亿改为滚动 60 日中位数** — MVP 降级为 `market._sentiment().active` 字符串标签查表（`_MARKET_ACTIVE_MAP`），Phase 3 实现完整版。
5. **回填节流已从 0.1s 改为 1.2s** — 对齐东财限流约定，防止 IP 封禁。
6. **百分位排名已加入 equal 补偿** — `(less + 0.5 * equal) / n`，避免离散指标边界不连续。
7. **相位分类已加入 3 日移动平均平滑** — 避免单日极端值导致相位抖动。

### 12.9.3 竞价选股模块（Phase 2）

**设计原则**：被动查询型产品，不做实时竞价扫描。改为盘后批量分析历史竞价数据，生成"今日竞价 TOP N"快照。

```python
# auction_screener.py — 竞价选股模块（盘后批量分析）
class AuctionScreener:
    """
    每日 15:30 后批量分析当日竞价数据，生成次日竞价预案。
    非实时扫描，而是历史竞价模式回放 + 次日预案生成。
    """
    
    def analyze(self, trade_date: str) -> List[AuctionCandidate]:
        """
        输入：当日全市场竞价快照数据
        输出：按爆量强度排序的候选股列表（TOP 50）
        """
        ...
    
    def calculate_auction_score(self, stock: AuctionData) -> float:
        """
        score = f(归一化爆量比, 未匹配买量占比, 高开幅度合理性)
        输出范围 0-100，便于跨股票排序
        """
        ...
```

**API**：
```python
@app.get("/api/limitup/auction/top?date=YYYY-MM-DD&n=50")
def get_auction_top(date: str, n: int = 50):
    """获取指定日期的竞价爆量 TOP N 候选股"""
    ...
```

### 12.9.4 席位引擎模块（Phase 3）

**实现策略**：冷启动批量回溯 90-180 天龙虎榜数据，建立席位标签库。

```python
# seat_engine.py — 席位分析模块
class SeatEngine:
    """
    龙虎榜席位智能引擎。
    冷启动：批量回溯历史龙虎榜数据，建立游资风格库和量化席位识别。
    日常：每日 T+1 更新席位标签。
    """
    
    def build_seat_profiles(self, lookback_days: int = 180):
        """冷启动：批量构建席位标签库"""
        ...
    
    def compute_consensus_signal(self, trade_date: str, stock_code: str) -> str:
        """
        计算多资金共识/分歧信号。
        返回: "多资金共识" / "分歧信号" / None
        """
        ...
```

**合规约束**：所有席位标签均基于公开历史数据的统计特征，系统需在界面显著位置标注"历史统计特征，不代表未来行为，不构成投资建议"。

### 12.9.5 个股深度页增强（Phase 2）

**新增 API 端点**：
```python
@app.get("/api/stock/{code}/deep")
def get_stock_deep(code: str, date: str = None):
    """
    个股深度分析 — 整合：
    - K 线/分时数据（东财 HTTP）
    - 资金流向明细
    - 近 30 日龙虎榜记录（如有）
    - 涨停基因得分（复用现有 gene_selector）
    - AI 投研摘要（结构化 Prompt，非自由发挥）
    """
    ...
```

**前端组件**：
```
<StockDeepPage>
  ├─ <StockHeader code name price changePct />
  ├─ <Tabs>
  │    ├─ <TabQuote>  <KLineChart /> <IntradayChart /> </TabQuote>
  │    ├─ <TabGene>   <GeneScoreCard /> <GeneScoreChart /> </TabGene>
  │    ├─ <TabFund>   <FundFlowChart /> </TabFund>
  │    └─ <TabAI>     <AIInsightCard /> </TabAI>
  └─ <QuickActionBar> 一键加自选 </QuickActionBar>
```

### 12.9.6 每日复盘模块（Phase 2）

```python
# daily_review.py — 复盘报告生成
class DailyReviewer:
    """
    每日收盘后自动生成复盘报告。
    MVP 阶段：规则引擎生成结构化摘要（无 AI Agent）。
    Phase 3+：接入 AI 复盘 Agent（结构化反思）。
    """
    
    def generate_review(self, trade_date: str) -> DailyReviewReport:
        """
        输出：
        - 市场情绪总结（STI 分数 + 阶段）
        - 板块热度排名
        - 今日涨停股统计
        - 昨日涨停股今日表现
        - 竞价 TOP N 回顾
        """
        ...
```

### 12.9.7 简化版回测模块（Phase 3）

```python
# backtest_lite.py — 简化版回测
class LiteBacktester:
    """
    基因得分 vs 次日表现散点图，提供策略可信度验证。
    不包含向量化回测、冲击成本模型等复杂功能（留给 trading-agents）。
    """
    
    def run(self, gene_results: List[GeneResult], lookback_days: int = 250):
        """
        输入：基因得分结果
        输出：
        - 基因得分 vs 次日收益率散点图数据
        - 高分组 vs 低分组收益对比
        - 基因得分的预测能力指标（IC、RankIC）
        """
        ...
```

### 12.9.8 与 a-Plate-Sentinel 的核心差异

| 维度 | a-Plate-Sentinel | Vibe-Research（独立模块实现） | 设计决策 |
|------|-----------------|---------------------------|---------|
| **定位** | 实时监控+交易辅助（主动型） | 被动查询投研看板 | 不做实时推送，盘后批量分析 |
| **合规** | 生成建议+用户确认 | 零标的红线 | 所有新增展示仍用中性表述 |
| **数据时效** | 毫秒级 WebSocket | 日频/盘后 | 日频预计算 + 缓存 |
| **STI 引擎** | 实时每分钟计算 | 盘后批量计算 | 复用 market.py 输出 |
| **竞价扫描** | 09:25:01 实时全市场 | 盘后历史竞价模式分析 | 生成次日预案快照 |
| **席位引擎** | Phase 2 | Phase 3（冷启动依赖） | 批量回溯 90-180 天 |
| **基因选股** | 未入 MVP | **已实现（领先）** | 不动基因选股器 |
| **回测** | 向量化+冲击成本 | 简化版散点图 | 仅做策略可信度验证 |
| **通知推送** | 飞书/企微实时推送 | 被动查询 | 通知推送在 trading-agents 中实现 |
| **前端** | React+Ant Design+ECharts | React+Tailwind+ECharts | 保持现有前端技术栈 |

### 12.9.9 模块实现核心原则

1. **STI 引擎只读不写**：只读取 market.py 输出，不修改现有情绪数据
2. **基因选股器不动**：5 因子 + Wilson 区间校正已实现，保持现状
3. **被动查询优先**：不做实时推送，所有功能围绕"盘后分析 + 次日预案"展开
4. **前端渐进增强**：情绪温度卡片叠加在现有面板上方，不破坏现有布局
5. **零标的红线坚守**：所有新增展示仍使用"历史统计特征""策略逻辑上"等中性表述
6. **席位标签合规**：所有席位标签显著标注免责声明，点击可查看"标注依据"
7. **解耦独立**：每个模块独立可测试，不产生循环依赖
8. **配置策略**：STI 权重和阈值为模块常量，**不支持用户级调整**（权重是方法论参数，不是用户偏好）
9. **独立容错**：STI 计算失败不阻塞数据更新流程，`source_ok=False` 时返回 null 而非伪造分数
10. **路由命名规范**：STI API 使用 `/api/market/sti/*` 命名空间，对齐 market 模块
11. **合规隔离**：STI 卡片与个股数据之间必须增加 section divider 视觉隔离层
12. **免责声明增强**：STI 卡片底部使用与全局 Disclaimer 同等显著的样式（边框 + 背景色 + 图标），非"小字"
13. **标签解释**：五阶段标签旁增加解释性文字（"启动（情绪从低位回升，历史统计含义）"），降低游资黑话引导性
14. **回填节流**：`time.sleep(1.2)` 对齐东财限流约定，防止 IP 封禁

### 12.9.10 目录结构更新

```
trading-agents/tradingagents/modules/limitup_sniper/
├── __init__.py
├── config.py                    # 模块配置（阈值/参数/开关）
├── gene_selector.py             # 1. 涨停基因选股器（已有）
├── limitup_sti.py               # 2. STI 情绪温度引擎（新增）
├── auction_screener.py          # 3. 竞价选股模块（新增，盘后批量）
├── seat_engine.py               # 4. 席位分析模块（新增，Phase 3）
├── stock_deep.py                # 5. 个股深度 API（新增）
├── daily_review.py              # 6. 复盘报告生成（新增）
├── backtest_lite.py             # 7. 简化版回测（新增，Phase 3）
├── risk_manager.py              # 8. 风控管理器（已有部分）
├── models.py                    # Pydantic 数据模型
├── data_fetcher.py              # 数据获取层（多源聚合）
├── engine.py                    # 主引擎（串联全流程）
└── daily_job.py                 # 定时任务入口
```

---

## 12.7 合规验证

| 要求 | 状态 | 验证方式 |
|------|------|---------|
| 零标的红线 | ✅ | 无"排板/扫板/回避"等行动建议标签 |
| 教育性展示 | ✅ | 所有文字使用"策略逻辑上""历史统计特征"等中性表述 |
| 免责声明 | ✅ | 页面底部 + API 返回均包含，STI 卡片使用与全局 Disclaimer 同等显著的样式 |
| 数据溯源 | ✅ | 所有数据标注来源（东财涨停板四池） |
| 游资标签合规 | ✅ | 未涉及龙虎榜席位标签 |
| 席位标签免责声明 | 待实施 | Phase 3 席位引擎上线时需显著标注"历史统计特征，不构成投资建议" |
| **STI 视觉隔离** | ✅ | STI 卡片与个股数据之间有 section divider 隔离层 |
| **STI 标签解释** | ✅ | 五阶段标签旁增加解释性文字（"启动（情绪从低位回升，历史统计含义）"） |
| **source_ok=False 不伪造分数** | ✅ | 返回 null 而非 0 分+"退潮" |
| **回填节流合规** | ✅ | time.sleep(1.2) 对齐东财限流约定 |

---

## 12.8 服务状态

```
后端: http://127.0.0.1:8900  ✅
前端: http://127.0.0.1:5899/limitup  ✅
测试: 72 个全部通过 (15 原有 + 20 新增 + 37 其他)
TypeScript: 编译通过（0 新增错误）
Vite: 构建成功（17.67s）
```

---

## 13. 实施路线图（更新：独立模块方案）

### Phase 2（4 周）— 情绪 + 竞价 + 深度 + 复盘

| 序号 | 模块 | 文件 | 说明 | 优先级 |
|------|------|------|------|--------|
| 1 | STI 情绪温度引擎 | `limitup_sti.py` | 读取 market.py 输出，合成 7 维 STI，前端叠加情绪温度卡片 | **P0** |
| 2 | 个股深度页 | `/api/stock/{code}/deep` | 整合 K 线/资金流向/龙虎榜/AI 摘要 | **P0** |
| 3 | 竞价选股模块 | `auction_screener.py` | 盘后批量分析，生成次日竞价预案快照 | **P1** |
| 4 | 每日复盘报告 | `daily_review.py` | 盘后自动生成市场情绪+板块+个股复盘 | **P1** |
| 5 | 用户级阈值配置 | 前端 Settings 页面 | 所有金额类阈值支持用户配置 | **P2** |
| 6 | 基因得分日频预计算 | 改造现有 `limitup_screener.py` | 每日 15:30 后自动计算，缓存 12 小时 | **P2** |
| 7 | 回溯天数恢复 250 日 | 配置变更 | 预计算后不再受性能限制 | **P2** |
| 8 | 与 StockData 页面整合 | 前端路由调整 | 打板策略作为 StockData 页面的一个新 Tab | **P2** |

### Phase 3（4 周）— 席位 + 回测 + AI

| 序号 | 模块 | 文件 | 说明 | 优先级 |
|------|------|------|------|--------|
| 9 | 席位引擎冷启动 | `seat_engine.py` | 批量回溯 90-180 天龙虎榜数据，建立席位标签库 | **P0** |
| 10 | 简化版回测 | `backtest_lite.py` | 基因得分 vs 次日表现散点图 | **P1** |
| 11 | AI 过滤（XGBoost） | `ai_filter.py` | Phase 3 可选，需新增依赖 | **P2** |
| 12 | 动态止盈止损 (ATR) | 扩展 `risk_manager.py` | 需持仓数据支撑 | **P2** |

### Phase 4+（长期）

| 序号 | 模块 | 说明 |
|------|------|------|
| 13 | 完整回测引擎 | 向量化回测 + 冲击成本模型 + Walk-Forward 验证（在 trading-agents 中实现） |
| 14 | 与 trading-agents 模块打通 | 基因选股器作为前置过滤器，3 个旧打板策略作为后置评分器 |
| 15 | AI 复盘 Agent | 规则引擎判定 + LLM 自然语言转写，需交易流水录入 |
| 16 | 通知推送系统 | 飞书/企微实时信号推送（在 trading-agents 中实现，独立于 Vibe-Research） |

---

## 14. 附录

### 14.1 参考资料

1. [Limit-Up Sniper](https://github.com/guoyaohua/limit-up-sniper) — 涨停基因选股 + 排板/扫板
2. [N-Rebound](https://github.com/konodiodaaaaa1/N-Rebound) — XGBoost N字反弹
3. [dual-strategy-quant](https://github.com/chenhe81/dual-strategy-quant) — 双策略自动切换
4. 龙头战法十年实证 — 二板模型 77.1% 日胜率
5. 集合竞价混合模型 — 胜率逼近 65%
6. [a-Plate-Sentinel PRD V2.1](../a-Plate-Sentinel/docs/prd.md) — 参考设计源
7. [a-Plate-Sentinel Module Design V1.0](../a-Plate-Sentinel/docs/module-design.md) — 参考技术设计

### 14.2 术语表

| 术语 | 定义 |
|------|------|
| 首板 | 第一个涨停板 |
| 连板 | 连续两个及以上涨停板 |
| 一进二 | 首板后第二个板的打板策略 |
| 排板 | 涨停价挂单排队等待成交 |
| 扫板 | 主动吃掉涨停价卖单 |
| 炸板 | 涨停后打开涨停板 |
| 封单 | 涨停价位上的买单数量 |
| 弱转强 | 昨日弱势（摸板未封）今日转强（高开放量） |
| 板块共振 | 同一板块多只股票同时涨停 |
| 涨停基因 | 基于历史统计的涨停股次日表现因子 |
| Wilson 下界 | Wilson 置信区间下限，用于小样本校正 |
| T+1 | A股交易制度，当日买入次日才可卖出 |
| fbt | 封板时间（东财字段），格式：时×10000+分×100，9:25=92500 |
| lbc | 连板数（东财字段） |
| zdp | 涨停百分比（东财字段） |
| 涨停板四池 | 东财数据：涨停池/昨涨停池/炸板池/跌停池 |
| STI | Sentiment Temperature Index，情绪温度指数（0-100） |
| 竞价爆量 | 集合竞价阶段成交量显著高于历史均值 |
| 席位标签 | 基于龙虎榜历史数据统计的游资/量化资金特征标签 |
| 多资金共识 | 多个游资席位同时净买入同一标的 |
| 分歧信号 | 游资净买入 + 量化席位大额净卖出 |

### 14.3 免责声明

> **本模块产出的所有分析和交易信号均由量化模型自动生成，可能存在错误或偏差。**
> 
> - 涨停基因基于历史统计特征，不代表未来行为
> - 集合竞价信号仅为参考，不构成投资建议
> - 所有回测结果均基于历史数据，不代表未来表现
> - 席位标签基于公开历史数据统计，不构成对任何特定主体的身份指控
> - 投资决策请咨询持有中国证监会颁发资质的专业机构
> - 作者不对使用本工具产生的任何投资损失承担责任
> - **股市有风险，投资需谨慎**
