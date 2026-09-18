# Spec: S183 — 模拟盘累积胜率曲线（实时聚合 + Wilson CI 带 + 50% 基准）

> 状态：已实现（2026-09-11，T1-T8 全绿：后端 test_s183 7 测 + 前端 vitest 4 测 + tsc0 + multi_arm/s175/trend/s180 23 无回归；grill 6 视角审后 v2 落地）
> 作者：claude  日期：2026-09-11
> 关联：S173 TradeJournal 闭环 / S175 模拟盘自洽 / S025 老 TrendsChart（复用 echarts 模式）/ buy-what-when-buy-when-sell 三问·胜率跟踪 / long-term-validation-north-star / S181 trend 臂升级

## 1. 问题 / 目标

模拟盘跑起来后持续积累 trade_journal 记录，但 `journal_closed_loop` 只实时聚合一个当前胜率值，看不到**胜率随时间/样本累积的变化**。用户要：每周重算胜率 + 专业统计图曲线 + 可视化"样本提升趋于准确"的收敛过程。

一句话：给 S173 模拟盘加一条**带 95% Wilson CI + 50% 随机基准线 + 方向色**的累积胜率曲线，让长期验证 north-star 可视化（CI 收窄=更确信真实 edge，真实 edge 可能<50% 即负 edge，方向诚实暴露）。

## 2. 背景

- **老 TrendsChart**（`frontend/src/components/winrate/TrendsChart.tsx`，S025-B2）：echarts 折线 + `useECharts` hook，数据源老 `winrate_records`（prediction_ledger 打板预测）。模式可复用，数据源不同。
- **S173 TradeJournal**（`.vibe-research/trade_journal.db`）：多臂模拟盘，`engine/trade_journal.py:383 _wilson_ci` **已存在**（Wilson score interval），`:389 n=0 返 (0.0, 0.0)`（需改 `(0.0, 1.0)` 诚实暴露无数据）。`aggregate_by_arm:313` 用 `is_realized=1 AND is_dead_arm=0` 防证否臂污染。`_compute_arm_stats` 用 `n_decided`（net_pnl 非 None）做分母。
- **数据现状（grill 核实）**：trade_journal 42 行全 `net_pnl=NULL`（breakout 40 + floor 2），全 09-09 单日，0 条真实盈亏。scheduler trade_journal_daily 09-10 FAILED（旧代码 dispatcher 不认）。**曲线在空壳数据上=看起来正确但没用**——故需空态处理 + 数据前置条件。
- **DORMANT_ARMS stale**：`:67 DORMANT_ARMS=("limitup","trend")` + `:63 ARM_VERDICT["trend"]="mock_not_ready"`——但 S181（98555b6）已把 trend 进 cron paper_track 为实臂，这两处须先修。
- **统计前提**（§44 v1 外推越界教训）：大数定律收敛**要求分布稳定 + edge 方向一致**。gap 例子：60d t=-3.79 → 120d t=-5.28，样本增大方向不变更确信负。"准确"= 收敛到真实 edge，真实 edge 可能<50%。故曲线**必须加 50% 基准线 + 方向色**（低于 50% 红=负 edge），光一条曲线无 CI 无基准会误导（看着"在变好"可能只是 CI 还没收窄 / retroactive settlement 人口变化）。

## 3. 需求清单

