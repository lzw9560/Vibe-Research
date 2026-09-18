# Spec: S219 — 封单成交比 §44 runner + fund 回补

> 状态：**deferred**（grill `wlf43z1f9` needs_revision confidence 0.86，synth #1 = DEFER 整个 spec）
>
> **deferred 原因**（三外部 gate 未满足）：① consecutive_relay ×0.75 provisional 非 ×1.0 definitive（panel un-freeze trigger1 未达）；② delivery 未 4 周真 P&L 验证（record_t0_fill 零生产调用，trigger2 未达）；③ fund 仅 em live ~49 天 <60（§44 R6 门槛，backfill 315 天不可行——akshare em 历史日返空率 63%）。
>
> **Errata（effaa99 commit msg 夸大）**：effaa99 commit msg 称 "record_t0_fill wired" 为夸大——实测 `record_t0_fill` 定义于 `backend/strategies/journal_recorder.py:114` 但全仓零生产调用者（bb0362f 已将 test 名 `_wired` 改 `_exists_not_wired` 诚实标注"定义存在但零生产调用，P0 用 manual_trades.jsonl path 未接入 fills_json"）。本 spec deferred 原因 ② 引用的"record_t0_fill 零生产调用"即此事实。归档 chore commit 待 main session 执行。
>
> **grill 8 CRITICAL**：R1 fund 历史不可回补 / em_get vs akshare 架构互斥 / backfill 会毁 consecutive_relay 生产 lbc / realizability 盲区（>10 桶=一字板高发）/ walk-forward 是 category error（该用 chrono holdout）/ R6 baked false fact（dimension_registry.py + get_multi_arm_recommendations 都存在，真 gap 仅 register_arm()函数+臂行）/ 两结局 0 实际收益（process theater）/ window_sanity 是声称非工程化。
>
> **un-defer 条件**：consecutive_relay 升 ×1.0 definitive AND delivery 4 周真 P&L 验证 AND fund 累积≥60 天。当前留 R1-R4 triage（fund≥60 天前只跑窗口 sanity，verdict 强制 underpowered），R5/R6 scaling 移除。详见 memory `s219-grill-2026-09-18`。
> 作者：lzw9560  日期：2026-09-18
> 关联：S211（consecutive_relay arm live wired）、S214（hithink backfill）、S217（chrono forward-OOS stage-2）、S205（per-战法维度集/strategy harness）、S218（C1 daily report）；memory [[t1-limitup-prediction-research-2026-09-18]]、[[gap-window-rerun-2026-09-18]]、[[multi-strategy-loop-panel-synthesis]]、[[milestone-2026-09-18-pivot]]

## 1. 问题 / 目标

freeze 条件 1（consecutive_relay stage-2 有答案）满足后，推进 2nd 战法候选验证。封单成交比 = 封单资金/成交额，是 panel synthesis + T+1 research 双重推荐的"冻结解除后 2nd 战法首选"——结构最不同（封板强度 vs consecutive_relay 连板数）+ 实盘共识最强（学术 Wan 2015 + 东方财富 + CSDN + 雪球 + 数量技术宅多源收敛"最强单一特征"：封单成交比>10→次日涨停>70%+连板>60%；3-10→次日高开≥6%）。

**目标**：回补 fund 315 天 + 写封单成交比 §44 runner（§44 v2 前置窗口 sanity gap/path/next-day-ZT 三窗口）+ 验证是否有 edge。过=2nd paper edge（register_arm + DailyReport 加）；不过=做减法 archive（同 late_lock/sector_heat 命运）。

## 2. 背景

**数据现状（2026-09-18 查清）**：
- zt_history schema 有 `fund`（封单额）+ `fundamt`（成交额）字段 ✓
- 但 fund 只 em 期 1178 行（~49 天，source=em），hithink backfill 12590 行 + ths 2279 行**不带 fund** ✗
- fundamt **全空**（0/16047）✗
- baostock cache 有 `amount`（成交额，5218 codes × 2067 bars）✓——fundamt 不须回补，按 date+code join 即可
- akshare `stock_zt_pool_em(date=历史日)` 返"封板资金"——fund 可回补 315 天，走 em_get route（push2ex URL + 熔断器 + 2s sleep，~315 调用量大须限流）

