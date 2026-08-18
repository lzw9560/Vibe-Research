# Spec: S081 — 打板 P2 战法匹配扩展（backlog，等 S070 R7）

> 状态：backlog（等 S070 R7 派生字段就绪）
> 作者：Claude  日期：2026-08-18
> 关联：`CLAUDE.md` §1.1、`specs/S002-打板工作流重构/spec.md`（P1 候选池漏斗）、**`specs/S070-intraday采集管道/`（数据层先行，R7 派生 last_lock_time/broken_duration_min/max_drop_pct）**、`specs/S079-打板P2战法与仓位闸/`（仓位闸+龙虎榜，不依赖本 spec）、`backend/strategies/strategy_matcher.py`、`backend/limitup_strategy.py`、原 PRD `/Users/lizhiwei/Downloads/Quantitative_Limit_Up_Trading_System_Implementation_Guide.md`
>
> **三拆背景**：原 S079 含战法匹配+仓位闸+龙虎榜三模块。Oracle 审查发现 PRD 2 战法核心因子（broken_duration_min/max_drop_pct/last_lock_time）在 repo 零匹配，需 S070 R7 派生字段就绪 —— 战法匹配拆本 spec 等 S070。S079（仓位闸+龙虎榜）不依赖本 spec，已先行。

---

## 1. 问题 / 目标

S002 P1 已落地候选池漏斗 + 诊断卡。`pre_market_workflow.py` 已有完整链：候选池 → `StrategyMatcher.match` → `PositionAdvisor.advise_batch`。`limitup_strategy.STRATEGY_REGISTRY` 已定义 8+1 战法，`match_strategies` 已实现匹配逻辑。

**缺口**：PRD 2 战法（弱转强接力 + 形态反包）的硬阈值因子（`broken_duration_min≥20` / `max_drop_pct≥5%` / `last_lock_time≥14:40` / `shadow_length_pct≥4%` 等）不在现有 registry，且这些因子是分时级指标，需 S070 R7 派生计算就绪才能落地。

**目标**：扩展 `StrategyMatcher.match()` 加 PRD 2 战法硬阈值匹配分支，复用 S070 R7 派生的 `last_lock_time` / `broken_duration_min` / `max_drop_pct` 字段 + 既有涨停池字段（`fbt` / `zbc` / K线数据）。一句话：在既有战法匹配引擎上加 2 个新战法硬阈值分支，因子来自 S070 派生层。

---

## 2. 背景

### 2.1 既有管线盘点

| 文件:行 | 既有能力 | 本 spec 关系 |
|---|---|---|
| `strategies/strategy_matcher.py:22` | `StrategyMatcher` 包装 `match_strategies`，已被 `pre_market_workflow.py:96,124` 消费 | **扩展 match()**，加 PRD 2 战法硬阈值匹配分支 |
| `limitup_strategy.py:497-631` | `STRATEGY_REGISTRY` 8+1 战法定义，`match_strategies:656` 实现匹配 | **新增 2 个战法注册项**（弱转强接力 + 形态反包），不修改现有 9 个 |
| `pre_market_workflow.py:124` | 调 `StrategyMatcher.match()` 匹配候选池 | **不改调用方**，match() 扩展后自动覆盖 |
| `first_board_filter.py:17-22` | 涨停池字段映射：`fbt`→首封时间 / `zbc`→炸板次数 / `lbc`→连板数 | **复用**，PRD 战法因子部分从这些字段派生 |

### 2.2 PRD 2 战法因子数据源映射

| PRD 因子 | 数据源 | 状态 |
|---|---|---|
| `limit_up_days`（连板天数）| `lbc` 字段（涨停池已有） | ✅ 已有 |
| `broken_duration_min`（炸板累计时长）| S070 R7.2 派生（从 `open_count>0` 时段累加） | ⏳ 等 S070 R7 |
| `max_drop_pct`（炸板后回撤幅度）| S070 R7.3 派生（`(涨停价 - low_price) / 涨停价 * 100`，依赖 R6 low_price） | ⏳ 等 S070 R6+R7 |
| `last_lock_time`（最后封死时刻）| S070 R7.1 派生（从 `open_count` 最后一次=0 的 ts 推算） | ⏳ 等 S070 R7 |
| `vol_ratio_1d`（换手倍数）| 涨停池 `hs`（换手率）+ 前日数据 | ✅ 已有（需取前日对比）|
| `close_pct`（收盘涨幅）| 涨停池 `zdp` 字段 | ✅ 已有 |
| `max_high_pct`（最高涨幅）| K 线数据 `astock.kline()` | ✅ 已有 |
| `shadow_length_pct`（上影线长度）| K 线数据（最高价/收盘价 - 1） | ✅ 已有（需 K 线取数）|
| `volume_1d` / `volume_2d`（成交量对比）| 涨停池 `amount` + 前日数据 | ✅ 已有（需取前日对比）|
| `ma_5_status`（5日均线状态）| K 线数据 `astock.kline()` + 均线计算 | ✅ 已有（需计算）|