- [ ] R1：GET `/api/journal/winrate-trends` 实时聚合（按周分桶，exit_date 做 cutoff）——查 `is_realized=1 AND is_dead_arm=0 AND net_pnl IS NOT NULL` 的 trades，按 `exit_date` 周分桶算累积胜率 + Wilson CI。不建表/不建 executor/不 seed cron（YAGNI：42 行聚合 <1ms）
- [ ] R2：复用 `engine/trade_journal.py:383 _wilson_ci`，改 `:389 if total<=0: return (0.0, 1.0)`（n=0 返宽带诚实暴露无数据，非 (0,0) 误导"精确 0%"）。现有调用方 `_compute_arm_stats:454` 有 `n_decided>0` guard 保护，改 (0,1) 不影响现有逻辑
- [ ] R3：前端 `JournalWinRateCurve` 组件——echarts **stack 技巧画 CI band**（ci_low 透明线 + ci_high-ci_low 差值 stack:'ci' 半透明面积 + win_rate 独立实线）+ **50% 随机基准 markLine**（虚线 + 标签）+ **方向色**（<50% 红、≥50% 绿填充）
- [ ] R4：双轴诚实标签——`n_total<30 或 n_days<60 → insufficient_sample` / `n≥30 且 n_days<60 → underpowered` / `n≥30 且 n_days≥60 → robust`。**删"与 §44 v2 口径一致"声明**（口径不同：本表按交易笔数 n + 交易日数 n_days 做 Wilson CI 收敛标签，§44v2 按 days_robust 做 verdict 冻结；robust 副标"仅统计意义，不触发 sizing 调整"，与 lift_to_multiplier 脱节——R3 enforce 已搁置不建反馈路径）
- [ ] R5：实现前先修 `DORMANT_ARMS` 移除 `"trend"` + `ARM_VERDICT["trend"]` 改 `"exploratory"`（S181 已升级 trend 为实臂，这两处 stale）
- [ ] R6：空态处理——trade_journal 无真实 net_pnl 记录时（当前 42 行全 NULL）显 exploratory 占位文字"模拟盘积累中（需 ≥30 条真实成交才有统计意义）"+ 当前 n 计数，不画空线
- [ ] R7：（降级到 §9 后续可选）分臂曲线 toggle——当前 trend=0、floor=2、breakout 40 NULL，无分臂数据。等单臂 n≥30 再加

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/engine/trade_journal.py` | R2 改 `_wilson_ci:389` n=0 返 (0,1) + R5 DORMANT_ARMS 移 trend / ARM_VERDICT 改 + 加 `query_winrate_trends()` 方法（实时聚合按周分桶） |
| `backend/routers/journal.py` | R1 加 `GET /api/journal/winrate-trends` 端点（调 `query_winrate_trends` 返时序） |
| `frontend/src/lib/journal-contract.ts` | 加 `JournalWinRateTrendPoint` type（仿 ArmAggregate 范式） |
| `frontend/src/lib/api.ts` | 加 `api.journalWinRateTrends()` 方法 |
| `frontend/src/lib/query/journal.ts` | 加 `useJournalWinRateTrends` hook（仿 useClosedLoop，queryKey: ['journal','winrate-trends']） |
| `frontend/src/components/journal/JournalWinRateCurve.tsx` | 新组件（echarts stack CI band + 50% markLine + 方向色 + 空态 + Disclaimer compact） |
| `frontend/src/pages/Journal.tsx` | 挂 `JournalWinRateCurve`（closedloop tab 内，JournalLedger 上方——不在 JournalLedger 内部防被 early return 劫持） |

~7 文件（原 v1 ~10 文件，砍落盘表/executor/cron/migration 省 3+ 文件）。

## 5. 设计方案

### 5.1 实时聚合 vs 落盘 snapshot（grill P0 修订）

**选实时聚合**（非落盘 snapshot）。理由：
- 42 行聚合 <1ms，建 winrate_snapshots 表 + migration + executor + cron seed + dispatch = 6+ 文件基建服务 42 行小表，YAGNI 违反
- 实时聚合天然避免：跨 DB 路径/UNIQUE 约束/0-trade 周写不写/历史回填/retroactive settlement stale/S088"不读结果 cache"矛盾
- 落盘 snapshot 是"结果 cache"，与 S088 重算范式冲突；实时聚合每次按 exit_date<=week_end 重算，与 `aggregate_by_arm` + S088 一致
- 等 trade_journal >10万行再考虑落盘（YAGNI 阈值）

### 5.2 Wilson CI 复用（grill P0 修订）

复用 `trade_journal.py:383 _wilson_ci`（已存在，公式正确 scipy 验证）。改 `:389`：
```python
if total <= 0:
    return (0.0, 1.0)  # n=0 返宽带诚实暴露无数据（非 (0,0) 误导"精确 0%"）
