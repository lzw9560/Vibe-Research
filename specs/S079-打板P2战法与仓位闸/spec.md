# Spec: S079 — 打板 P2 仓位闸 + 龙虎榜黑名单（瘦身版）

> 状态：草案
> 作者：Claude  日期：2026-08-18
> 关联：`CLAUDE.md` §1.1、`specs/S002-打板工作流重构/spec.md`（P1 候选池漏斗）、`specs/S070-intraday采集管道/`（数据层，R6-R8 战法因子派生，本 spec 不依赖）、`specs/S081-打板P2战法匹配/`（backlog，等 S070 R7）、`specs/S074-market_phase统一判定/`、`backend/seat_engine/`、`backend/strategies/hot_money_seats.py`、原 PRD `/Users/lizhiwei/Downloads/Quantitative_Limit_Up_Trading_System_Implementation_Guide.md`
>
> **三拆背景**：原 PRD 含战法匹配+仓位闸+龙虎榜三模块。Oracle 审查发现 PRD 2 战法核心因子（broken_duration_min/max_drop_pct/last_lock_time）在 repo 零匹配，需新增分时数据源 —— 战法匹配拆 S081 等 S070 R7 派生字段就绪（原计划独立 S080 spec 已并入 S070 R6-R8）。本 spec 瘦身只做**仓位闸扩展 + 龙虎榜黑名单层**，两者不依赖分时数据源，可先行。

---

## 1. 问题 / 目标

S002 P1 已落地候选池漏斗 + 诊断卡。`pre_market_workflow.py` 已有完整链：候选池 → `StrategyMatcher.match` → `PositionAdvisor.advise_batch(weather_state)` → `position_suggestions`。但缺两层：(1) PRD 三状态仓位闸（大面股/跌停/晋级率/连板高度 → 绿/黄/红总仓位上限熔断）；(2) PRD 龙虎榜席位三分级风控（黑名单硬剔除/独食独大/散户霸榜）。

**目标**：扩展 `first_board_filter._market_phase()` 加 PRD 4 因子 + 红期硬熔断覆盖；在 `PositionAdvisor` 既有 weather 熔断之上叠加 `cap_by_market_phase` 后处理；复用既有 `seat_engine`/`hot_money_seats` 加 PRD 黑名单硬剔除层。一句话：P1 漏斗 + 既有战法匹配输出后，叠加仓位闸 + 龙虎榜黑名单两层后处理。

---

## 2. 背景

### 2.1 既有管线盘点（Oracle B1 修复）

| 文件:行 | 既有能力 | 本 spec 关系 |
|---|---|---|
| `pre_market_workflow.py:96-97,124,149-150` | 已实例化 StrategyMatcher + PositionAdvisor，链路：候选池 → match → advise_batch(weather_state) → suggestions | **复用，不替代**。本 spec 在 advise_batch 输出后加 cap_by_market_phase |
| `strategies/position_advisor.py:56-120` | `PositionAdvisor.advise(signal, weather_state)`，已有 weather 熔断：暴风雨→None，极端反弹→cap 0.5，max_total_position=0.8 | **叠加，不替换**。weather 熔断保留，cap_by_market_phase 作为第二层上限 |
| `strategies/strategy_matcher.py:22` | `StrategyMatcher` 包装 `match_strategies`，已被 pre_market_workflow 消费 | **本 spec 不改**（战法匹配扩展拆 S081） |
| `limitup_strategy.STRATEGY_REGISTRY` | 8+1 战法已定义，`match_strategies` 已实现 | **本 spec 不改** |
| `seat_engine/service.py` | `SeatEngine`：build_seat_profiles / compute_consensus_signal（机构占比）/ get_seat_profile | **复用**，PRD 黑名单层在其上加 |
| `strategies/hot_money_seats.py` | 60 日龙虎榜聚合，SeatProfile（一日游/接力型/机构），SeatRiskFactor（day_trip_ratio） | **复用**，但"绕过 em_get"需处置（见 §5.3） |

### 2.2 与原 PRD 的逻辑冲突处置（AGENTS.md spec 逻辑冲突审查）

