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

### 📅 M5：财报季排雷（ReportSeasonCircuitBreaker）——1/4/8 月雷区
- 财报季（1 月预告/4 月一季报+年报/8 月中报）雷区：未披露财报+财务指标异常节点→自动拉黑
- 从工程源头杜绝连续一字跌停（业绩雷）
- Vibe-Research 现有：reports/ + metrics/（缺财报季排雷 circuit breaker）

### 📅 M6：日历效应 + 国家队护盘——A 股非线性防线
- 日历效应：两会/十一/中央经济工作会等窗口先验概率修正
- 国家队护盘：跌破关键整数关口时权重股不计成本护盘行为函数（实时监控）
- Vibe-Research 现有：market 情绪 + indices（缺日历效应先验 + 国家队护盘函数）

### 🤖 M7：LLM 图谱智能体——DeepSeek 公告解析
- 本地大模型（DeepSeek 等开源）异步解析上市公司公告→标准 JSON→实时注入图谱
- 比肉眼更早捕获隐藏暗线概念股
- Vibe-Research 现有：chat.py（hithink LLM）+ stoke NLP（缺 LLM 公告→JSON→图谱注入）

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
- **股指期货基差（升贴水率）**：全市场对冲盘恐慌度牛熊风向标（中频波段监控，基差异常=对冲盘恐慌）
- **可转债反哺矩阵**：正股封死涨停→毫秒级联动买入 T+0 无涨跌停限制可转债，用 T+0 工具赚涨停溢价（高频短线，绕 A 股 T+1 限制）

## 6. Vibe-Research 落地（investing/quantitative-system/）

- 新建 `investing/quantitative-system/` 子区：M1-M4 方法论 + 五域实体 + risk_model + action
- 实体类扩展（21→加）：`factor` / `signal` / `backtest_result` / `trade_freq` / `regime` / `risk_model` / `stat_method` / `guru_strat`（游资战法，行为非名字）
- 关系：factor→stock / signal→trade / backtest→strategy / regime→signal / policy→sector（预期差动态权重）
- 复用 Vibe-Research 现有：s44_verifier（§44v2 验证 M4 断路器触发条件）+ ablation_runner（因子消融）+ trade_journal（模拟盘验 M3 CentralRouter）+ strategies/cards（M1 打板战法）

## 6.5 流程系统（端到端，方法论串成流程）

数据采集 → 图谱注入 → 因子计算 → 策略生成 → 回测验证 → 模拟盘 → 实盘执行 → 风控 → 反馈闭环

1. **数据采集（DataHub）**：astock/gstock/newsradar/market + baostock cache 5230 股 + stoke NLP + mootdx tick（M1 VPIN 原料）
2. **图谱注入（M7 LLM 智能体）**：DeepSeek 公告→JSON→图谱 inbox 待审 + 实体/关系更新
3. **因子计算（AlphaEngine）**：向量化 + shift(1) 防前视 + M1 VPIN/M2 预期差/M6 日历效应因子
4. **策略生成**：strategies/cards + S194 信号融合（方向感知编码 S199）+ M3 CentralRouter 跨频次撮合
5. **回测验证（BacktestCore）**：A 股 T+1/成本/涨跌停 + §44v2 s44_verifier（day_paired+permutation+Bonferroni+walk_forward+days_robust<60 cap）
6. **模拟盘**：trade_journal + forward_test 30/60 天
7. **实盘执行（TradeExecutor）**：S192 开户后 QMT/PTrade + M3 CentralRouter 内部撮合
8. **风控**：M4 断路器（相关性>0.85 冻结）+ M5 财报季排雷 + RiskController 敞口
9. **反馈闭环**：forward_test 30/60 天复验 → DIMENSION_LIFT_REGISTRY 更新 → lift_to_multiplier 调整 → 策略升/降级 → 回测修正

## 6.6 闭环（三重反馈，防断裂）

