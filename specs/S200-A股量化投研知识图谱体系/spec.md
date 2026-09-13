# Spec: S200 — A股量化投研知识图谱体系构建（4 破局哲学 + 五域 + 跨频次 + Vibe-Research 落地）

> 状态：草案（方法论底层 spec；4 方法论 + 五域骨架来自用户头脑风暴 + Red Teaming；Vibe-Research 落地待 quant-system-brainstorm workflow 综合后定稿）
> 作者：Claude  日期：2026-09-13
> 分级：large（图谱认知层 + 编码工程 + 统计工程 跨层，多 spec 编排）
> 关联：[[ashare-quant-red-teaming-4-pitfalls]] memory / [[S193-缺口理论]] / [[S194-信号融合]] / [[S198]] / [[S199]] / [[S159-§44v2]] / `ontology-knowledge-graph` skill

## 1. 问题 / 目标

**核心矛盾**：缝合"主观投研艺术（游资/政策/轮动）"与"量化工程科学（编码/统计/风控）"，在零实盘经验下构建逻辑闭环、无法被轻易收割的 A 股量化投研体系。

**破局**：不猜"他是谁"（席位名），度量"他的行为"（资金微观结构）；不抓静态关键词，度量动态预期差；多频次虚拟路由内部撮合消除内耗；非平稳市场动态断路器防踩踏。

**目标**：在 Vibe-Research 现有架构（数据层 astock/gstock + 策略层 strategies/cards + 评价层 s44_verifier §44v2 + 执行层 scheduled_tasks/trade_journal + 认知层 Obsidian investing/ 21 实体类）上，构建**量化投研知识图谱体系**——4 方法论底层骨架 + 五域实体 + logic 规则 + risk_model + action，落地 investing/quantitative-system/。

## 2. 方法论骨架（4 破局哲学，图谱 logic+risk_model 核心）

### 🛡 M1：资金微观结构（Microstructure）——度量行为非名字
- **放弃席位名**（拖拉机账户+量化互收割伪装）→ 用订单流微观结构
- **VPIN（Order Flow Toxicity）**：主动买入大单 vs 主动卖出大单瞬时失衡比，>3σ = 超级大鳄扫货/砸盘
- **冰山订单检测**：买一到买五挂单量暴增但不成交+瞬间撤单 = 量化算法测试
- **图谱实体**：`异常主力行为_类型A`（不记"白头女"，记微观特征）→ 连线股票 → 广播短线打板模块"流动性即将暴增"
- Vibe-Research 现有：dragon-tiger 表（席位，降级 context）+ mootdx tick OFI（雏形）→ 加 VPIN 毒性度量 + 撤单率/挂单失衡

### 🌐 M2：动态预期差（Dynamic Expectation Gap）——非静态关键词
- **政策不是绝对利好，超出预期才是**——度量预期差
- **新闻敏感度弹性（Beta of News Sensitivity）**：政策热度 10→100 但股价没反应 = price in / 借利好出货（负向信号）；热度 0→5 但龙头竞价无量空涨 = 聪明资金抢筹（极高预期差，爆发前夜）
- **动态权重**：图谱连线按"价格/成交量对新闻滞后反应时间"动态计算，非静态
- Vibe-Research 现有：stoke NLP + market 情绪 + sector_phase → 加 Beta News Sensitivity + 预期差度量（周末热+周一竞价没量+龙头没封一字→极度危险）

### 🔀 M3：虚拟路由（CentralRouter / Internal Crossing）——多频次内耗消除
- **逻辑账户隔离**：子账户 A（长线）+ 子账户 B（短线高频），各自决策大脑独立
- **中央撮合路由**：A 买 10 万 + B 卖 2 万同标的 → 内部对冲 10-2=8 万 → 只向券商发"买 8 万"→ 省税费 + 保策略纯洁性
- Vibe-Research 现有：trade_journal + scheduled_tasks（分频次但无统一风控/内部撮合）→ 加 CentralRouter + 逻辑账户隔离

### 🚨 M4：动态断路器（Systemic Circuit Breaker）——非平稳防踩踏
- **不相信历史，只信当下**：监控因子暴露度相关性矩阵（非仅收益率）
- **相关性 >0.85（3 日内）**：全市场不同流派策略相关性飙升 = 生态级剧变（政策突变/公募踩踏/流动性黑天鹅）→ 强制"仓位减半/只卖不买"防守
- **2024 微盘股踩踏教训**：国九条+ST 新规 → 10 年回测模型爆仓，历史废纸
- Vibe-Research 现有：§44 v2 + em_get circuit_breaker（防封非因子）→ 加因子相关性 Systemic Circuit Breaker

## 3. 五域实体（用户框架，落地 investing/quantitative-system/）

| 域 | 实体 | 关系 | Vibe-Research 现有 |
|---|---|---|---|
| 政策/宏观 | 中央会议/央行/证监会/国家大基金/政策关键词 | 政策--(利好/利空)-->板块 | events/ + stoke NLP（缺政策 NLP 关键词 + 预期差 M2） |
| 产业/板块 | 申万行业/概念/产业链上下游 | 上游--(传导)-->下游/板块A--(轮动领跑)-->板块B | industries/ + concepts/ + sector_phase（缺 Markov 转移矩阵 + LASSO 筛选） |
| 资金/席位 | 龙虎榜席位（**降级 context**）/异常主力行为（M1 微观结构） | 席位--(净买入)-->标的/异常行为-->标的 | dragon-tiger/（缺 VPIN M1） |
| 学术/社区 | ArXiv 论文/研报/雪球股吧舆情/GitHub 量化库 | 研报--(覆盖)-->股票/社区情绪--(预示见顶)-->标的 | reports/ + analysts/ + newsradar（缺社区舆情 + 预期差 M2） |
| 策略/模型 | 打板/趋势波段/高频 T+0/战法卡/因子/信号/backtest_result | 策略--(买卖信号)-->标的/因子--(驱动)-->策略 | strategies/cards/（12 战法卡）+ s44_verifier（缺 CentralRouter M3 + 断路器 M4） |