```
实现注意：n_total=0 是公式前硬 guard，`if(n===0) return {ci_low:0, ci_high:1, label:'insufficient_sample'}`，不进入公式计算（0/0 未定义）。

### 5.3 echarts CI band（grill P0 修订——stack 技巧）

echarts line series 的 areaStyle 从线填到轴基线，**不能** `[ci_low, ci_high]` 之间填。用 stack 技巧（零额外依赖，不改 useECharts 公共 hook）：
```js
series: [
  { type:'line', data: ci_low, stack:'ci', areaStyle:{color:'transparent'}, lineStyle:{opacity:0} },  // 透明垫底
  { type:'line', data: ci_high.map((h,i)=>h - ci_low[i]), stack:'ci', areaStyle:{color:'rgba(251,146,60,0.15)'}, lineStyle:{opacity:0} },  // 差值半透明带
  { type:'line', data: win_rate, itemStyle:{color:'#fb923c'} },  // 胜率实线
],
markLine: { data:[{ yAxis:50, label:'随机基准 50%' }], lineStyle:{type:'dashed'} },
```
方向色：win_rate<50% 的区段红色 areaStyle（负 edge），≥50% 绿色。

### 5.4 双轴诚实标签（grill P0 修订）

| 条件 | label | 线型 |
|---|---|---|
| n_total<30 或 n_days<60 | insufficient_sample | 虚线灰 |
| n≥30 且 n_days<60 | underpowered | 点划线黄 |
| n≥30 且 n_days≥60 | robust | 实线 |

robust 副标"仅统计意义，不触发 sizing 调整"（与 lift_to_multiplier 脱节，R3 enforce 搁置）。

**口径声明**（删"与 §44 v2 一致"）：阈值数值 60 沿用，但口径不同——本表按交易笔数 n + 交易日数 n_days（Wilson CI 收敛标签），§44v2 按 days_robust（verdict run 时冻结）。两者不混用。

### 5.5 数据前置条件 + 空态（grill P0 修订）

当前 trade_journal 42 行全 net_pnl=NULL（空壳）。曲线组件：
- n_decided=0 时显占位文字"模拟盘积累中（需 ≥30 条真实成交才有统计意义，当前 0 条已结算）+ 当前 n 计数"，不画空线
- 优先修 S175 P0-1 scheduler 点火（重启后端让 trade_journal_daily 连续跑，累积真实 net_pnl）
- UI 先行：先建曲线组件 + 空态 + API（返空），等数据来了自动显示（符合 [[ui-first-implementation-order]]）

### 5.6 分母口径（grill P2 修订）

分母 = `n_decided`（`net_pnl IS NOT NULL AND net_pnl != 0 AND exit_reason != 'unbuyable'`），与 `_compute_arm_stats` 一致。排除 unbuyable（买不到）+ breakeven（net_pnl=0）+ NULL（未结算）。查询加 `is_dead_arm=0` 防证否臂（gap）污染总览。

## 6. 验收标准

- [ ] A1：`_wilson_ci:389` n=0 返 (0.0, 1.0)，现有 `_compute_arm_stats` 测试仍绿（guard 保护）
- [ ] A2：`DORMANT_ARMS` 移除 trend + `ARM_VERDICT["trend"]="exploratory"`（S181 一致）
- [ ] A3：GET `/api/journal/winrate-trends` 返 `[{week_start, win_rate, ci_low, ci_high, n_decided, n_total, n_days, label}]`，空表返 `[]` 非 500
- [ ] A4：前端曲线渲染 win_rate 线 + CI band（stack 技巧）+ **50% markLine** + **方向色** + 空态占位 + Disclaimer compact
- [ ] A5：Wilson CI 单测——n=0 返 [0,1]+insufficient_sample / n=1/10/100 vs `scipy.stats` 或查表值
- [ ] A6：实时聚合单测——mock trade_journal records，验证按周分桶 + 累积胜率 + CI + 双轴标签（n=29/30 + n_days=59/60 边界）
- [ ] A7：n<30 或 n_days<60 → insufficient_sample；n≥30 且 n_days<60 → underpowered；n≥30 且 n_days≥60 → robust（边界 n=29/30/59/60 + n_days=59/60）
- [ ] A8：tsc0 + 全量测试无回归（test_s173 + test_s175 + test_s181 不破）

## 7. 合规与工程底线自查

- [x] 弱合规：胜率是历史统计特征，曲线区挂 Disclaimer compact 轻量提醒
- [x] 不臆造：Wilson CI 公式有数学依据（Wilson 1927），复用已存在 `_wilson_ci`，单测验证边界
- [x] 私有数据：trade_journal 在 `.vibe-research/`（VR_DATA_DIR），不进 git
- [x] 不涉 em_get：数据源是内部 trade_journal 表
- [x] 工程底线：实时聚合走重算范式（S088，不读结果 cache）；诚实标注方向（50% 基准 + 方向色，§44 外推禁令 UI 落地）
- [x] DRY：复用 `_wilson_ci` 不新建第四个 Wilson 函数
- [x] YAGNI：不建 winrate_snapshots 表/executor/cron（42 行实时聚合 <1ms）；R7 分臂降级 §9

## 8. 测试计划

- **Wilson CI 单测**（扩 `test_trade_journal.py`）：n=0 返 (0,1) / n=1/10/100 vs scipy.stats.wilson 边界
- **实时聚合单测**（`test_s183_winrate_trends.py`）：mock trade_journal 5 records（含 unbuyable/dead_arm/NULL/breakeven），验证按周分桶 + 累积胜率 + CI + 双轴标签 + is_dead_arm 过滤 + n_decided 分母
- **API 单测**（TestClient）：空表返 []、有数据返时序、is_dead_arm 过滤
- **前端组件测试**（`JournalWinRateCurve.test.tsx`）：渲染 win_rate 线 + CI band（stack）+ 50% markLine + 方向色 + 空态 + 加载态
- **集成**：重启后端 → scheduler trade_journal_daily 连续跑 → 攒真实 net_pnl → API 返时序 → 前端渲染（手动冒烟，依赖 P0-1 点火）

## 9. 后续可选（非本 spec，显式标触发条件）

- **分臂曲线 toggle**（R7 降级）：需各臂攒够 n≥30 真实 net_pnl（当前 trend=0/floor=2/breakout 40 NULL）。至少数周后
- **Sharpe / drawdown 曲线**：`aggregate_by_arm` 已算，此为可视化扩展非新计算
- ~~regime 分层胜率~~（grill 砍：依赖不存在的 regime 检测模块，speculative）
- ~~§44 v2 联动自动调 lift_to_multiplier~~（grill 砍：死联动，R3 enforce 已搁置，DIMENSION_LIFT_REGISTRY 静态 frozen 不回写）
