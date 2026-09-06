# Spec: S160 — 底座重建方向 + re-scoped scope（世纪大辩论 verdict）

> 状态：草案（世纪大辩论 10 视角收敛 + grill 10 holes + 开源调研，2026-09-06）
> 关联：grill-foundation-holes-2026-09-06 / open-source-quant-framework-research-2026-09-06 / S159 / multiline-strategy-direction
> 分级：large（多组件+逻辑闭环+架构）—— feature 分支 + grill + 分步实施（S161-S166 增量）

## 0. 问题

底座方向（辩论裁决 + grill 定 scope）经 grill 8 视角审查找 10 承重漏洞（77% verify 真）+ 世纪大辩论 10 视角辩论。10 视角强收敛：否 B（再辩论=拖延），建 edge-agnostic 诚实测量基建 NOW，gap=hypothesis/证伪-pending 非 verified edge，defer fill/multi-line/gap-capture，修 reuse rot，reframe 三层。分歧经综合：engine 三层解耦（非 no-fill 降级），gap verify-now via 基建（daily-bar 非 60 天 intraday），scope medium-thin。

核心命门（grill #1+#2）经辩论**化解**：①"gap 未 verified 却当 edge 建基建"——建的是 edge-agnostic 验证基建（判定器），非 edge-capture 基建；gap 是 daily-bar 可 NOW 跑 §44v2 verify/falsify（非 60 天 intraday）。②"design-agnostic 引擎不可能"——engine 三层解耦：Decision+Accounting design-agnostic / Executor 可插拔 fill（deferred），非 no-fill 降级。

## 1. 目标

底座重建 = 建 edge-agnostic 诚实测量基建（验证任何候选 edge 的判定器，不依赖 gap 是否 verified）+ UI 契约先行 + gap hypothesis 跑 §44v2 verify/falsify + defer 方向绑定件 + 修 reuse rot + reframe 三层。不在未验证 edge 上建 capture 基建。

## 2. 需求清单（re-scoped core，design-agnostic 建 NOW）

1. **§44v2 验证框架**（priority 1，design-agnostic + edge-independent）：wire `vendor/skill-backtest-overfit`（DSR/PBO/CSCV/purged-kfold/haircut，现 0 接线）+ 合并 `tools/` 散落 day_paired_lift+permutation+Bonferroni+walk-forward 为单一 verifier。签名=(entry/exit return series + n_trials + 可选 trials_matrix)→verdict。接 qlib Recorder 模式（实验追踪落盘 n_trials 喂 DSR）。详见 S161。
2. **反前视回测引擎**（priority 2，三层解耦）：Decision+Accounting 层 design-agnostic（给定 Trades 序列算 path return / day_paired_lift 非池化 / walk-forward / Bonferroni 全局+per-family / cost 0.70%+印花0.1%+佣金5元 / survivorship unbuyable 过滤），借 qlib Nested Decision Point + backtrader 0/-1 索引+cheat_on_open。Executor 层可插拔 fill（T+1OpenFill 默认 impl，IntradayConditionalFill deferred）——非 no-fill 降级（风控/框架架构师否了 no-fill 焙进 s144 gap-blindness）。详见 S162。
3. **数据质量门 + 轻量血缘**（priority 3，design-agnostic）：源边界 schema 校验 + 血缘记录（脚本→artifact+commit hash）。**砍 lake/ETL**（无消费者 YAGNI，grill+数据 lens 证）。治 §44 synthesis 臆造前科 + harness 硬编码路径根因。详见 S163。
4. **防封 backbone robust + secrets gate**（priority 3，design-agnostic）：breaker 持久化（SQLite state 跨进程）+ per-端点拆（push2his/push2/datacenter/fflow）+ proxy_pool 接 transport（非裸 requests，MITM 防护）+ hithink key 轮换入 §1.2 secrets gate（启动校验+泄漏标记+轮换提醒）。详见 S164。
5. **UI 契约先行**（priority 1，contract-first）：DimensionValidationCard UI（mock 先跑，字段=dimension_id/label/lift/CI/n/days_robust/status/multiplier/source_script/note + 三窗口对比表 + overfit 统计占位"待建"灰底 + frozen/updated_commit）+ 实验记录 UI。UI 数据形状反过来锚定 §44v2 harness 输出契约 + evaluation_lifts.db schema + Recorder schema。UI 先行非被动呈现（[[ui-first-implementation-order]]）。详见 S165。
6. **Trade Journal + Risk Ledger**（priority 3，design-agnostic risk carve-out）：port S149 journal.py/excursion.py/at_risk.py（develop 缺，仅 feature 分支 cb54a96/f9898f9）。gap-down excursion 数据唯一来源。借 backtrader Analyzers 接口。Honest Risk Label（stop 对 gap-down 是仪式非保护，诚实标）。详见 S166。

## 3. defer（方向绑定/YAGNI，不建 NOW）

- fill Executor impl（IntradayConditionalFill，gap 方向绑定，grill #2）。
- 多线路骨架（line_id/注册/资源分配，零 validated 线路 YAGNI，grill #4）。只建 shared infra 接口。
- gap capture/intraday 执行（封板检测/pre-seal buy，方向层，需 60 天 live 积累）。
- OMS / 组合层风控（风控 core 无牙，依赖 OMS，grill #8）。
- lake/ETL/血缘重（无消费者 YAGNI，grill+数据 lens）。
- edge emergence/decay 监控（无 edge premature，grill #9）。只留数据质量监控。

