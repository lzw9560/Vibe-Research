# Spec: S095 — gene_scores 写路径修复与日期自证守卫

> 状态：spec 落盘，待审查
> 作者：opencode 会话  日期：2026-08-23
> 级别：**medium**（写路径修复 + 守卫，不改业务算法，不碰前端）
> 流程门：spec.md + plan（并入本文件）；issue 层单轮审查；直接 develop 提交
> 依赖：日期完整性专项已落（今天的全项目 is_trading_day 守卫 + 东财静默回退修复）
> 承接：S094 §10 S0 "前置硬门"（S094 的 S2/S4 合并前必须完成本 spec）

## 0. 起因（实证根因）

gene_scores 表历史行**系统性错位一天**（Oracle 两轮独立复现，08-13 起每一天）：

| gene_scores 行标签 | 实际名单 = | 写入时刻（updated_at） |
|---|---|---|
| 08-17 周一（63只） | **08-16→实为 08-14 周五**的池 63 只 | **08-16（周日）16:00** |
| 08-18 周二（106只） | 08-17 周一的池 106 只（全等） | 08-17 周一 16:11 |
| 08-19 周三（79只） | 08-18 周二的池 79 只（全等） | 08-18 周二 16:13 |
| 08-20 周四（36只） | 08-19 周三的池 36 只（全等） | 08-19 周三 17:46 |
| 08-21 周五（54只） | 当日池（唯一正确） | 08-22 17:28（fix-18 重算） |

**根因机制**（三个事实拼合）：

1. `gs(T)` 的 code 集合 ⊆ `zh(prev_trading_day(T))` —— 标签是 T，内容是**前一个交易日**的池
2. `gs(08-17)`（周一）写于 **08-16 周日 16:00**——周一交易尚未发生，此时请求"周一的池"，东财无此数据
3. 东财对"未来日期/无数据日期"请求**静默返回最近一个已定型池**（08-14 周五），代码未校验数据日期，直接以请求日期 T 标写入

**核心：这不是"非交易日"问题**（那种今天的 is_trading_day 守卫已修）——是**时序问题**：在 T 日池**尚未收盘定型**时（盘前/周末/任意未来时点）请求 T 的池，静默回退 + 未自证日期 → 错位标写入。`is_trading_day(T)=True` 的交易日同样中招（因为请求时刻早于收盘定型时刻）。

**影响**：FLOW A 候选输入（`workflow.py:182 load_gene_scores`）+ 基因得分 + R12 confidence 复用 + sector_cycle `aggregate_sectors`（按 date 读 gene_scores）+ backtest_lite/forward_test 全部坐在错位数据上。是 S094"坚实底座"的阻断前提。

## 1. 需求清单

### A. 写路径日期自证守卫（核心）

- [ ] R1 `_compute_and_cache_async`（limitup_screener/service.py:188）落盘前加**数据日期自证校验**：
  - 请求日期 `target_date` 若 > 最近交易日（`last_trading_date_str()`）→ **拒绝写入**，返回空/降级结果（未来日期必然无真实数据）
  - 请求日期 ≤ 最近交易日但**池尚未定型**的窗口（当日盘中，`now < 15:31`）→ 按既有"盘中口径"逻辑走（现状保留，不算错位——盘中快照本身语义合法），但须校验返回池行数与 zt_history 同日快照一致（不一致告警）
- [ ] R2 **未来日期拒绝**是唯一硬闸门：`target_date > last_trading_date_str()` 时 `_compute_and_cache_async` / `precompute_daily_async` / `precompute_daily` 三入口统一拒写、返回空结果（不查东财，不浪费请求）
- [ ] R3 调用方诚实降级：`pre_market_workflow.py:121`（盘前算当天）、`scheduled_tasks.py:614`（回填循环）、`backfill_history.py:204` 三处写路径消费方在收到空结果时记录日志 + 不写假数据（现状已部分处理，本条补齐）

### B. 数据日期自证机制（防未来再犯）

- [ ] R4 东财池返回后加**交叉校验钩子**：`_fetch_zt_pool(target_date)` 拉到的池与 `zt_history.db` 同日快照（若存在）比对，行数或 code 集合不一致 → 告警日志（不硬失败——盘中收缩是合法的）。若请求日期在 zt_history 已有 final 快照且行数不一致 → **拒绝写入**（final 快照是权威）。
- [ ] R5 `save_gene_scores`（data.py）加 `pool_date` 元数据列（可选增强）：记录"数据实际来源日期"，与 `date`（标签）分离——未来再出现错位可从元数据发现。

### C. 调用方清理（根绝误传未来日期）

- [ ] R6 梳理所有写路径调用方（`get_screener_result` / `precompute_daily*` 显式传日期的 12 处），逐一确认传入日期 ≤ 最近交易日；盘前场景（`pre_market_workflow.py:121` `self.date` 为当前交易日）确认盘前请求东财当日池的行为语义（东财返回空 → 已处理；不应请求未来日期）
- [ ] R7 `scheduled_tasks.py:614` 回填循环（`back_days` 回溯）已带 is_trading_day 守卫（今天落地）——确认回溯方向是"过去"非"未来"（现状正确，本条只加测试锁定）