- **策略闭环**：spec→plan→tasks→TDD+grill+verification → 模拟盘 → forward_test 30/60 天 → R3 enforce（S197 两门 safeguard）→ lift 复验 → 升降级 → 回测修正
- **图谱闭环**：代码改实体→图谱同步（CLAUDE.md 会话开始协议）+ reviews 8 项检查（断链/孤立/coverage）+ inbox 待审（M7 LLM 抽取实体先进 inbox 审核通过才进正式区，注入质量门）
- **§44v2 闭环**：lift 验证 → DIMENSION_LIFT_REGISTRY DB-backed 动态读（S197 R2）→ lift_to_multiplier → 生产权重 → 30/60 天复验 → 升降级（迟滞带防抖动，月频非周频）

## 6.7 质量保证（多道防线，有质量）

- **SDD §0 分级工作流**：small/medium/large + spec→plan→tasks→TDD+grill+verification（CLAUDE.md §0.1）——每条方法论子 spec 走 SDD
- **§44v2 统计防线**：day_paired+permutation+Bonferroni+walk_forward+days_robust<60 provisional cap ×0.5（不阻断集成但诚实标注）——M1-M7 因子都要过
- **对抗审查 ≥6 视角**：统计方法论/承重代码 adversarial verify（CLAUDE.md 自动复盘 2026-09-05）——S198/S197/S193 R5 已验证抓到 solo 漏的 CRITICAL（look-ahead/基线 endogenous/ci_overlap 死接线）
- **图谱质量门**：inbox 待审（confidence+source+quality_score）+ reviews 8 项检查 + 断链/孤立/coverage——M7 LLM 注入不直接灌入
- **工程底线**：不臆造（financial_rigor.py 验算）+ 私有数据隔离（.vibe-research/ gitignored）+ em_get 防封（限流/熔断/代理）
- **M4/M5/M3 防线**：断路器（相关性>0.85 冻结切现金）+ 财报季排雷（1/4/8 月拉黑）+ CentralRouter 内部撮合（防多频次内耗）
- **forward_test 30/60 天 R3 enforce**（S197）：live OOS 积累（backfill 无效=真 blocker）→ 两门 safeguard（enforce=跑+写+报 pending，promote=人 review 后 apply）→ 防自动改生产权重破坏

## 6.8 verdict 修订（quant-system-brainstorm ww1bqpg70 synthesizer，7 处）

方向正确但低估 Vibe-Research 已有能力 + 3 结构性缺陷，7 修订：
1. **不引入 backtrader**——复用现有 engine/{executor,accounting,fill_policies}.py（已建模 T+1 offset≥1/cost 0.70%/涨跌停 board-aware/一字板 unbuyable），引入双轨维护 + backtrader 默认 fill 无封板成交概率
2. **不换 akshare/tushare**——em_get 三合一防封（限流 0.3s+熔断器双组+代理探测）比爬虫强，只加统一 get_kline(code,start,end,freq) 接口（bars_provider 雏形）+ hithink DuckDB 作批量回测源
3. **不降级 t 检验**——§44v2（day_clustered+permutation+Bonferroni K≤8+walk_forward+DSR/PBO/haircut）比 IC/IR+t 检验强一个量级，ADD IC/IR+分层回测（5/10 组单调+Newey-West HAC）作互补非替代
4. **补第四频次桶**（打板 T+1 涨停事件）——用户三桶缺，12 战法卡+七态状态机+1092 case，二元稀疏事件用 §44v2 event lift 非 IC/IR 横截面，频次隔离不可混测
5. **先修已确认 CRITICAL bug**：gap_classifier 前视（_is_filled D+1..D+3）+ cost 口径 0.70% vs 0.2% 不一致（撞"判断须可复现"底线）+ ST 按 code 检测失效（limitup_strategy:48）+ industry_normalized stub（recommendation_engine:156）+ 北交 30% 缺失
6. **backfill 2018 再上 OOS**——当前 KlineCache 174 日缺口 >90%，walk_forward 仅 2-3 窗口统计功效极低
7. **建 quantitative-system/ 子区**（11 新实体+22 关系+17 logic 规则+4 动作），quant_signal 双链回指现有 strategies/gap-theory 非重建

## 6.9 优先 spec（verdict 11 条，按优先级）

