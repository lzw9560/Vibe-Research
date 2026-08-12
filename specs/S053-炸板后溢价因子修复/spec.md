# Spec: S053 — 炸板后溢价因子修复 + match 条件解耦

> 状态：已实现（2026-08-12，commit 907b5d1；pytest 1102 passed / R4 回填待手动触发）
> 作者：grill 会话  日期：2026-08-12
> 级别：**medium**（数据源 bug 修复 + 因子重定义 + match 条件改写；跨层但无新外部数据源）
> 流程门：develop 直提 + 勤 commit；issue 级 review；简化验收
> 关联：S062（reverse_package 卡片已记 S053 对照结论）、S047（权重已降为 0%）、S055（炸板预警规则引擎）

## 1. 问题 / 目标

`炸板后溢价` 因子近 60 日恒为 0，致 `break_reseal`/`reverse_package` 战法 60 日无信号。根因有二：

1. **数据源 bug**：`service.py:84` 拉 `getYesterdayZTPool` 用 `fbt:asc` 排序参数，该端点对 `fbt:asc` 返空；正确参数是 `zs:desc`（live 验证 8/11 返 97 条）。
2. **计算逻辑错**：`models.py:117-123` 的 `炸板后溢价` 公式分子取自 `yzt`（昨涨停池）的连板数、分母用 `zb_total`（炸板池数量）——分子分母来自不同池，语义不通。即使 `yzt` 有数据，公式也错。

目标：修复数据源 + 重新定义因子计算 + 解耦 match 条件，让两条战法恢复信号产出。

## 2. 背景（2026-08-12 live 核实）

### Bug 1 数据源（已核实）

`getYesterdayZTPool` 排序参数对照表（单次 em_get 探测）：

| 日期 | `fbt:asc`（现状） | `zs:desc`（正确） |
|---|---|---|
| 2026-08-11 | 0 条 | **97 条** |
| 2026-08-04 | 0 条 | **75 条** |

`service.py:84` 现用 `fbt:asc` → 恒返空 → 因子恒 0。

### Bug 2 计算逻辑（已核实）

`models.py:117-123` 现状：
```python
zb_total = len(zb)
if zb_total > 0:
    yzt_lianban = sum(1 for z in yzt if (z.boards or 0) >= 1)  # 分子取自 yzt
    rebound_rate = wilson_lower_bound(yzt_lianban, zb_total) * 100  # 分母用 zb_total
else:
    rebound_rate = 0.0
```

分子（yzt 连板数）与分母（zb 总数）来自不同池，无物理意义。

### 因子重定义可行性（已 live 验证）

新口径「炸板池次日回封率」= T 日 zb 池 ∩ T+1 日 zt 池 / T 日 zb 池：

| T→T+1 | zb | zt_next | 回封 | 回封率 |
|---|---|---|---|---|
| 8/04→8/05 | 15 | 103 | 3 | 20.0% |
| 8/05→8/06 | 43 | 79 | 6 | 14.0% |
| 8/06→8/07 | 20 | 74 | 3 | 15.0% |
| 8/07→8/11 | 26 | 58 | 1 | 3.8% |
| 8/10→8/11 | 14 | 58 | 1 | 7.1% |
| 8/11→8/12 | 17 | 92 | 1 | 5.9% |

数据有方差（3.8%~20%），不再是零方差死因子。

### DB 现状

近 15 日 `factor_rebound_rate` 全为 0.0（8/12 的 58 行、8/11 的 99 行…无一例外）。
S047 已把权重降为 0%——因子废弃但不删，保留计算用于 match。

### match 条件现状

`limitup_strategy.py:681-704`：
- `break_reseal`: `炸板后溢价 > 0 and 封板率 >= 50`
- `reverse_package`: `炸板后溢价 < 0 and total_score >= 55`

`reverse_package` 的 `炸板后溢价 < 0` 条件永远不满足（因子恒 ≥ 0）——这是第二个 bug。

## 3. 需求清单