| # | 冲突点 | 原 PRD 立场 | repo 现状 | 处置 |
|---|---|---|---|---|
| 1 | 合规边界 | 直接给交易方向/买卖时机 | CLAUDE.md §1.1 已降级弱合规 | **遵循 §1.1**：主流程给方向/时机/参数，挂轻量风险提醒 |
| 2 | 系统定位 | 数据→清洗→指挥→**执行** | 不接券商不下单 | **纯信号生成**：系统出参数 + 推送，用户手动下单（Q2 决议） |
| 3 | 龙虎榜数据通道 | `ak.stock_lhb_detail_em` | `seat_engine`（datacenter）+ `hot_money_seats`（datacenter，注释"绕过 em_get"）+ `stock_financial.dragon_tiger`（astock） | **复用既有 seat_engine/hot_money_seats**，不新增 akshare 通道。`hot_money_seats` "绕过 em_get" 需核实 datacenter 是否真不需 em_get 防护，或套上限流（§5.3） |
| 4 | 战法集合 | 2 战法（弱转强+形态反包） | STRATEGY_REGISTRY 8+1 战法已实现，`StrategyMatcher` 已消费 | **拆 S081**：PRD 2 战法硬阈值（broken_duration≥20min 等）需分时数据源，拆 S081 等 S080 数据层就绪。本 spec 不涉及战法匹配扩展 |
| 5 | 仓位控制 | 三状态硬区间 70-100%/30-50%/0-20% | `PositionAdvisor.advise` 已有 weather 熔断（暴风雨→None，极端反弹→cap 0.5）+ max_total_position=0.8 | **上限约束叠加**：PRD 三状态作为第三层上限，叠加在 weather 熔断 + max_total_position 之上。叠加代数：`final_cap = min(weather_cap, market_phase_cap, max_total_position)`（见 §3.3 R10） |
| 6 | 情绪状态机 | PRD 三状态（绿/黄/红） | STI 8 维度加权 → 4 天气（T-1 盘后）；`first_board_filter._market_phase()` 单 zt_count → 4 档（冰点/普通/活跃/亢奋，用于评分权重分层） | **扩展现有 `_market_phase()`**：从单 zt_count 改为 4 因子输入 + 红期硬熔断覆盖。不引入新概念 MarketSwitch。STI 是 T-1 盘后总结，`_market_phase` 是 T+1 盘前仓位闸因子，时序用途不同 |
| 7 | 龙虎榜席位风控 | 黑名单硬剔除 + 独食独大 + 散户霸榜 | `seat_engine` 有机构占比计算 + `hot_money_seats` 有一日游/接力型分类，**无黑名单硬剔除** | **在既有之上加黑名单层**：复用 seat_engine 的占比计算基础，新增 config/seat_blacklist.yaml + 子串模糊匹配 + 硬剔除逻辑。独食独大/散户霸榜复用既有 day_trip_ratio 基础扩展 |

### 2.3 S002 隔离决议显式豁免（Oracle B5 修复）

S002 §2/§9 决议："参考价位（入场/止损/止盈）不在主流程，隔离为研究模式 spec（S00x）单独签字"。grep `specs/` 无 S00x —— 该隔离决议从未解除。

本 spec R12 输出触发价/竞价达标额/仓位参数，事实上废弃该隔离决议。按 AGENTS.md spec 逻辑冲突审查，必须显式宣布豁免：

- **豁免依据**：CLAUDE.md §1.1（2026-07-30）弱合规允许研判/买卖时机/收益预期；`position_advisor.py:107-108` 已输出 `entry_price_range`（entry_low/entry_high）作为既成事实先例。
- **豁免范围**：P1 漏斗/诊断卡本体仍守 AC10（不输出方向结论词）；P2 输出层（仓位闸 + 龙虎榜黑名单 + 信号参数）放宽到 §1.1 弱合规口径，允许输出触发价/熔断仓位/【拒绝介入】等量化方向参数，挂轻量风险提醒。
- **未豁免**：不接券商、不下单（AC7 工程底线保留）；参考价位（止损/止盈）仍不在本 spec，属 S081 战法匹配 spec 范围。

### 2.4 历史 spec 关系

- **S002（P1 已实现）**：本 spec 是其 P2 首批，复用 R1/R2/R3 漏斗输出 + pre_market_workflow 既有链路。**S002 不改**。
- **S080（先行，数据层）**：seal_intraday 分时数据扩展，派生 broken_duration_min / max_drop_pct / last_lock_time。**本 spec 不依赖 S080**（仓位闸 + 龙虎榜不需要分时数据）。
- **S081（backlog，等 S080）**：战法匹配扩展（PRD 2 战法硬阈值）。依赖 S080 数据层就绪。本 spec 不涉及。
- **S074（market_phase 统一判定）**：草案未实现，关注时段判定（pre-market/intraday/post-market），与 `_market_phase()` 情绪档位概念正交。
- **limitup-design.md**：其中"策略逻辑教育展示"定位作废，迁移到弱合规主流程。本 spec 在该文档标注 supersede 段落（见 §10 T6），不留"宣布作废但不修改"的活跃文档。