## 4. 修 reuse rot + reframe 三层（hygiene，adopt A mechanics）

- REGISTRY 改标"§44 v1 窗口偏差 no-edge 记录（待 v2 重测）"，不灌进新底座当 final（grill #3）。
- harness 9 脚本 ROOT 改 env/config（VR_DATA_DIR 或 Path(__file__).parents[2]）参数化，不硬编码 Vibe-Research-S151（grill #3）。
- CronScheduler 改性"cron-driven fire-and-forget（无依赖图）"，非 DAG（grill #3）。
- reframe 三层为"1 built infra + 2 conceptual（selection=展示终态, direction=deferred 未建）"，无层间 producer-consumer 契约。regime gate 移 timing 层（grill #5）。
- 落地名门更新：S150 done / §44v2 spec-only / intraday direction-layer 非 design-agnostic（grill #7）。
- anti-overfit 措辞改"重用 §44v2 部分（walk-forward+Bonferroni），PBO/CSCV/DSR/Harvey 待建"（grill #6）。

## 5. gap 处理（hypothesis 非 verified edge）

- gap = 14 天 underpowered hypothesis（t=10.65 naive 池化，net+0.45% WR46.5%<50% 薄，S159 自标 underpowered）。
- NOW 跑 §44v2 重方法论 on gap（扩 14→42 天 daily-bar via baostock daily + ths_limit_up_pool，**非 60 天 intraday**——gap 是 daily-bar 量 D 收盘→D+1 开盘，统计验证不需 intraday）。day-paired 非池化+permutation null+Bonferroni K=~20+walk-forward+DSR n_trials=20。
- verdict：robust edge / 仍 underpowered / 证否。
- gap capture/intraday（封板检测/pre-seal buy）defer 到方向层（60 天 live 积累，非 NOW）。
- Chen2017 nuance：gap 是大户的不可复制，但 retail 可 intraday 打板捕获（非完全不可复制）——prior 倾向薄/难，但 verify via 基建（便宜，daily-bar NOW）。

## 6. 受影响文件

- 新建：`specs/S160-底座重建/spec.md`（本 spec）+ S161-S166 per-component specs。
- §44v2 验证框架（S161）：新建 `backend/` verifier 模块（合并 `tools/` 散落脚本）+ wire `vendor/skill-backtest-overfit`。
- 反前视引擎（S162）：新建 `backend/` engine 三层（Decision/Accounting/Executor）。
- 数据质量门+血缘（S163）：新建 `backend/` data_quality 模块。
- 防封（S164）：改 `circuit_breaker.py`（持久化+拆细）+ `proxy_pool` 接 transport + secrets gate。
- UI（S165）：新建 `frontend` DimensionValidationCard + 实验记录页。
- Trade Journal+Risk Ledger（S166）：port S149 `journal.py`/`excursion.py`/`at_risk.py` 到 develop。
- 修 reuse rot：改 `evaluation.py`（REGISTRY 改标）+ 9 harness 脚本（ROOT 参数化）+ `scheduled_tasks.py`（CronScheduler 改性 docstring）。

## 7. 验收标准

- [ ] S161-S166 per-component specs 写完（design-agnostic + edge-independent 验证）。
- [ ] §44v2 验证框架 wire backtest-overfit（DSR/PBO/CSCV/purged-kfold/haircut grep 非零）。
- [ ] gap 跑 §44v2 重方法论（14→42 天 daily-bar，verdict robust/underpowered/证否）。
- [ ] 引擎三层解耦（Decision+Accounting design-agnostic / Executor pluggable fill）。
- [ ] reuse rot 修（REGISTRY 改标 + 9 harness 参数化 + CronScheduler 改性）。
- [ ] UI 契约先行（DimensionValidationCard mock 跑 + 锚定 harness 契约）。
- [ ] 防封 backbone（breaker 持久化 + per-端点 + proxy_pool 接 transport + hithink key 轮换）。
- [ ] Trade Journal+Risk Ledger port S149 到 develop。
- [ ] pytest -m "not live" --deselect (newsradar+s032+s040) 全绿。

## 8. 合规与工程底线自查

- [x] 不臆造：gap §44v2 重方法论实算（day_paired+permutation+Bonferroni+walk-forward+DSR），禁 naive 池化。
- [x] 私有数据隔离：数据 cache 写 .vibe-research 不进 git；hithink key 轮换 + secrets gate。
- [x] em_get 防封：proxy_pool 接 transport（非裸 requests）+ breaker 持久化 + per-端点。
- [x] §44 降级参考性建议：v2 强化"前置 sanity+回溯主场"，不强制不阻塞。
- [x] verdict 外推禁令：gap 标 hypothesis 非 verified，跑 §44v2 后才称 robust/证否。
- [x] 不闭门造车：10 专家辩论 + 开源调研 + 文献（Chen2017/Hua'an/Harvey/López de Prado）。

## 9. 分级

**large**（底座重建，多组件 + 逻辑闭环 + 涉及架构）。feature 分支 + grill + playwright 验收。分步实施（S161-S166 增量，每步 §44v2 验证+复盘）。per-component specs 先行（S161 §44v2 验证框架 priority 1，S165 UI 契约先行 priority 1 并行）。