**§44 v1 错窗口教训**（[[gap-window-rerun-2026-09-18]]）：late_lock（封板时间特征，同族）在 gap 窗口 **FALSIFIED**（0.58x 方向错，late-seal gap DOWN vs universe UP）——封单成交比是封板强度特征，同族风险。§44 v2 前置窗口 sanity 必做——先 gap/path(D+1-open→D+4)/next-day-ZT 三窗口对比定位优势在哪，无则不上重方法论。

**panel synthesis 4 trigger**：① consecutive_relay definitive（DONE stage-2 ×0.75）② delivery 4 周真 P&L（时间 gate）③ candidate 过 step-0 triage（封单成交比要测）④ edge 结构不同（封单成交比封板强度 vs 连板数，满足）。un-freeze 须 ALL 非 OR——本 spec 验证 ③+④。

## 3. 需求清单

- [ ] R1 **fund 回补**：**⚠️ 2026-09-18 实测 CRITICAL blocker**：`akshare stock_zt_pool_em(date=历史日)` 5 个 spread 日期全返空（em ~14 天 rolling）+ hithink backfill 12590 行不带 fund + ths 不带 + baostock 无 fund（只 amount 成交额）。**备选 ③ 已调研不可行**：`stock_zt_pool_strong_em` 历史日空 + 连近期都不返封板资金字段（只成交额），`previous_em` 历史日空 + 近期返"昨日封板时间"非封板资金。**fund 历史回补完全不可行**——只 em live snapshot 近期 ~49 天有 fund。备选：① em live 累积 fund ~60 天后达 §44 R6（时间 gate，须等 ~2 月）② 封单成交比只近期 ~49 天 underpowered 标探索性不做 definitive。**R1 blocker 须 grill verdict 后定方向**——S219 可能 defer 到 em live 累积后，或降级探索性，或换 2nd edge 候选。
- [ ] R2 **fundamt join**：baostock cache amount 按 date+code join zt_history（不须回补，cache 已有 5218 codes）
- [ ] R3 **封单成交比 §44 runner**（`tools/seal_turnover_ratio_lift.py`，套 `zt_pool_seal_time_lift.py` compute_obs 模板）：
  - 封单成交比 = fund / baostock_amount
  - §44 v2 前置窗口 sanity：gap（D-close→D+1-open, gap_net_return）/ path（D+1-open→D+4, path_return）/ next-day-ZT 三窗口对比定位优势
  - 分桶（封单成交比 >10 / 3-10 / <3）vs universe，每窗算 lift+胜率+mean+base rate+IC
