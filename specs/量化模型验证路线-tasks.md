# 量化模型验证路线 · 原子 task

> 拆自 [`量化模型验证路线.md`](量化模型验证路线.md)。每 task：ID / 描述 / 依赖 / 验收 / 状态。
> 状态：✅done / 🟡进行中 / ⬜待 / ⏸阻塞待用户/数据

---

## 阶段 0 · 前置（S150 采集修复 + HIGH3）

| ID | 描述 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T0.1 | S150 R1 timeout（`execute_async` 包 `wait_for` per-task_type）+ R2 reaper（`reap_stale_running`+`_reap_stale_runs`+`start` 重建前 reap） | — | 6 unit test 绿 | ✅done |
| T0.2 | S150 审查 HIGH1 修：独占 `ThreadPoolExecutor(max_workers=2)` + `run_in_executor` 替代 `to_thread` | T0.1 + 审查 | test_thread_pool_isolated 绿 | ✅done |
| T0.3 | S150 审查 HIGH2 修：`kline_refresh=1200` + `_REAPER_STALE_SECONDS=1300` | T0.1 + 审查 | test_task_timeout 含 kline_refresh=1200 绿 | ✅done |
| T0.4 | S150 全量回归（HIGH1/HIGH2 修后 no regression） | T0.2,T0.3 | 2676+ passed（deselect 3 flaky） | 🟡`b6wuhg6r3` 在跑 |
| T0.5 | :8900 重启加载 S150 新代码（PID 78868 旧代码） | T0.4 绿 | 重启后 `_running_task_ids` 重建不含 stale | ⬜待用户重启（或同意我 kill） |
| T0.6 | 明早盘中验证 task 5 正常写 `seal_intraday_snapshots_202609` 多一天 distinct date | T0.5 | 盘后查 seal_intraday_2026.db 多 1 天 | ⬜待 T0.5 |
| T0.7 | **HIGH3 根治**：`collect_once` 改 `subprocess.run(timeout=120)`（子进程可 kill，根治孤儿线程重复写库+_DB_LOCK 死锁）或改 async（httpx.AsyncClient，`wait_for` 可 cancel 协程） | T0.4 绿 + spec | 子进程/协程可真 cancel，无孤儿线程写库；test 覆盖 | ⏸待用户定（现在做 or 等 T0.6 验证后） |

---

## 阶段 1 · S153 现有 T-1 验证（日线可得，不卡 intraday）

| ID | 描述 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T1.1 | S153 spec Write（H1-H4 预注册 + R1-R10 + harness + solo审6疑点） | ✅done — spec v2 | done |
| T1.2 | S153 spec 审查（`wqnl70tka` 12 agent adversarial） | ✅done — 4 CRITICAL+2 HIGH 已修（H2 D+2入场/max_high line336/permutation新建/spec commit/R6 guard/Bonferroni K=6-8） | done |
| T1.3 | S153/S151 spec **git commit 锁预注册**（CRITICAL4） | 待 | 我 |
| T1.4 | R1 compute_consolidation 4-tuple（**max_high line 336 完整窗口**） | T1.3 | 4-tuple + max_high 正确 | ⬜ |
| T1.5 | R2 PatternScan 加 consolidation_max_high 字段 | T1.4 | 字段就位 | ⬜ |
| T1.6 | R3 scan_patterns 适配 4-tuple 解包 | T1.4 | test_pattern_scan 绿 | ⬜ |
| T1.7 | R4 PlatformBreakout match 加 C3（amplitude≤6.0） | T1.4-1.6 | C3 hit/miss/unavailable 绿 | ⬜ |
| T1.8 | R5 LowAbsorption match 加 C3（vol_brk<1.0） | T1.4-1.6 | C3 hit/miss/unavailable 绿 | ⬜ |
| T1.9 | R6 simulate_holding_with_confirm（**signal_date=D+1 + guard idx+2/None + D+2 入场**，无 look-ahead） | T1.4 | guard + D+1收盘确认 + D+2入场 | ⬜ |
| T1.10 | R7 platform_breakout_lift.py（**day_cluster_permutation 新建 + rolling walk-forward 非单 split + Bonferroni K=6-8**） | T1.7,T1.9 | harness 跑通 | ⬜ |
| T1.11 | R8 low_absorption_c3_lift.py | T1.8,T1.9 | harness 跑通 | ⬜ |
| T1.12 | R9 预注册冻结（**spec git commit hash 锁定**，train 不优化阈值） | T1.10,T1.11 | commit hash 锁 | ⬜ |
| T1.13 | R10 测试（C3 + 4-tuple + max_high line336 + guard） | T1.4-1.8 | pytest 绿 | ⬜ |
| T1.14 | 跑验证（day_paired_lift + permutation + rolling walk-forward + Bonferroni K=6-8） | ✅done — H1-H4 全无 edge（H1 0.9606劣于随机/H2 1.0791/H3 1.2177/H4 1.0015，p全远α_adj） | done |
| T1.15 | 诚实标注结果 | ✅done — 不事后调参，matrix 落档 .scratch/s153-*/matrix.json | done |

