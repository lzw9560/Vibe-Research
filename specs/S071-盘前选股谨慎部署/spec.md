# S071 · 盘前选股谨慎部署（breakout 弱信号 + 风控）

> 状态：已实现（2026-08-16，commit 9ee3bd1 + 9284859）。**本 spec 为事后补写**（2026-08-17，grill 指出 §0 SDD 违规——代码先于规范，现补齐记录）。
> 定位：**待确认**（见 §6 定位撕裂 A/B/C，未投真金）。

## 1. 问题/背景

S066 Phase 0e forward_test 证明涨停五因子（total_score）lift=0.98<1，无 §44 validated edge。
§44 grill reframe + S070 kline TA 验证后，breakout_20d 是唯一"弱正"信号
（day-cluster 1.722x<2x + PnL+0.486%，robust>1 但 <2x）。
在无 validated edge 的前提下，S071 谨慎部署 breakout 作为盘前选股**观察/风控演练**工具，不宣称 edge。

## 2. 目标/需求

- R1：盘前对历史涨停股（1121 universe）按 breakout_20d 排序，出 top-N 候选。
- R2：每候选附风控参考价（止损/止盈/仓位×日历/max 持仓/max 持有日）。
- R3：honest_label 前置——标"§44<2x 弱信号，非 validated edge"。
- R4：edge 主来自风控非对称（小仓+紧止损+1:2 R:R+短持），非信号本身。
- R5：不投真金（前向测试期间）。

## 3. 信号定义

```
breakout_20d = T-1 close / max(high, 前 20 日)
score ∈ (0, 1]；score >= 0.95 → binary=1（硬突破）
universe = baostock_kline_cache（1121 涨停史股，本地，非东财不被限流）
数据源：baostock qfq 日K（公开可复算）
```

## 4. 风控参数

| 参数 | 值 | 依据 |
|---|---|---|
| 单票仓位 | 3% × 日历因子 | 弱信号小仓 |
| max_positions | 3 | 集中度上限 |
| 止损 | -4%（相对入场参考价） | 紧止损 |
| 止盈 | +8% | R:R≈1:2 非对称 |
| max_hold_days | 3 | breakout 衰减快 |

日历因子调仓：复用 S066 §6 `calendar_factor`（周五×0.7/节前×0.5/末日×0.3/周四×1.0）。

## 5. 受影响文件（已实现）

- backend/strategies/premarket_selection.py（信号 + 风控层）
- backend/routers/premarket.py（GET /api/strategy/premarket-selection）
- backend/app.py（router 注册，+2 行）
- backend/tools/refresh_kline_cache.py（kline 日更，手动跑；cron 未接）
- frontend/src/lib/query/premarket.ts
- frontend/src/pages/limitup/PremarketSelection.tsx
- frontend/src/router.tsx + components/layout/navigation.ts

## 6. 待决项（定位撕裂，grill 2026-08-17）

`honest_label` / `disclaimer` 说"弱信号探索，不投真金"，但实现给每候选止损价/止盈价/仓位%/max 持仓——**执行参数 vs 探索标签矛盾**。三选一：

- **(A) 探索工具**：砍执行参数，只留 breakout 分数 + 候选 + 弱标签。
- **(B) 可执行选股**：§44<2x 不该投真金，须先补 S066 §15 组合风控 + §16 成本/熔断 + 60 天复验拿 validated edge 再上。
- **(C) 其他**。

**未决。当前实现横跨 A/B（标签说 A，参数做 B）。决策前不投真金。**

## 7. 与 S066 关系

S071 ≠ S066 的实现。S066 原信号（total_score）§44 证伪后的**替代路径**，
未走 S066 策略注册表 / 9 战法 / 漏斗架构 / 组合风控 §15 / 执行成本 §16 / 前端 L0-L3。
详见 grill-reframe-final-verdict memory + S066 tasks.md 第 7 行"HOLD 新复杂度至 alpha 验证"。

**纪律冲突**：S066 tasks.md 第 7 行明令 HOLD 新层至 alpha 验证，
S071 在无 alpha 下部署——属 grill 确认的流程偏离（本 spec 补写即对其透明化，不消除）。

## 8. 验收标准

- [x] endpoint /api/strategy/premarket-selection 注册（OpenAPI 确认）
- [x] honest_label 前置（§44<2x 弱信号标注）
- [x] 风控参数输出（止损/止盈/仓位×日历）
- [x] 前端候选表 + 风控卡 + honest banner
- [x] tsc 0 错 + pytest 1548 passed
- [ ] 定位撕裂 resolve（§6，未决）
- [ ] kline 日更 cron 接线（手动刷新在，cron 未接）
- [ ] 60 天复验（~2026-09-20，与 S066 task 116 同点）

## 9. 合规自查（弱合规）

- 工程底线·可复现：breakout 基于 baostock 公开 qfq K 线，公式可复算 ✓（禁止心算/臆造）
- 工程底线·私有数据隔离：kline cache 在 .vibe-research/（VR_DATA_DIR），不进 git ✓
- 工程底线·防封：baostock 非 em_get，不被 IP 限流 ✓
- honest 标注：§44<2x 弱信号前置 ✓
- 待决：定位撕裂未 resolve（§6），前向测试期间不投真金 ✓