---

## 3. 需求清单

### 3.1 龙虎榜席位三分级风控（Q7，复用既有 seat_engine/hot_money_seats）

- [ ] R1：复用 `seat_engine.SeatEngine.compute_consensus_signal()` 获取 T-1 龙虎榜买卖席位 + 机构占比
- [ ] R2：黑名单硬剔除 —— 买入前五席位中≥1 个黑名单席位且占比>15% → 标的从候选池硬剔除，看板标【拒绝介入】
  - [ ] R2.1 黑名单名单维护在 `config/seat_blacklist.yaml`（PRD §3 初始列举 + 可扩展）
  - [ ] R2.2 席位匹配用**子串模糊匹配**（应对"中国国际金融上海分公司" vs "中金公司上海分公司" 等写法差异）
- [ ] R3：独食独大软标记 —— 买一席位占比≥55%（前五买入额）或≥10%（全天成交额）→ 标 `risk_flags=["独食独大"]`，PositionAdvisor 仓位砍半（复用 `hot_money_seats.SeatRiskFactor` 基础扩展买一占比计算）
- [ ] R4：散户大本营霸榜软标记 —— 买入前五中拉萨团结路/东环路等席位≥3 个 → 标 `risk_flags=["散户霸榜"]`，战法匹配置信度降权（复用 `hot_money_seats.day_trip_ratio` 基础扩展席位计数）
- [ ] R5：数据缺失处置（Oracle H4 修复）—— 龙虎榜"未取得"时，黑名单硬剔除**不可执行**（标"席位风控数据未取得，硬剔除不可执行" + 显著警示），由用户决策。与 AC6 透明原则一致，不默认放行（风控绕过）也不默认拒绝（数据抖动误杀）

### 3.2 T+1 仓位闸（Q5 + Q6 + Q8=C 扩展 _market_phase）

- [ ] R6：扩展 `first_board_filter._market_phase()` 从单因子 zt_count 改为 PRD 4 因子输入 + 红期硬熔断覆盖（**不引入新概念**）
  - [ ] R6.1 扩展因子输入：`zt_count`（保留）+ `big_loss_count`（大面股≥10%家数）+ `floor_count`（跌停家数）+ `ladder_success_rate`（连板晋级率）+ `max_ladder_height`（连板最高高度）
  - [ ] R6.2 保留四档判定（冰点<30/普通<60/活跃<100/亢奋≥100，按 zt_count）+ **新增红期硬熔断覆盖**：当 `big_loss≥8 或 floor≥20` 时强制返回"红期"，覆盖四档判定
  - [ ] R6.3 三状态映射：绿 = 活跃+亢奋 / 黄 = 普通 / 红 = 冰点 或 红期硬熔断覆盖触发；仓位上限 绿 70-100% / 黄 30-50% / 红 0-20%
  - [ ] R6.4 因子从 T-1 盘后数据计算，`_market_phase()` 输出喂 T+1 盘前 PositionAdvisor
  - [ ] R6.5 兼容性：`_market_phase(zt_count)` 旧签名保留向后兼容（`first_board_filter.score_candidate` 现有调用不破坏）；新增 `_market_phase(zt_count, big_loss, floor, ladder_success, ladder_height)` 重载
- [ ] R7：在 `PositionAdvisor.advise_batch` 输出后加 `cap_by_market_phase(positions, phase)` 后处理函数
  - [ ] R7.1 **叠加代数（Oracle B4 修复）**：`final_cap = min(weather_cap, market_phase_cap, max_total_position)`
    - `weather_cap`：既有，暴风雨→0（禁止开仓），极端反弹→0.5，晴天/阴天→1.0
    - `market_phase_cap`：新增，绿→1.0（不放宽，只收紧），黄→0.5，红→0.2
    - `max_total_position`：既有 0.8 硬上限
  - [ ] R7.2 **绿档不放宽原则**：market_phase_cap 绿档=1.0（不顶掉 weather_cap 或 max_total_position），只收紧不放宽
  - [ ] R7.3 **互斥说明**：同一情绪现象（大面股爆炸≈暴风雨）可能同时触发 weather 熔断和 market_phase 熔断，取 min 不冲突