**关键依赖**：`broken_duration_min` / `max_drop_pct` / `last_lock_time` 三个因子等 S070 R7 派生层就绪。S070 R7 未落地前，本 spec 标"数据层未就绪"不进实现。

### 2.3 与原 PRD 的逻辑冲突处置

| # | 冲突点 | 原 PRD 立场 | repo 现状 | 处置 |
|---|---|---|---|---|
| 1 | 合规边界 | 直接给买卖时机 | CLAUDE.md §1.1 弱合规 | **遵循 §1.1**：战法匹配输出命中/置信度 + 触发价/竞价达标额参数，挂轻量风险提醒 |
| 2 | 战法集合 | 2 战法替换 8 战法 | STRATEGY_REGISTRY 8+1 战法已实现 | **新增 2 个注册项**，不替换现有 9 个。PRD 2 战法与既有 registry 命名体系对齐（实现阶段核实既有 break_reseal/reverse_package 是否语义重叠，重叠则合并而非新增）|
| 3 | 触发价输出 | 次日触发价 = 昨日涨停价/最高价+0.01 | S002 §2/§9 参考价位隔离决议 | **显式豁免**（S079 §2.3 已豁免，本 spec 继承）：引用 §1.1 + PositionAdvisor 既有 entry_price_range 先例。标注"参考值，非执行指令" |

### 2.4 历史 spec 关系

- **S002（P1 已实现）**：本 spec 是其 P2 战法匹配扩展，复用 R1/R2/R3 漏斗输出 + pre_market_workflow 既有链路。**S002 不改**。
- **S070（先行，数据层）**：R6 加 low_price 字段 + R7 派生 last_lock_time/broken_duration_min/max_drop_pct。**本 spec 依赖 S070 R7 就绪**。
- **S079（先行，仓位闸+龙虎榜）**：仓位闸 + 龙虎榜黑名单层，不依赖本 spec。本 spec 战法匹配输出喂 S079 的仓位闸（战法乘数）。
- **limitup-design.md**：8 战法定义历史背景，本 spec 新增 2 战法对齐既有 registry 命名体系，不直接引用 limitup-design 的战法口径。

---

## 3. 需求清单

### 3.1 弱转强接力战法（PRD §2.1）

- [ ] R1：在 `STRATEGY_REGISTRY` 新增"弱转强接力"战法注册项
  - [ ] R1.1 硬阈值因子：`limit_up_days≥1` + `broken_duration_min≥20` + `max_drop_pct≥5%` + `last_lock_time≥14:40` + `vol_ratio_1d∈[1.8,3.0]`
  - [ ] R1.2 因子取数：`limit_up_days` 从 `lbc`；`broken_duration_min`/`max_drop_pct`/`last_lock_time` 从 S070 R7 派生；`vol_ratio_1d` 从 `hs` + 前日对比
  - [ ] R1.3 置信度打分：5 因子全命中=high，4 命中=medium，≤3 命中=low（不输出）
- [ ] R2：扩展 `StrategyMatcher.match()` 加该战法硬阈值匹配分支
  - [ ] R2.1 不修改现有 `match_strategies` 逻辑，新增 `match_prd_strategies()` 方法或在 match() 加分支
  - [ ] R2.2 S070 R7 未就绪时，该战法标"数据层未就绪"跳过匹配（不报错，标 data_status）

### 3.2 形态反包战法（PRD §2.2）

- [ ] R3：在 `STRATEGY_REGISTRY` 新增"形态反包"战法注册项
  - [ ] R3.1 硬阈值因子：`close_pct<9.5%` + `max_high_pct≥7%` + `shadow_length_pct≥4%` + `volume_1d>volume_2d*1.2` + `ma_5_status=="Upward"`
  - [ ] R3.2 因子取数：`close_pct` 从 `zdp`；`max_high_pct`/`shadow_length_pct` 从 K 线 `astock.kline()`；`volume_1d`/`volume_2d` 从 `amount` + 前日对比；`ma_5_status` 从 K 线 + 均线计算
  - [ ] R3.3 置信度打分：5 因子全命中=high，4 命中=medium，≤3 命中=low
- [ ] R4：扩展 `StrategyMatcher.match()` 加该战法硬阈值匹配分支（同 R2 结构）

### 3.3 信号输出（Q2 纯信号生成）