| spec | 优先级 | 内容 |
|---|---|---|
| S-gap-classifier-lookahead-fix | CRITICAL | _is_filled 前视修复（标签训练可用未来，实盘信号只用 T 及之前 bar 重算）独立 spec |
| S-cost-caliber-unification | CRITICAL | accounting 0.70% vs S194 0.2% 口径统一（slippage 0.60% vs 0.10% 差 6x，§44 net verdict 前强制校验一致）|
| S-get-kline-unified-interface | HIGH | 统一 get_kline(code,start,end,freq)（取数散落 astock/bars_provider/kline_history/baostock 5+处）|
| S-IC-IR-evaluation-layer | HIGH | compute_ic(Spearman+Newey-West HAC lag=3)+compute_ir+月度 IC+分层回测（5/10 组 Jonckheere-Terpstra）|
| S-industry-neutralization | HIGH | recommendation_engine:156 stub→真 demean+residualize（skill-factor-orthogonalize）|
| S-historical-backfill-2018 | HIGH | baostock 回补到 2018-01-01 支撑 OOS（当前 174 日缺口 >90%，验收交易日≥1500）|
| S-st-detection-fix | MEDIUM | limitup_strategy:48 ST 按 code 恒 False（ST 在 name）+北交 832/920=30%+新股前 5 日|
| S-direction-aware-gap-encode | MEDIUM | = S199（GAP_REGIME_ENCODE 方向感知）|
| S-quantitative-system-graph-entry | MEDIUM | = S200（11 实体+22 关系+17 规则+4 动作）|
| S-cross-freq-signal-align | MEDIUM | = S194 R1（signal_align 跨频次对齐层）|
| S-lift-to-multiplier-reactivation | P0 TODO | = S197/RB-8（替代读冻结值+days<60 cap+R3 enforce）|

## 6.10 graph_landing（investing/quantitative-system/ 子区，12 子目录）

factors/(alpha_factor) / signals/(quant_signal 枢纽类，[[]]双链回指 strategies/gap-theory) / backtests/(backtest_result) / frequencies/(trade_freq 四桶) / stat-methods/(stat_method 映射 s44_verifier) / cost-models/(cost_model 映射 accounting) / execution/(execution_broker) / regimes/(quant_regime) / risk-models/(risk_model) / edge-types/(edge_type) / logic/(防未来函数/T+1 约束/涨跌停/防过拟合门/窗口偏差/小样本降权/多重检验/频次隔离/cost 一致性/survivorship/regime 条件/方向感知 17 规则) / actions/(跑回测/验证信号/执行交易/风控熔断 4 动作)。桥接现有：data-sources/(17)→quant_data_hub / specs/(101)→stat_method / dragon-tiger/(41)→execution_broker/seat_profile。

## 7. 受影响文件 + 关联 spec

| 文件/spec | 改动 |
|---|---|
| `investing/quantitative-system/` | 新建子区（M1-M4 + 五域实体 + risk_model + action）|
| `investing/MOC.md` | 加 quantitative-system 导航 |
| `investing/logic/` | 加 M2 预期差 + M3 CentralRouter + M4 断路器 logic 规则 |
| `investing/actions/` | 加 internal_crossing + circuit_breaker_freeze + broadcast_signal |
| S201-M1（VPIN）| 新 spec：VPIN 订单流毒性 + 冰山订单检测 |
| S202-M2（预期差）| 新 spec：Beta News Sensitivity + 预期差度量 + 日历效应先验（M6 并入）|
| S203-M3（CentralRouter）| 新 spec：逻辑账户隔离 + 内部撮合路由 |
| S204-M4（断路器）| 新 spec：因子相关性矩阵 + Systemic Circuit Breaker |
| S205-M5（财报季排雷）| 新 spec：ReportSeasonCircuitBreaker（1/4/8 月雷区拉黑未披露+财务异常）|
| S206-M6（日历+国家队）| 新 spec：两会窗口先验 + 国家队护盘行为函数 |
| S207-M7（LLM 智能体）| 新 spec：DeepSeek 公告→JSON→图谱注入 + 暗线概念股捕获 |

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