- [ ] R8：`_market_phase` 与 STI 时序用途显式区分（STI 是 T-1 盘后总结，`_market_phase` 是 T+1 盘前仓位闸因子）。**不引入新概念，不替代 STI**

### 3.3 纯信号输出 + 人工执行 checklist（Q2）

- [ ] R9：系统输出参数清单（不接券商 API，不下单）
  - [ ] R9.1 仓位参数：单笔委托金额 = 总仓位上限 × 个股仓位分配 ÷ 标的数；黄色期砍半
  - [ ] R9.2 触发价/竞价达标额：**属 S081 战法匹配 spec 范围**，本 spec 不输出（战法因子未就绪）。本 spec 只输出仓位参数 + 龙虎榜风控标记
- [ ] R10：仓位参数 + 龙虎榜风控标记 + 人工执行 checklist 推送飞书/前端弹窗（复用现有推送通道），checklist 标注"仓位参数参考值，非执行指令"

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/strategies/first_board_filter.py`（修改） | 扩展 `_market_phase()` 从单 zt_count 改为 4 因子输入 + 红期硬熔断覆盖（R6）。保留旧签名向后兼容 |
| `backend/strategies/position_advisor.py`（修改） | 加 `cap_by_market_phase(positions, phase)` 后处理（R7），叠加在既有 `advise_batch` + weather 熔断之上。**不修改既有 advise/advise_batch 签名** |
| `backend/dragon_tiger_seat_filter.py`（新增） | 龙虎榜席位三分级风控，复用 `seat_engine.compute_consensus_signal` + 扩展 `hot_money_seats.SeatRiskFactor`，新增黑名单硬剔除逻辑 |
| `backend/seat_engine/service.py`（修改） | 扩展 `compute_consensus_signal` 输出买一占比字段（供 R3 独食独大判定） |
| `backend/strategies/hot_money_seats.py`（修改） | 处置"绕过 em_get"问题（§5.3）—— 核实 datacenter 是否需 em_get 防护，或套上限流/重试 |
| `backend/routers/workflow.py`（修改） | 复用既有 `/api/workflow/pre-market` 端点，输出加 `market_phase_cap` + `risk_flags` 字段，**不新增 /api/workflow/p2/* 端点** |
| `config/seat_blacklist.yaml`（新增） | 黑名单席位名单 + 阈值可配 |
| `frontend/src/pages/Workflow.tsx`（修改） | pre-market 报告展示：仓位上限 + 龙虎榜风控标记 + 人工 checklist |
| `frontend/src/lib/api.ts`（修改） | pre-market 响应类型加 `market_phase_cap` + `risk_flags` 字段 |
| `docs/limitup-design.md`（修改） | 标注"策略逻辑教育展示定位"段落 supersede（§10 T6） |

---

## 5. 设计方案

### 5.1 两层后处理架构（不破坏 P1 漏斗 + 既有 pre_market 链路）

```
[既有 pre_market_workflow.py 链路，本 spec 不改]
候选池 → StrategyMatcher.match → PositionAdvisor.advise_batch(weather_state)
                ↓ position_suggestions
            ┌───────────────────────────────────┐
            │ 1. DragonTigerSeatFilter（新增）  │
            │    龙虎榜席位三分级                │
            │    输入：suggestions + T-1 龙虎榜 │
            │    复用：seat_engine + hot_money_seats │
            │    输出：硬剔除后标的 + risk_flags │
            └───────────────────────────────────┘
                ↓
            ┌───────────────────────────────────┐
            │ 2. cap_by_market_phase（新增后处理）│
            │    输入：标的 + T+1 _market_phase │
            │    叠加：min(weather_cap,          │
            │           market_phase_cap,       │
            │           max_total_position)     │
            │    输出：标的+仓位上限+risk_flags  │
            └───────────────────────────────────┘
                ↓
            推送飞书/弹窗 + 人工执行 checklist