- [ ] R5：战法匹配命中后输出参数清单（不接券商 API，不下单）
  - [ ] R5.1 弱转强接力：次日触发价 = 昨日涨停价；竞价达标额（1进2≥1500万 / 2进3+≥3000万 或昨日成交额10%）；配合价格区间 +2%~+5%
  - [ ] R5.2 形态反包：次日触发价 = 昨日K线最高价+0.01元；盘中量比≥3.5 + 实时换手达昨日60%
  - [ ] R5.3 触发价精度：复用 `limitup_strategy._round_to_tick_size` / `_validate_limit_up_price`（既有，line 29-52）处理涨跌停精度
  - [ ] R5.4 参数标注"参考值，非执行指令"
- [ ] R6：参数 + 人工执行 checklist 推送飞书/前端弹窗（复用现有推送通道），checklist 内容含"09:15-09:20 看竞价大单 / 09:24:30 算量校验 / 09:30:03 看分时不下破零轴 + L2 红字大单"等人工动作

---

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/limitup_strategy.py`（修改） | STRATEGY_REGISTRY 新增 2 个战法注册项（弱转强接力 + 形态反包），不修改现有 9 个 |
| `backend/strategies/strategy_matcher.py`（修改） | 扩展 match() 加 PRD 2 战法硬阈值匹配分支，或新增 match_prd_strategies() 方法 |
| `backend/pre_market_workflow.py`（修改） | match() 扩展后自动覆盖，不改调用方。输出加 PRD 战法触发价/竞价达标额参数 |
| `backend/routers/workflow.py`（修改） | /api/workflow/pre-market 响应加 PRD 战法参数字段 |
| `frontend/src/pages/Workflow.tsx`（修改） | pre-market 报告展示：PRD 战法命中 + 触发价 + 竞价达标额 + 人工 checklist |
| `frontend/src/lib/api.ts`（修改） | pre-market 响应类型加 PRD 战法参数字段 |

---

## 5. 设计方案

### 5.1 扩展现有引擎（不新建）

```
[既有 pre_market_workflow.py 链路]
候选池 → StrategyMatcher.match()
         ├── match_strategies()（既有 9 战法，不改）
         └── match_prd_strategies()（新增，PRD 2 战法硬阈值）
                ├── 弱转强接力：5 因子硬阈值（S070 R7 派生 + lbc + hs）
                └── 形态反包：5 因子硬阈值（zdp + kline + amount + ma5）
         ↓ 合并输出 StrategySignal 列表
    → PositionAdvisor.advise_batch(weather_state)
    → [S079] cap_by_market_phase + DragonTigerSeatFilter
    → 推送飞书/弹窗 + 人工执行 checklist