### D. 历史数据处理（已完成，本条为确认）

- [ ] R8（已完成）fix-18 重算 08-13~08-21 历史行（5/5 code 集合全等），备份 `.vibe-research/gene_scores.db.bak-recompute-offset-2026-08-23`
- [ ] R9 08-13 及更早的历史行：若用户需要长窗口回测（§44 复验），按同样口径重算；不需要则保留现状（标注"08-13 之前可能错位"）。**拍板：保留现状**——回测窗口用 08-13 起即可（近 2 周足够 §44 复验），不扩大重算范围

## 2. 受影响文件

| 文件 | 改动 |
|---|---|
| `limitup_screener/service.py` | R1/R2 三入口未来日期拒绝 + R4 交叉校验钩子 |
| `limitup_screener/data.py` | R5 pool_date 元数据列（可选） |
| `pre_market_workflow.py` | R3/R6 盘前场景诚实降级 |
| `scheduled_tasks.py` | R7 测试锁定回溯方向 |
| `tests/test_s095_gene_scores_guard.py` | 新增：未来日期拒绝 / 盘中小时合法 / 交叉校验告警 / final 快照权威 |

## 3. 验收标准

- [ ] AC1 `precompute_daily_async('2026-08-24')`（未来日期）返空结果 + 不查东财（mock 断言）
- [ ] AC2 `precompute_daily_async('2026-08-21')`（历史交易日）正常计算（回归不破坏）
- [ ] AC3 `precompute_daily_async(last_trading_date_str())` 当天盘中请求合法（保留现状语义）
- [ ] AC4 `precompute_daily_async('2026-08-22')`（周六，最近交易日之后）返空（非交易日也归入"未来"拒绝）
- [ ] AC5 交叉校验：mock zt_history final 快照与请求池不一致 → 拒绝写入 + 日志
- [ ] AC6 pytest `-m "not live"` 全绿（基线 2215 passed 不退化）

## 4. 设计取舍

1. **只做未来日期硬闸门，不改盘中语义**——盘中快照（`now < 15:31` 请求当日）是合法业务需求（盘后预计算依赖），不是错位。错位的本质是"未来日期请求"。
2. **交叉校验是第二道防线，非唯一防线**——主防线是 R2 未来日期拒绝；R4 是深度防御。
3. **不扩大历史重算范围**——08-13 前保留现状（R9 拍板），避免大范围重算引入新风险。

## 5. 合规自查

- [x] 不臆造：未来日期拒绝写入（返空不造假）；交叉校验不匹配拒绝写入
- [x] 私有数据 .vibe-research/ 不进 git
- [x] em_get 防封：未来日期拒绝不查东财

## 6. 冲突审查

| 旧逻辑 | 旧决策 | S095 决策 | 处置 | 迁移路径 |
|---|---|---|---|---|
| `_compute_and_cache_async` 无日期自证 | 接受东财静默回退任意日期 | 未来日期拒绝 + 交叉校验 | 替换 | 三入口统一闸门 |
| 盘前算当天（`pre_market_workflow:121`) | 接受空池降级 | 保留 + 诚实降级补齐 | 共存 | 补日志 |
| 历史重算范围 | 未定 | 08-13 起（不扩大） | 拍板 | 保留现状 |

## 7. 实施（plan 并入）

### S1 未来日期硬闸门（R1/R2）
- `limitup_screener/service.py` 三入口加 `if target_date > last_trading_date_str(): return _empty_result(target_date)`（非交易日也归入拒绝：周六 > 最近交易日周五）
- 新增 `tests/test_s095_gene_scores_guard.py` AC1/AC2/AC3/AC4

### S2 交叉校验钩子（R4）
- `_fetch_zt_pool` 后加对比逻辑：zt_history 有 final 快照且行数不一致 → 拒绝写入
- 测试：AC5

### S3 调用方诚实降级 + 测试锁定（R3/AC6)
- `pre_market_workflow.py:121` / `scheduled_tasks.py:614` / `backfill_history.py:204` 补日志
- `scheduled_tasks.py:614` 回溯方向测试（R7）
- 全量回归（AC6）

### 依赖
S1 → S2 → S3（串行，每步有对应测试）

## 8. 已知盲点

1. `zt_history.db` 的 final 快照覆盖率：08-20/08-21 是 non-final（fix-18 时段写入），历史日 final 覆盖不全 → R4 交叉校验只在"有 final 快照"时生效，非全量防线。接受——主防线是 R2 未来日期拒绝。
2. `pool_date` 元数据列（R5）是可选增强，若 S1/S2 已足够，可推迟到 S094 实施后按需加。
