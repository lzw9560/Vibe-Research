# S234 短线战法排雷过滤器（Short-Term Tactics Filter）

> 状态：降级完成版收口（2026-10-17）。Phase 1-4 核心已实现（2184f92），T1.6 blocked（依赖 S235 Phase B 实时竞价）、T1.8/T1.9 deferred（数据源 plan stale：baostock bar 无 ltsz + falsified 战法过滤器边际低）。降级版第一层用 ST+5日均成交。
> 编号：S234
> 关联 memory：[[short-term-tactics-knowledge-2026-10-07]] + [[quant-traps-four-pitfalls-2026-10-07]] + [[commander-automation-wired-2026-10-07]]

## 1. 问题 / 目标

用户提供两大战法（弱转强抢筹 9:25 + 尾盘趋势锁定 14:50）+ 双层漏斗 + 🔔 JSON 输出格式，要求"落入记忆，同步更新投研系统，sdd"。

**但项目实测**：
- 战法1（弱转强）= consecutive_relay falsified **-1.66% definitive**（p=1.0, n_test 89/65≥60）
- 战法2（尾盘锁定）= baostock_5min_freeze / seal_timing **假 edge**（survivorship + entry涨停价 + exit一字 over-credit）
- 双层漏斗第二层因子（竞价量比/换手/板块共振/龙虎榜席位）= 打板接力因子，19 信号全 falsified

**目标**：建一个**诚实**的排雷过滤器——不假装战法有 alpha，而是：
1. 第一层财务硬过滤（sound，可落地）
2. 第二层情绪因子匹配（**标 falsified**，不假装 alpha 来源）
3. 输出 JSON（is_passed/risk_level/hit_rules/reason/safe_action）——借鉴用户给的安全审查模板
4. 仓位建议附 verdict 诚实标注（R30）
5. 不编"主力意图"（§1.2 工程底线：判断须可复现+禁止臆造，只基于可观测量价/席位）

## 2. 需求清单

- **R1 双层漏斗第一层（财务硬过滤，一票否决）**：流通市值 30-150 亿 / 剔除 ST+*ST+退市+资产负债率>85%+非标意见 / 5 日均成交>1.5 亿
- **R2 第二层情绪因子匹配（标 falsified）**：
  - 战法1（9:25）：竞价量比>3.5 / 竞价成交额占比>8% / 高开 2-5%
  - 战法2（14:50）：日换手 12-22% / 收盘>=99.5% 日内最高+站稳 VWAP / 同板块 2+ 涨停 / 龙虎榜席位>8%
  - **每个因子旁标项目 verdict**（如"竞价量比>3.5 → 打板因子 falsified"）
- **R3 JSON 输出**：`{is_passed, risk_level, hit_rules, reason, safe_action}` —— Pass=可进观察池 / Block=剔除 / Refuse=黑名单
- **R4 仓位建议附 verdict**（R30）：红利低波✅ / 打板🔴falsified / 小市值⚠️OOS fail
- **R5 不编主力意图**：只基于可观测数据（量价/席位/换手/板块），"主力意图"类话术标"主观推断"
- **R6 复用现有基建**（不重造）：pre_market_workflow / strategies/funnel/ / first_board_filter._market_phase / gene_scores.zt_count_250d / dragon_tiger_history.db
- **R7 双时段触发**：9:25 早盘（竞价快照）+ 14:50 尾盘（盘中确认），接 scheduled_tasks cron

## 3. 受影响文件

**新建**：
- `backend/tools/short_term_tactics_filter.py`（排雷过滤器主脚本，输出 JSON）

**接入**：
- `backend/tools/commander_runner.py`（沸点期调用排雷过滤器）
- `backend/tools/fetch_market_sentiment_metrics.py`（已有，情绪诊断判断是否沸点）
- `backend/tools/calculate_position_allocation.py`（已有，仓位+verdict）

**复用（不改）**：
- `backend/pre_market_workflow.py`（PreMarketWorkflow.run 完整盘前）
- `backend/strategies/funnel/`（漏斗选股 aggregation + non_limitup_funnel）
- `backend/strategies/first_board_filter.py`（_market_phase 五状态机）
- `backend/strategies/position_advisor.py`（cap_by_market_phase 仓位闸）
- `.vibe-research/gene_scores.db`（zt_count_250d 股性 + code_industry 行业）
- `.vibe-research/dragon_tiger_history.db`（1 年席位）
- `.vibe-research/baostock_kline_cache.db`（5248 股 kline）
- `.vibe-research/zt_history.db`（涨停+连板）

## 4. 验收标准

- [ ] 第一层财务过滤可跑（市值/ST/资产负债率/成交额 从 baostock_kline + gene_scores + hithink 取）
- [ ] 第二层因子匹配可跑（竞价/换手/板块/龙虎榜 从 zt_history + dragon_tiger + intraday 取）
- [ ] 输出 JSON 合法（is_passed/risk_level/hit_rules/reason/safe_action 五字段）
- [ ] 每个第二层因子旁标项目 verdict（falsified 诚实标注）
- [ ] 仓位建议附 verdict（R30）
- [ ] 不编主力意图（"主力意图"类话术标"主观推断"或剔除）
- [ ] commander_runner 沸点期调用排雷过滤器
- [ ] pytest 单元测试覆盖第一层+第二层+JSON 输出
- [ ] 不臆造数据（所有因子从项目 cache 取，可复算）

## 5. 合规自查（弱合规，工程底线）

- [x] 不臆造数据（所有因子从项目 cache 取，可复算）
- [x] 私有数据隔离（.vibe-research/，不进 git）
- [x] em_get 防封（龙虎榜走 em_get 限流，已有 dragon_tiger_history backfill）
- [x] verdict 外推禁令（战法1/2 falsified 不假装就绪，不回"引擎已就绪"）
- [x] 不编主力意图（§1.2 禁止臆造，只基于可观测数据）
- [x] 仓位建议附 verdict（R30 诚实标注）

## 6. plan / tasks（后续）

- plan.md：技术方案（复用 pre_market_workflow + funnel，不重造；JSON 输出 schema；双时段 cron 接入）
- tasks.md：可执行 checklist（第一层→第二层→JSON→commander 接入→cron→测试）

## 7. 关键 caveat（诚实）

用户要"完全自动化运转"+"引擎已就绪"——**spec 阶段不假装就绪**。战法1/2 项目 falsified，排雷过滤器是**降低候选池**非**翻正 verdict**。沸点期打板仍标"全样本 falsified + regime-conditional 未测"。用户接受高风险才激活，过滤器输出标 risk_level=High + verdict falsified。