```

### 5.2 S070 R7 依赖门禁

- S070 R7（last_lock_time/broken_duration_min/max_drop_pct 派生）未就绪时：
  - 弱转强接力战法标"数据层未就绪"跳过匹配（不报错，标 `data_status="missing_s070_r7"`）
  - 形态反包战法不依赖 S070 R7（因子来自 K 线 + 涨停池字段），可先行实现
- S070 R7 就绪后：通知本 spec 可进实现，弱转强接力战法激活

### 5.3 备选方案为何不选

- **A 替换 STRATEGY_REGISTRY 现有 9 战法**：破坏既有 match_strategies 逻辑 + pre_market_workflow 消费链
- **B 新建独立战法匹配引擎**：与既有 StrategyMatcher 重复，pre_market_workflow 要改两处调用
- **C 用代理字段降级（fbt/zbc 近似炸板时长）**：精度不足，PRD 硬阈值（≥20min）用炸板次数近似语义偏差大

### 5.4 工程约束

- **判断须可复现**（CLAUDE.md §1.2）：战法阈值必须可由公开数据 + 既定规则复算，跑 `financial_rigor.py` 验算
- **数据缺失透明**（S002 AC6）：S070 R7 未就绪时标"数据层未就绪"，不臆造因子值
- **PRD 阈值探索性标注**（AGENTS.md 数据支撑优先）：PRD 硬阈值（≥20min / ≥5% / ≥14:40 等）是外部 PRD 拍定值，零数据支撑。spec 标注"探索性"，进 config 可配，约定回测调参门限
- **触发价精度**：复用 `limitup_strategy._round_to_tick_size` / `_validate_limit_up_price`（既有）

---

## 6. 验收标准

- [ ] AC1：`STRATEGY_REGISTRY` 新增"弱转强接力"+"形态反包"2 个战法注册项，不破坏现有 9 个。命名与既有 registry 体系对齐（实现阶段核实 break_reseal/reverse_package 语义重叠则合并）
- [ ] AC2：`StrategyMatcher.match()` 扩展后对候选池标的并行匹配 PRD 2 战法，输出命中/未命中/置信度，阈值与 PRD §2.1/§2.2 完全一致
- [ ] AC3：弱转强接力战法因子（broken_duration_min/max_drop_pct/last_lock_time）从 S070 R7 派生取数。S070 R7 未就绪时标"数据层未就绪"跳过匹配（不报错，标 data_status）
- [ ] AC4：形态反包战法因子（close_pct/max_high_pct/shadow_length_pct/volume/ma_5）从涨停池 + K 线取数，不依赖 S070 R7
- [ ] AC5：战法匹配命中后输出触发价/竞价达标额参数，复用 `_round_to_tick_size`/`_validate_limit_up_price` 处理精度。参数标注"参考值，非执行指令"
- [ ] AC6：系统输出参数 + 人工执行 checklist，推送飞书/弹窗，**不接券商 API、不下单**
- [ ] AC7：所有研判/买卖时机输出挂轻量风险提醒「历史统计特征，市场有风险」（CLAUDE.md §1.1 弱合规）
- [ ] AC8：PRD 阈值标注"探索性"（外部 PRD 拍定，零数据支撑）。**验算口径**：(a) 规则执行复算 —— 跑 `financial_rigor.py` 验证阈值判定逻辑正确；(b) 阈值近 60 交易日命中率/空池率统计 —— 跑 `financial_rigor.py --thresholds prd_p2_strategies --window 60d`，标注探索性、进 config 可配、约定回测调参门限
- [ ] AC9：S002 AC10 "不输出方向结论词"在 P2 放宽到 §1.1 弱合规口径（S079 §2.3 已豁免，本 spec 继承）

---

## 7. 合规与工程底线自查（逐条确认）

- [x] 研判/推荐/买卖时机属系统能力（2026-07-30 新口径，CLAUDE.md §1.1）；用户可见输出挂轻量风险提醒
- [ ] 判断可复现：涉及数据的跑 `~/tools/financial_rigor.py` / `report_audit.py` 验算通过，禁臆造/心算 —— **实现阶段验证**
- [x] 涨停四池/连板股榜个股属公开榜单客观事实
- [x] 用户私有数据未进 git、未上传
- [x] 新增东财端点走 `em_get()` 限流；K 线取数复用 astock 既有路径
- [x] 不接券商、不下单（AC7 工程底线保留）
- [x] S002 参考价位隔离决议 + AC10 显式豁免（S079 §2.3 已豁免，本 spec 继承）
- [x] 输出参数标注"参考值，非执行指令"

---

## 8. 测试计划

- **单元测试**（`pytest -m "not live"`）：
  - 弱转强接力战法：mock 满足/不满足 PRD 5 因子阈值的标的，验证命中/未命中/置信度
  - 形态反包战法：mock 满足/不满足 PRD 5 因子阈值的标的，验证命中/未命中/置信度
  - S070 R7 未就绪门禁：mock R7 派生字段缺失，验证弱转强接力标"数据层未就绪"跳过
  - 触发价精度：复用 `_round_to_tick_size` 测试用例
- **联网测试**（`pytest -m live`）：
  - S070 R7 派生字段实际取数验证
  - K 线取数（astock.kline）+ 均线计算验证
- **手动验收**：
  - 取近 5 个交易日真实数据跑全链路，输出战法命中 + 触发价 + checklist
  - 跑 `financial_rigor.py --thresholds prd_p2_strategies --window 60d` 对阈值复算 + 命中率统计

---

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| S070 R7 派生字段粒度限制（60s） | broken_duration_min 可能漏短时炸板 | 标注"60s 粒度近似"，PRD 阈值≥20min 容忍度高 |
| PRD 2 战法与既有 registry 语义重叠 | 重复注册 | 实现阶段核实 break_reseal/reverse_package，重叠则合并 |
| PRD 硬阈值零数据支撑 | 阈值过严/过宽 | 标注"探索性"，进 config 可配，回测调参门限（AC8） |
| S070 R7 长期未就绪 | 本 spec 长期 backlog | 形态反包战法不依赖 S070 R7，可先行实现 |

**回滚**：本 spec 扩展 `StrategyMatcher.match()` + `STRATEGY_REGISTRY` 新增 2 项。回滚策略：
1. 删除 2 个战法注册项 + match_prd_strategies() 方法，match() 恢复原行为
2. S070 R7 派生字段保留（属 S070 范围，不回滚）

---

## 10. 待定项（不阻断，实现阶段核实）

- T1：PRD 2 战法与既有 STRATEGY_REGISTRY 命名/语义对齐 —— 实现阶段核实 break_reseal（炸板回封）与"弱转强接力"、reverse_package（反包）与"形态反包"是否重叠，重叠则合并而非新增
- T2：PRD 第五节"09:15-09:35 盘中动作"重写为人工执行 checklist 的具体措辞（Q2 依赖）
- T3：竞价达标额（1进2≥1500万 / 2进3+≥3000万）的"昨日全天成交额10%"阈值 —— 实现阶段核实从哪个字段取昨日成交额
- T4：S070 R7 就绪通知机制 —— S070 R7 落地后如何通知本 spec 可进实现（spec 状态从 backlog → 草案）