---

## 阶段 2 · 盘中满 30 天后扩展（~9-10 到点，依赖 T0.5/T0.6）

| ID | 描述 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T2.1 | 等 `seal_intraday` 满 30 交易日（现 4 天，差 26） | T0.5,T0.6 + 时间 | DB distinct date ≥30 | ⏸阻塞（数据积累） |
| T2.2 | `intraday_edge_validation` 补实现（复用 sector_heat_validation Wilson CI+lift）+ first_plate H2 质量门（封板时间≤10:30 × 开板次数=0）验证 | T2.1 | H2 path_lift 输出（看是否 >1 + 样本外） | ⬜ |
| T2.3 | weak_turn_strong / reverse_package / end_of_day_sneak 盘中交互验证（broken_duration/max_drop_pct/last_lock_time 等） | T2.1 | 各战法盘中交互 lift 输出 | ⬜ |

---

## 阶段 3 · 资金流（阻塞，等 IP/ut）

| ID | 描述 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T3.1 | 等 push2his IP/ut 恢复（现返空不可得） | IP/ut 环境 | `stock_fund_flow_120d` 返 ≥2 日数据 | ⏸阻塞 |
| T3.2 | `fund_flow_validation` 跑（T-1 main_net→T 涨停 lift） | T3.1 | lift 输出 | ⬜ |

---

## 横切 · 评价层 + debate 辅助（可并行起 spec）

| ID | 描述 | 依赖 | 验收 | 状态 |
|---|---|---|---|---|
| T5.1 | S151 评价层 spec：预登记冻结（lift≥2x+CI不重叠+n≥100且≥30交易日）+ 降权梯度（<1 robust→×0.1 / 1≤<2→×0.5 / ≥2→×1.0，不硬剔）+ 30日+n≥100 首次回溯 60日复验 + 诚实标注 | 用户起 | spec 落 | ⏸待用户 |
| T5.2 | S151 实现：评价层 + 选股层即时处理（换手 0.9979/167日 robust<1 → ×0.1 踢出；gene/breakout → ×0.1 保留采数不参与排序；tradability 硬剔保留） | T5.1 | 评价层标注"选股层无 validated 维度，edge 待盘中" | ⬜ |
| T6.1 | debate 辅助层 spec：加盘中事实（封单/开板/last_lock_time）进 `debate.py` 底稿让 AI 看（fund_flow 已在底稿）；**标"辅助非 edge"** | 用户起 | spec 落 | ⏸待用户 |
| T6.2 | debate 辅助层实现：底稿 `_DOSSIER_SPEC` 加盘中数据点 | T6.1 | debate 底稿含盘中事实，标非 edge | ⬜ |

---

## 关键依赖与并行

- **阶段 0 是地基**：T0.5（:8900 重启）→ T0.6（盘中验证）→ T2.1（30 天积累）。T0.7（HIGH3）可与阶段 1 并行（不阻塞验证）。
- **阶段 1 不卡 intraday**（日线可得）：T1.1-T1.14 可在 T0.4 绿后启动，与 T2/T3 并行。
- **横切（S151/debate）**：T5/T6 可与阶段 1 并行起 spec。
- **关键路径**：T0.5→T0.6→T2.1→T2.2（first_plate H2，唯一未证伪维度）是 edge 验证主线；T1.x（platform_breakout/low_absorption）是并行可立即做的验证。

## 诚实底线（每 task 不可破）

- walk-forward + day-cluster 置换 + Bonferroni 三关全过且 path_lift>1 前，所有战法维持 **raw-shadow stance**（零仓位积累数据），不驱动交易决策。
- 任何 lift 未经 day-cluster 去池化前都是假象（4.686x→1.723x 教训）。
- 预注册冻结防 p-hacking（T1.11 commit hash 锁定）；事后调参须标 post-hoc 降级探索性。