## 4. logic 规则 + risk_model + action（四构件动态层）

**logic 规则**：
- M2 预期差：周末热度+周一竞价没量+龙头没封一字→"极度危险"评级
- M3 CentralRouter：高频卖+低频买同标的→内部虚拟撮合抵消，不报交易所
- M4 断路器：全市场风格因子相关性 >0.85（3 日）→强制冻结自动交易切人工
- §44v2：因子 lift<2x/方向无关编码→no_contribution（S199 方向感知修）

**risk_model 实体**（新增）：
- `VPIN`（订单流毒性，M1）
- `factor_correlation_matrix`（因子相关性矩阵，M4）
- `systemic_circuit_breaker`（相关性>0.85 强制减半/只卖不买，M4）
- `central_router`（内部撮合 + 逻辑账户隔离，M3）

**action 构件**（新增）：
- `internal_crossing`（CentralRouter 内部撮合）
- `circuit_breaker_freeze`（强制冻结自动交易）
- `broadcast_signal`（异常行为/预期差→广播各频次策略）

## 5. 跨频次联合调度（编码工程）

- **底层统一资产库 + Barra 风险对冲**：RiskController 监控全系统总敞口（Beta Exposure），短线打板买医药+中长线选股自动调低医药权重防单一行业过度暴露
- **中层图谱特征广播**：GraphEngine 实时解析新闻/研报，"半导体"节点关联热度暴涨 300%→广播 Sector_Heat_Signal→短线加入打板池+趋势算周线突破
- **频次隔离**：逻辑账户 A（长线基本面）+ B（短线高频）+ C（中频波段），各自决策，CentralRouter 内部撮合

## 6. Vibe-Research 落地（investing/quantitative-system/）

- 新建 `investing/quantitative-system/` 子区：M1-M4 方法论 + 五域实体 + risk_model + action
- 实体类扩展（21→加）：`factor` / `signal` / `backtest_result` / `trade_freq` / `regime` / `risk_model` / `stat_method` / `guru_strat`（游资战法，行为非名字）
- 关系：factor→stock / signal→trade / backtest→strategy / regime→signal / policy→sector（预期差动态权重）
- 复用 Vibe-Research 现有：s44_verifier（§44v2 验证 M4 断路器触发条件）+ ablation_runner（因子消融）+ trade_journal（模拟盘验 M3 CentralRouter）+ strategies/cards（M1 打板战法）

## 7. 受影响文件 + 关联 spec

| 文件/spec | 改动 |
|---|---|
| `investing/quantitative-system/` | 新建子区（M1-M4 + 五域实体 + risk_model + action）|
| `investing/MOC.md` | 加 quantitative-system 导航 |
| `investing/logic/` | 加 M2 预期差 + M3 CentralRouter + M4 断路器 logic 规则 |
| `investing/actions/` | 加 internal_crossing + circuit_breaker_freeze + broadcast_signal |
| S201-M1（VPIN）| 新 spec：VPIN 订单流毒性 + 冰山订单检测 |
| S202-M2（预期差）| 新 spec：Beta News Sensitivity + 预期差度量 |
| S203-M3（CentralRouter）| 新 spec：逻辑账户隔离 + 内部撮合路由 |
| S204-M4（断路器）| 新 spec：因子相关性矩阵 + Systemic Circuit Breaker |

## 8. 验收

- [ ] A1：4 方法论 logic 规则落图谱（M1-M4）
- [ ] A2：五域实体 + risk_model + action 落 investing/quantitative-system/
- [ ] A3：MOC + MASTER_INDEX 更新
- [ ] A4：Vibe-Research 现有复用（s44_verifier/ablation/trade_journal/strategies）映射
- [ ] A5：4 方法论各起子 spec（S201-S204）+ 对抗审（统计方法论 + 编码承重）

## 9. 合规与工程底线

- [x] 不臆造：M1-M4 方法论从用户 Red Teaming 提炼 + Vibe-Research 现有复用
- [x] §44v2 防过拟合：M4 断路器用因子相关性（非仅收益率）+ §44v2 验证触发条件
- [x] 私有数据隔离：VPIN/tick 数据在 .vibe-research/（gitignored）
- [x] 不预断 edge：4 方法论是防御性（防收割）非"赚钱保证"
- [x] 零实盘：S192 不开户先 SuperMind 回测 + trade_journal 模拟盘验 CentralRouter

## 10. 实现时序

- **现在（9-13）**：S200 spec 草案（方法论骨架 + 五域 + 落地框架）
- **quant-system-brainstorm workflow 综合**（若回来）：整合 4 调研+6 专家 → spec 定稿 + priority_specs
- **4 方法论子 spec**（S201-S204）：各起 spec + 对抗审 + 实现
- **图谱落地**：investing/quantitative-system/ 子区 + 实体 + 关系 + logic + action