- [ ] R4 **§44 验证**：lift≥2.0 robust_edge / 1.0-2.0 未validated / <1.0 劣于随机；n≥60 天（<60 标 underpowered 不判劣于随机，§44 v2）；Bonferroni 按 n 调；walk-forward（若 n 够）
- [ ] R5 **诚实性 verdict**：过=2nd paper edge（DIMENSION_LIFT_REGISTRY 加 seal_turnover + **新建 multi-arm registry + refactor signal_report.py 支持 multi-arm**【当前硬编码 consecutive_relay line 171/200/292】+ DailyReport 加维度）；不过=做减法 archive（同 late_lock）
- [ ] R6 **multi-arm view 扩展（非新建）+ register_arm() bridge**（P1 seam）：**⚠️ 2026-09-18 grill wlf43z1f9 核实（修正我 solo grep 错）**：`dimension_registry.py`（`strategies/dimension_registry.py` 有 DIMENSION_REGISTRY + "封单强度"维度）+ `get_multi_arm_recommendations`（`recommendation_engine.py:250`，floor/breakout/limitup/trend/gap 臂）**两者都在**。真 gap 仅 `register_arm()` 函数不存在 + consecutive_relay/seal_turnover 臂行没加。R6 scope = 给现有 `get_multi_arm_recommendations` 加臂行（row-add），**非新建**。**R6 defer 到 seal_turnover 过 §44 robust_edge 后**（synth #2，gate on R4）。我之前 solo grep 只搜 `candidate_funnel/`+`s205`，漏 `strategies/`+`routers/`，致 baked false fact——教训：solo grep 须全仓 not subset。

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/tools/seal_turnover_ratio_lift.py` | 新——封单成交比 §44 runner（套 zt_pool_seal_time_lift.py 模板）|
| `backend/data/zt_history_store.py` | 扩 fund 回补函数（akshare zt_pool 历史日走 em_get 落 db，保 source 标注）|
| `backend/data/transport.py` | em_get route push2ex zt_pool 端点（限流/熔断，不裸调 akshare）|
| `backend/candidate_funnel/evaluation.py` | DIMENSION_LIFT_REGISTRY 加 seal_turnover（若过 robust_edge）|
| `backend/strategies/dimension_registry.py` | **已存在**——DIMENSION_REGISTRY 在此（含"封单强度"维度）；`get_multi_arm_recommendations` 在 `backend/recommendation_engine.py`（floor/breakout/limitup/trend/gap 臂）。两者都在（2026-09-18 grill wlf43z1f9 核实，修正 solo grep 错）。真 gap 仅 `register_arm()` 函数不存在 + consecutive_relay/seal_turnover 臂行未加（R6 scope= row-add 非 new-build）|
| `backend/tools/signal_report.py` | **重构**——支持 multi-arm（当前硬编码 consecutive_relay line 171/200/292，S219 若过须 refactor）+ 若过加 seal_turnover 维度（C1 扩）|

## 5. 设计方案

**fund 回补**：
- 走 em_get route（push2ex URL + `circuit_breaker.get_breaker("eastmoney")` + 2s sleep）
- 不裸调 akshare/requests（§1.2 工程底线——akshare stock_zt_pool_em 内部走东财 push2ex，属东财端点须走 em_get 限流防封）
- 回补 2025-06→2026-09 缺口期（hithink/ths source 行的 fund 字段空），只补 fund（fundamt 从 baostock join）
- 幂等：同日同 code 重写覆盖（zt_history PRIMARY KEY(date,code)）
- 备选：直接 akshare + 2s sleep（zt_pool_seal_time_lift.py:7 现状）——**不选**，违反 §1.2（akshare 不限流 315 调用风险封 IP）

**封单成交比 runner**：
- 套 `zt_pool_seal_time_lift.py` compute_obs 模板（D, code, seal_amount, net, win）
- 封单成交比 = fund / baostock_amount（当日总成交额，非涨停瞬间封板成交额）
- §44 v2 前置窗口 sanity：gap / path / next-day-ZT 三窗口都算，先定位优势在哪
- 分桶 >10 / 3-10 / <3 vs universe

**§44 v2 应用规约**：
- 前置窗口 sanity（必做，§44 v2 第 1 件事）
- 重方法论只在对窗口+n 够时上（<60 天标 underpowered 不判劣于随机）
- Bonferroni 按 n 调不 over-correct
- §44 不每阶段参与（spec 轻 sanity + grill 只留重大方法论变更）

**multi-arm view 新建（P1 seam）**：
- 2026-09-18 grill wlf43z1f9 核实（修正 solo grep 错）：`strategies/dimension_registry.py` + `recommendation_engine.py:get_multi_arm_recommendations` **两者都在**，`signal_report.py:169-258` 硬编码 consecutive_relay（`_compute_consecutive_relay_decay`）。真 gap 仅 `register_arm()` 函数不存在 + consecutive_relay/seal_turnover 臂行没加
- 封单成交比若过，须**扩展** 现有 multi-arm registry（加 `register_arm()` → dimension + cap + verdict，row-add 非 new-build）+ refactor signal_report.py 支持 multi-arm（不硬编码 consecutive_relay）
- 这是 panel synthesis 说的"前瞻设计 scope=design seam"——**bridge 到已有** multi-arm registry（`strategies/dimension_registry.py` + `recommendation_engine.py`），非 new-build（spec 原臆造引用 dimension_registry.py/get_multi_arm_recommendations 不存在，已修正）
- 备选：R6 defer 到"seal_turnover 过 §44 后"再做——若 grill verdict 建议 premature，R6 可从本 spec 拆出（R1-R5 先做，R6 待 2nd edge 确认后）

## 6. 验收标准

- [ ] A1 fund 覆盖 ≥60 天（§44 R6 门槛），走 em_get route 不裸调
- [ ] A2 §44 verdict 三窗口都算（gap/path/next-day-ZT），定位优势窗口
- [ ] A3 grill workflow 过（≥6 lens，§44/方法论 spec 必起，CLAUDE.md §1.3+§7）
- [ ] A4 TDD test（runner + fund 回补 + register_arm bridge）
- [ ] A5 若过 robust_edge：register_arm + DailyReport 加维度；若不过：archive（做减法）
- [ ] A6 不臆造数据（akshare 真实回补），私有数据隔离（.vibe-research/）

## 7. 合规与工程底线自查

- [ ] 工程底线：不臆造数据（akshare 真实回补 fund）/ 私有数据隔离（.vibe-research/ 不入 git）/ em_get 防封（akshare zt_pool 走 em_get route 不裸调，§1.2）
- [ ] §44 v2：前置窗口 sanity（gap/path/next-day-ZT 三窗口对比）/ 重方法论只在对窗口+n 够（<60 天标 underpowered）/ Bonferroni 按 n 调 / §44 不每阶段参与（spec 轻 sanity + grill 重大方法论）
- [ ] 研判属系统能力（2026-07-30 新口径，CLAUDE.md §1.1）；用户可见输出挂轻量风险提醒
- [ ] 判断可复现：§44 verdict 基于公开数据 + 既定规则可复算，禁臆造/心算
- [ ] 涨停四池个股属公开榜单客观事实（可呈现 code/name）
- [ ] 用户私有数据未进 git

## 8. 测试计划

- `pytest -m "not live"` 离线快测（runner + 回补 + register_arm）
- fund 回补 smoke：实跑 akshare zt_pool 历史日走 em_get 回补 1 周验证 fund 落 db
- §44 verdict smoke：实跑 runner 算三窗口 lift
- grill workflow ≥6 lens 审 spec 方法论（§44 v2 + 错窗口风险 + register_arm seam）

## 9. 风险与回滚

- **R1 fund 历史回补不可行**（CRITICAL，2026-09-18 实测）：akshare em 历史日全空 + hithink/ths 不带 fund + baostock 无 fund。fund 只 em live 近期 ~49 天。S219 可能须 defer 到 em live 累积 60 天后，或降级 underpowered 探索性。memory t1-research"zt_pool 已 backfill 315 天"是 stale（hithink backfill 315 天带 lbc 不带 fund）。
- **§44 v1 错窗口风险**（高）：封单成交比同族 late_lock 在 gap 窗口 FALSIFIED——封单成交比可能同命运。缓解：§44 v2 前置窗口 sanity 先定位优势窗口，无则不上重方法论。
- **falsified 风险**（中）：late_lock + sector_heat 都 falsified，封单成交比是第 3 个封板特征候选。缓解：若不过 robust 即 archive（做减法，同 late_lock）。
- **fund 回补被封 IP**（中，已降级）：R1 blocker 后 fund 回补不可行，此风险 moot。em live 累积每日 1 snapshot 低量无封 IP 风险。
- **工程量**（中）：fund 回补 315 调用 + runner + §44 + grill + register_arm 跨会话。回滚：分阶段（R1 回补→R3 runner→R4 §44→R6 register_arm），每阶段独立可停。