- [ ] R1 修数据源：`service.py:84` 把 `getYesterdayZTPool` 的 sort 从 `fbt:asc` 改 `zs:desc`
- [ ] R2 重定义因子计算：`models.py:117-123` 改为「炸板池次日回封率」= T 日 zb ∩ T+1 日 zt / T 日 zb（wilson 下界修正）
- [ ] R3 解耦 match 条件：`break_reseal`/`reverse_package` 不再依赖 `炸板后溢价` 因子，改用其他可用因子（封板率/次日溢价率/total_score）
- [ ] R4 回填历史：修完后触发 gene_scores 重算 `factor_rebound_rate` 字段（近 30 日），让因子值不再恒 0。**必须补历史**——只跑当日的话历史日全 missing，看不到效果。`em_zt_topic_pool` 支持按历史日期查 T+1 zt 池，逐日补算。仅重算 gene_scores，不回填 prediction_ledger（已回填 90 天）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/limitup_screener/service.py` | R1：`getYesterdayZTPool` sort 改 `zs:desc` |
| `backend/limitup_screener/models.py` | R2：`compute_factors` 的 `炸板后溢价` 重定义 |
| `backend/limitup_strategy.py` | R3：`break_reseal` match 改 `zt_count_250d ∈ [3,5] 且 封板率>=80`；`reverse_package` 保留待 S055 |
| `backend/strategies/cards/break_reseal.md` | 更新卡片 match 条件说明 |
| `backend/strategies/cards/reverse_package.md` | 更新卡片说明"match 待 zb 池接线后激活" |

## 5. 设计方案

### R1 数据源（最小改动）

`service.py:84`：
```python
# 前：asyncio.to_thread(astock.em_zt_topic_pool, "getYesterdayZTPool", date, "fbt:asc"),
# 后：asyncio.to_thread(astock.em_zt_topic_pool, "getYesterdayZTPool", date, "zs:desc"),
```

### R2 因子重定义

新口径需 T+1 日 zt 池——这是**跨日聚合**，而 `compute_factors` 处理的是**单股历史序列**，职责不同。

**选定路径 C：调用方预算（`service.py` 层回填）**

`compute_factors` 保持纯单股逻辑不动（签名不扩展，3 个调用点不改）。`service.py` 本来就同时拉 zt/zb/yzt 三池，最自然在那里：
1. 在 `_fetch_zt_pool` 后追加拉 T+1 日 zt 池（单次 em_get）
2. 在 `compute_gene_score` 算完后，用 zb ∩ zt_next / zb 算回封率，回填 `factors["炸板后溢价"]` + 重算 `total_score`

**为何不选路径 A（签名扩展）**：`compute_factors` 有 3 调用点（主路径/回测点/K线重建点），签名扩展会强迫后两个传 `zt_next=None` 且 `compute_gene_score` 要透传新参数，污染面大。跨日聚合本不属于单股函数。

**为何不选路径 B（同 A 的变体）**：同上。

**路径 C 的边界处理：**
- 4a zb 为空：T 日无炸板股 → 回封率 0 + missing 标注（无炸板何来回封，诚实不臆造）
- 4b zt_next 拉取失败：T+1 数据未到/网络错 → 当日 missing 标注；但**R4 回填会补历史**——`em_zt_topic_pool` 支持按历史日期查 T+1 zt 池，回填时逐日补算
- 4c 跨周末 T+1：周五 T → 周一 T+1，自然算（gene_scores 交易日历跨周末正常）
- 4d 节假日 T+1：T 是节前最后一日，T+1 是节后。回封语义弱化但接受——拉失败即 missing，不特殊处理

### R3 解耦 match 条件（D4b grill 锁定：zt_count_250d 做区分维度）

**数据证据（近 30 日 / 2206 行，次日收益取自 prediction_ledger 回填）：**

`zt_count_250d` 分桶 × 次日收益（限定 total>=50）：

| zt_count 桶 | 候选 | 有收益 | 命中率 | 均收益 |
|---|---|---|---|---|
| 3-5 | 26 | 19 | **89.5%** | **+6.15%** |
| 6-10 | 23 | 18 | 61.1% | +3.09% |
| 11+ | 3 | 1 | 0.0% | -3.19% |

强单调反转：3-5 是"老练但不过劳"黄金区，6+ 衰减，11+ 反亏。

`封板率` 几乎无区分度（>=50 到 >=95 命中率 75.7%→80.6% 微弱升）；`次日溢价率` 非单调（>40 反降到 66.7%）；`total_score>=60` 拐点 83.3% 但样本仅 6 条。

**选定方案：**

- **break_reseal**：`zt_count_250d >= 3 且 zt_count_250d <= 5 且 封板率 >= 80`
  - 物理意义：历史封板能力（zt 3-5 黄金区）+ 当日封板强
  - 预期命中率：89.5%（19 条样本）
  - 注意：样本仅 19 条，n<10 不足，先跑起来积累样本再靠命中率反馈收敛
- **reverse_package**：match 不改，卡片更新说明"match 待 zb 池接线后激活"
  - 根因：reverse_package 物理定义是"前日跌停/断板后反包"，候选应来自炸板池（zb），不是涨停池（zt）。`match_strategies` 输入是 gene_scores（涨停股），结构上不会命中真正的断板反包标的。
  - 真正修复需要 zb 池接线到 match 逻辑，属 S055 炸板预警范畴，不在本 spec 范围
  - 暂时保留 match 条件原文（`炸板后溢价 < 0` 恒不满足），等 S055 落地后从 zb 池取候选激活

**为何不用 total_score>=60 做阈值（83.3% 拐点）：** 样本仅 6 条，统计学不足；且两战法若都用 total_score 做门槛会退化成一个战法，失去区分度。zt_count 3-5 黄金区既有更高命中率（89.5%）又能保持战法语义区分。

### R4 回填

修完 R1-R3 后，调 `precompute_daily_async` 逐日重算近 30 日 gene_scores 的 `factor_rebound_rate`。

**必须补历史**：只跑当日的话历史日全 missing（T+1 zt 池当日才拉得到，过了就拉不到——但 `em_zt_topic_pool` 支持按历史日期查 T+1 zt 池，所以能补）。

回填走 em_get（防封底线：限流 + 熔断），逐日串行，单日失败不阻断。

## 6. 验收标准

- [ ] A1 `getYesterdayZTPool` 用 `zs:desc` 返非空（单测 mock + live 冒烟）
- [ ] A2 `compute_factors` 新口径：给 zb + zt_next 算回封率；缺 zt_next 返 0 + missing 标注
- [ ] A3 `break_reseal` match 改 `zt_count_250d ∈ [3,5] 且 封板率 >= 80`（不再依赖 `炸板后溢价`）；`reverse_package` match 保留不改（待 S055 zb 池接线）；合成 gene 命中 break_reseal
- [ ] A4 回填后 DB `factor_rebound_rate` 不再恒 0（至少近 7 日有非零值）
- [ ] A5 pytest -m "not live" 全过

## 7. 合规与工程底线自查

- [ ] 因子属客观统计呈现；不臆造（缺 T+1 数据降级为 0 + missing 标注）
- [ ] 判断可复现：回封率 = zb ∩ zt_next / zb，可程序化验算
- [ ] 新增 em_get 走 `em_get()` 限流（R4 回填）
- [ ] 用户私有数据（gene_scores.db）不进 git

## 8. 测试计划

离线：`compute_factors` 单测（给 zb/zt_next 算回封率 + 缺数据降级）、`match_strategies` 单测（break_reseal/reverse_package 新条件命中）。联网：live 拉一日验证 yzt 非空 + 回封率非零。手动：DB 抽查 factor_rebound_rate 非零。

## 9. 风险与回滚

- R1 改 sort 后 yzt 非空但可能影响其他消费者？查 grep 确认 yzt 仅用于 `compute_factors` 的 `炸板后溢价`（已废弃权重 0%）。
- R2 T+1 日 zt 池拉取增加一次 em_get 调用——但 R1 已修 yzt，且 zt_next 是涨停池主端点，稳定。
- R4 回填触发 em_get 批量——走限流 + 熔断，失败降级。
- 回滚：恢复 sort 参数 + 恢复 match 条件。