```

> **串行链说明**：两层为串行依赖。回滚策略见 §9（整链禁用回退到既有 pre_market 输出，或单层禁用需同时禁用其下游）。

### 5.2 备选方案为何不选

- **A 接东财 OpenAPI 下单**：触 AC7 "不接券商不下单"工程底线
- **B PRD 三状态替代 STI**：STI 已与候选池/诊断卡/前端深度集成；且 STI 是盘后总结、`_market_phase` 是盘前开关，时序用途不同
- **C 新增 akshare 龙虎榜通道**：无视既有 seat_engine/hot_money_seats 同源 datacenter 通道，重复造轮子
- **D 引入新概念 MarketSwitch**：与既有 `_market_phase()` 职责重叠，扩展现有状态机比新增概念更复用

### 5.3 工程约束

- **AC7 防封底线不可绕过**：`hot_money_seats.py:75` 注释"绕过 em_get 熔断（datacenter API 可直接 urllib 调用）" —— 需核实 datacenter 域名（`datacenter-web.eastmoney.com`）是否真不需 em_get 防护。若 datacenter 限流策略与 push2ex 不同，在 spec 里显式声明理由；若相同，套上限流/重试
- **判断须可复现**（CLAUDE.md §1.2）：仓位闸阈值、龙虎榜风控阈值必须可由公开数据 + 既定规则复算
- **数据缺失透明**（S002 AC6）：龙虎榜取不到时标"未取得"+原因，不臆测席位结构；黑名单硬剔除不可执行（R5）
- **PRD 阈值探索性标注**（AGENTS.md 数据支撑优先）：PRD 三状态阈值（大面≤3/跌停≤5）与三分级阈值（15%/55%/≥3 席）是外部 PRD 拍定值，零数据支撑。spec 标注"探索性"，进 config 可配，约定回测调参门限（见 §6 AC8）

---

## 6. 验收标准

- [ ] AC1：`first_board_filter._market_phase()` 扩展为 4 因子输入（zt_count + big_loss + floor + ladder_success + ladder_height），保留冰点/普通/活跃/亢奋四档 + 红期硬熔断覆盖（big_loss≥8 或 floor≥20 时强制返回"红期"）。旧签名 `_market_phase(zt_count)` 向后兼容，`score_candidate` 现有调用不破坏
- [ ] AC2：`cap_by_market_phase(positions, phase)` 后处理叠加在 `PositionAdvisor.advise_batch` 输出之上，叠加代数 `final_cap = min(weather_cap, market_phase_cap, max_total_position)`。绿档 market_phase_cap=1.0（只收紧不放宽）。同一情绪现象同时触发两套熔断时取 min 不冲突
- [ ] AC3：龙虎榜席位三分级风控正确执行：黑名单占比>15% 硬剔除、独食独大仓位砍半、散户霸榜降权。复用 `seat_engine.compute_consensus_signal` + `hot_money_seats.SeatRiskFactor`，不新增 akshare 通道
- [ ] AC4：龙虎榜数据"未取得"时，黑名单硬剔除不可执行 + 标"席位风控数据未取得" + 显著警示，由用户决策（不默认放行也不默认拒绝）
- [ ] AC5：系统输出仓位参数 + 龙虎榜风控标记 + 人工执行 checklist，推送飞书/弹窗，**不接券商 API、不下单**。参数标注"参考值，非执行指令"
- [ ] AC6：`hot_money_seats.py` "绕过 em_get" 问题处置 —— 核实 datacenter 是否需 em_get 防护，在 spec/代码注释显式声明理由，或套上限流/重试
- [ ] AC7：所有研判/买卖时机/仓位参数输出挂轻量风险提醒「历史统计特征，市场有风险」（CLAUDE.md §1.1 弱合规）
- [ ] AC8：PRD 阈值标注"探索性"（外部 PRD 拍定，零数据支撑）。**验算口径**（Oracle H5 修复）：(a) 规则执行复算 —— 跑 `financial_rigor.py` 验证阈值判定逻辑正确；(b) 阈值近 60 交易日触发频率/空池率统计 —— 跑 `financial_rigor.py --thresholds prd_p2 --window 60d`，标注探索性、进 config 可配、约定回测调参门限（命中率<5% 或空池率>30% 触发调参）
- [ ] AC9：S002 AC10 "不输出方向结论词"在 P2 放宽到 CLAUDE.md §1.1 弱合规口径 —— 允许输出仓位参数/红期强制熔断/【拒绝介入】等量化方向参数，挂轻量风险提醒。**S002 P1 AC10 不继承到 P2**（§2.3 显式豁免）
- [ ] AC10：不涉及战法匹配扩展（拆 S081），不涉及参考价位（止损/止盈，属 S081）

---

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机属系统能力（2026-07-30 新口径，CLAUDE.md §1.1）；用户可见输出挂轻量风险提醒「历史统计特征，市场有风险」
- [ ] 判断可复现：涉及数据的跑 `~/tools/financial_rigor.py` / `report_audit.py` 验算通过，禁臆造/心算 —— **实现阶段验证**
- [x] 涨停四池/连板股榜个股属公开榜单客观事实（设计选择，可呈现 code/name）
- [x] 用户私有数据（持仓/研报/key）未进 git、未上传
- [x] 新增东财端点走 `em_get()` 限流；`hot_money_seats` datacenter 通道核实/套限流（AC6）
- [x] 不接券商、不下单（AC7 工程底线保留）
- [x] S002 参考价位隔离决议 + AC10 显式豁免（§2.3），引用 §1.1 + PositionAdvisor 既有先例
- [x] 输出参数标注"参考值，非执行指令"

---

## 8. 测试计划

- **单元测试**（`pytest -m "not live"`）：
  - `_market_phase()` 扩展：mock zt_count=40/big_loss=3/8/12 等场景，验证四档判定 + 红期硬熔断覆盖
  - `cap_by_market_phase`：mock PositionAdvisor 输出 + 三状态映射 + weather_cap，验证 `min()` 叠加代数
  - 向后兼容：`_market_phase(zt_count=40)` 旧签名调用返回"普通"，不报错
  - 龙虎榜席位三分级：mock 黑名单席位/独食独大/散户霸榜场景，验证硬剔除/砍半/降权
  - 数据缺失：mock 龙虎榜"未取得"，验证硬剔除不可执行 + 警示
- **联网测试**（`pytest -m live`）：
  - `seat_engine.compute_consensus_signal` 取数验证
  - `hot_money_seats` datacenter 通道限流验证（AC6）
- **手动验收**：
  - 取近 5 个交易日真实数据跑全链路，输出仓位参数 + 风控标记 + checklist
  - 跑 `financial_rigor.py --thresholds prd_p2 --window 60d` 对阈值复算 + 触发频率统计
  - 飞书推送格式确认

---

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| `_market_phase()` 扩展破坏 first_board_filter 评分链路 | 现有评分权重分层失效 | 保留四档判定 + 旧签名向后兼容（R6.5），红期硬熔断作为覆盖层不替换四档 |
| `cap_by_market_phase` 叠加与既有 weather 熔断冲突 | 双重熔断语义混乱 | 叠加代数 `min()` 取最严（R7.1），绿档不放宽（R7.2），互斥说明（R7.3） |
| `hot_money_seats` "绕过 em_get" 触 IP 封禁 | datacenter 通道被封 | 核实 datacenter 限流策略，套限流/重试（AC6） |
| PRD 阈值零数据支撑 | 阈值过严/过宽 | 标注"探索性"，进 config 可配，回测调参门限（AC8） |
| 龙虎榜数据"未取得"默认行为 | 默认放行=风控绕过，默认拒绝=误杀 | 硬剔除不可执行 + 警示 + 用户决策（R5/AC4） |

**回滚**：两层为**串行链**（龙虎榜风控 → 仓位闸），非独立模块。回滚策略：
1. **整链禁用**：回退到既有 pre_market_workflow 输出，不影响 S002 P1 已验收行为
2. **单层禁用**：需同时禁用其下游所有层
3. **`_market_phase()` 扩展回滚**：删除 4 因子重载 + 红期硬熔断覆盖，旧签名自动恢复原行为（R6.5）

---

## 10. 待定项（不阻断，实现阶段核实）

- T1：PRD 第五节"09:15-09:35 盘中动作"重写为人工执行 checklist 的具体措辞（Q2 依赖）—— 属 S081 战法匹配 spec 范围，本 spec 只输出仓位 + 风控 checklist
- T2：龙虎榜席位字段在 datacenter 数据中的实际字段名映射（实现阶段核实）
- T3：`_market_phase()` 扩展与 S074（market_phase 统一判定，草案未实现）的命名协调 —— S074 关注时段判定，本 spec 扩展关注情绪档位，概念正交
- T4：`limitup-design.md` "策略逻辑教育展示定位作废"的文档段落标注 supersede（不留"宣布作废但不修改"的活跃文档）
- T5：`PositionAdvisor.advise_batch` 输出结构核实 —— `cap_by_market_phase` 参数类型对齐（实现阶段核实 advise_batch 返回的是 list[PositionSuggestion] 还是其他结构）
