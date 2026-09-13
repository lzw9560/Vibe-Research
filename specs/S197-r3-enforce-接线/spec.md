# Spec: S197 — r3-enforce 接线（R3 task reminder→enforce + registry DB-backed 动态读）

> 状态：v2 草案（6 视角对抗审 wrs3bqhis 后修订，needs-revision→revised；待 9-25 forward_test 30 天数据 + 用户确认破坏性 safeguard）
> 作者：Claude  日期：2026-09-13
> 分级：medium（改 scheduled executor + DIMENSION_LIFT_REGISTRY 读法，承重 + 破坏性）
> 关联：RB-8 backlog / §44 v2 P0 (c) / [[S151 R3]] / [[S180 r3 sizing]] / [[S159-§44应用规约v2]]
> 对抗审 verdict：wrs3bqhis（6 视角，design_holds=needs-revision，3 CRITICAL + 7 HIGH，详见 wrs3bqhis.output）

## 1. 问题 / 目标 + 对抗审发现

**RB-8 现状（2026-09-13 调研 + 对抗审）**：
- §44 v2 P0 (a) lift_to_multiplier 接线生产 ✅ DONE（verifier.py:12 + scoring.py:68，替代直读 frozen weight_multiplier）
- §44 v2 P0 (b) days_robust<60 provisional cap ×0.5 ✅ DONE（evaluation.py:212 gate + 219-225，生产侧已 enforce）
- forward_test monitor endpoint ✅ DONE（S188 P0 #3，scheduled_tasks.py:115）
- get_forward_test_summary 评估逻辑 ✅ DONE（forward_test.py:349）
- R3 task（evaluation_backtest）仍 reminder——到点写 checkpoint + WARNING + 返 action 指引「由人跑 harness」，不自动验证
- DIMENSION_LIFT_REGISTRY 冻结常量（evaluation.py:48，frozen_commit 2026-09-05）

**backfill 无效（真 OOS blocker，非 lazy wait）**：forward_test picks 依赖 live intraday seal data（gene_scores eastmoney_live），深度 backfill 被 seal_time 墙挡；07-13→08-16 的 25 天 eastmoney_live gene_scores 虽存在但 score_candidates 07-13 后改过（`27403bc`）→ backfill 重算 picks = look-ahead bias。

**对抗审 3 CRITICAL 执行缺口**（wr33bqhis verdict）：
1. **`--baostock` flag 不存在**（first_board_layer_lift.py:769 只认 `--baostock-history`）→ backtest.py:161 action 引用 `--baostock` → 9-25 真跑 fallthrough 到 run_layer_lift(days=120)→days_robust≥60→**绕过 30 日 provisional cap ×0.5**，废掉积累期保护
2. **enforce 触发机制未定义**：seed.py:271 payload 无 enforce key，§5「用户显式触发」无 API/CLI 路径。30/60 天跨阈本身自动（数据日积）→「用户显式触发」承诺不可实现，dry-run 默认 ≈ 现状 reminder = §44 v2 P0(c) 未落地
3. **ci_overlap 死接线**：lift_to_multiplier:196 默认 ci_overlap=True/robust=True，4 生产调用点（scoring.py:68/verifier.py:112/evaluation.py:267,303,314）全不传 → validated 分支（:230 需 `not ci_overlap`）不可达，harness 不算 CI → spec R3 的 60 日升级逻辑不可实现，唯一能自动触发的是破坏性降级 ×0.5→×0.1（清零 5 gene 因子）

**对抗审 7 HIGH**：harness 输出无 days_robust/CI / 依赖链（R3 写 days_robust→生产 cap 读 db，safeguard 不独立）/ 无 rollback / registry load 语义未定 / 无幂等迟滞 / 无审计 trail / DIM_ARM_MAP 重复 breakout 键（evaluation.py:242 vs 249）/ 单 harness 只盖 2/17 维。

**redundancy 判定**（不冗余）：lift_to_multiplier=策略层（已 enforce 冻结输入），R3=数据新鲜度更新层（未 enforce）。依赖链非冲突：R3 喂 lift_to_multiplier（R3 写 days_robust→db，lift_to_multiplier 读算 ×0.5 cap）。生产侧 cap 不再独立，正确性取决于 R3 db 写准确性。**R3 必须在生产读层加 pending→approved 两门**，让 lift_to_multiplier 只读 approved，否则 db 写直接变输入=无 safeguard 破坏性传播。

**目标**：R3 task reminder→enforce（两门设计）+ DIMENSION_LIFT_REGISTRY 冻结→DB-backed 动态读（cached-TTL + provenance）。运行需 forward_test 30 天 live 数据（~9-25，不可 backfill）。

## 2. 需求清单（v2，据对抗审 16 条 spec_revisions）

### R1：evaluation_backtest 到点自动跑 harness（scope 限定 + flag 修）
- 修 `--baostock` → `--baostock-history`（first_board_layer_lift.py:769 实际 flag）
- **scope = turnover/seal_amount only**（明文「部分动态/15 维冻结」），不暗示一次 subprocess 更新全 registry——单 harness 只产 2/17 维，其他维度由各自 harness 写
- evaluation_lifts.db schema 显式定义（dimension_id PK + lift/n/days_robust/ci_overlap/robust/phase/last_reverified_at/updated_at/source_script）+ writer 明确（executor 解析 harness JSON 或改 harness 直写）
- 或复用 recorder.db + dimension_id↔line_id 映射层（harness 写 first_board_layer:layer1/2/3 非 registry 17 键）
- **明文 baostock 源维度 days_robust≥60 在 30 日就过 cap 的语义**，或改用 forward_test_records 源（days_robust=30 让 cap 真咬）

### R2：DIMENSION_LIFT_REGISTRY DB-backed 动态读（OVERLAY + cached-TTL + provenance）
- **OVERLAY 非替换**：DB 维度覆盖自己条目，冻结基保留给 DB 无的维度（保 ofi/seal_sincerity/bid_ask_pressure 的 exploratory cap 不丢）
- load 语义 = **cached-with-short-TTL（1h）+ enforce 时 cache-invalidate**（非 eager import——需重启才生效=「动态读生效」FALSE；非 per-call——N+1 db hit per score）
- silent fallback 到生产评分路径加 **provenance marker**（source='fallback_frozen_stale_2026-09-05'）surfaced 到 GET /api/evaluation/dims + card.evaluation
- 降级范式对齐 _load_cache fallback-empty-write-corrupts（db 缺/坏返冻结值不崩），但补「valid-but-wrong」检测（borderline lift=0.99 方法论 artifact）——sanity check 持久化前（lift∈[0,5] n>0 days_robust 匹配 forward_test 日数±10%）

### R3：两门 safeguard + enforce 触发 + ci_overlap wire + 幂等迟滞 + 回滚审计
- **两门设计**（最关键修订）：
  - gate1 `enforce`：run harness + 写 db + REPORT verdict（pending 状态，不生效生产读）
  - gate2 `promote`：人工 review lift 后才翻 approved，让 registry 读 db 值（API/CLI，非 cron payload sticky）
  - 分离「知道 lift」（安全 informational）和「应用到生产」（破坏，改 scoring.py:68 的 5 gene 因子）
- enforce 触发 = **一次性 per-trigger API/CLI**（非 cron payload sticky）；cron 永远 dry-run 默认；首次 9-25 人工 enforce 验通管线后，才定义后续 auto-enforce 的 flip trigger（带 audit + rollback-on-anomaly）
- **wire ci_overlap+robust** 从 db→lift_to_multiplier 4 调用点，或改 spec 风险模型承认 validated 不可达 + 只有降级能 auto-fire（当前 validated 分支死代码）
- **幂等 + 迟滞**：phase + last_reverified_at（首次后不再自动 re-run）+ 迟滞带（连续 N 周或 EMA smoothing 才升降级）+ post-60 月频非周频 re-run（防 lift 边界振荡→×0.1↔×0.5 周翻）
- **回滚 + 审计 trail**：per-dimension 版本表（非删整 db）+ 原子读（version id 快照防 torn read）+ 审计 trail（old→new multiplier）+ harness→pending→review→approved 门 + shadow 模式（enforce 前算候选排序 delta 不 apply）
- **修 DIM_ARM_MAP 重复 breakout 键**（evaluation.py:242 vs 249：合并意图或重命名 + 文档 min-multiplier 放大风险——弱 conditioning 因子 lift<1 days≥60→×0.1 拖垮整个 breakout 臂）

### R4：不破坏 lift_to_multiplier 接线
- lift_to_multiplier（evaluation.py:195）纯函数不变，只改 registry 读法 + 4 调用点传 ci_overlap/robust

### R5：共享 contract + 边界测试（消解 mock tautology）
- **定义共享 contract**（db schema + harness 输出格式模块）让 mock 和真 harness 都遵守——消除 mock tautology（mock 发明格式循环自证，9-25 真跑炸）
- 边界测试：db 写失败（磁盘满/权限）/ 部分写（2/17 维→其余 fallback）/ subprocess timeout（抄 intraday.py timeout=110 范式）/ 并发执行（两 evaluation_backtest 同跑）/ enforce flag 类型混淆（string 'true' vs bool True vs int 1）
- safeguard/fallback TDD 在 contract 定后高价值（dry-run-vs-enforce 破坏性 + db-missing-fallback 可靠性）

## 3. 受影响文件（v2 补 scoring.py + verifier.py）

| 文件 | 改动 |
|---|---|
| `backend/scheduler/executors/backtest.py:115-167` | evaluation_backtest 两门 + 自动跑 harness + enforce flag + 修 --baostock-history |
| `backend/candidate_funnel/evaluation.py:48` | DIMENSION_LIFT_REGISTRY → `_load_lifts_db()` OVERLAY 动态读（cached-TTL + fallback 冻结 + provenance） |
| `backend/candidate_funnel/evaluation.py:241-250` | DIM_ARM_MAP 重复 breakout 键修（合并/重命名 + min-multiplier 风险注释） |
| `backend/candidate_funnel/evaluation.py:254-272` | lift_for_arm 改读 db 动态值 + 传 ci_overlap/robust |
| `backend/strategies/funnel/scoring.py:58-89` | gene_multiplier 调用传 ci_overlap/robust（5 gene 因子热路径） |
| `backend/routers/verifier.py:112` | lift_to_multiplier 调用传 ci_overlap/robust |
| `backend/candidate_funnel/evaluation.py:303,314` | _apply_evaluation_layer 两处调用传 ci_overlap/robust |
| `backend/tests/test_r3_enforce.py` | 新建：共享 contract + 边界测（两门/dry-run-enforce/db-fallback/timeout/并发/flag 类型） |

## 4. 验收

- [ ] A1：evaluation_backtest 30 日 DUE + enforce=True → 自动跑 first_board_layer_lift --baostock-history + 写 evaluation_lifts.db（pending 状态，mock 数据测）
- [ ] A2：DIMENSION_LIFT_REGISTRY OVERLAY 读 db 动态值，db 缺/坏 fallback 冻结 + provenance marker 不崩
- [ ] A3：两门——enforce=run+write+REPORT pending（不生效生产读）；promote（人 review 后）才翻 approved 让 registry 读
- [ ] A4：lift_to_multiplier 纯函数不变 + 4 调用点传 ci_overlap/robust（validated 分支可达或 spec 承认不可达）
- [ ] A5：DIM_ARM_MAP 重复键修 + min-multiplier 风险注释
- [ ] A6：runbook（9-25 真跑步骤 + 预期 lift verdict + 失败回退路径）或 @pytest.mark.live integration stub（9-25 后跑）
- [ ] A7：pytest not live 全绿（共享 contract + 边界测覆盖 R1-R5）

## 5. 合规与工程底线自查

- [x] 不臆造：lift 从 first_board_layer_lift day_paired harness 算，days_robust 从 forward_test_records 实数
- [x] 私有数据隔离：evaluation_lifts.db 在 VR_DATA_DIR（.vibe-research/，gitignored）
- [x] 破坏性 safeguard 两门：enforce=run+write+REPORT pending（安全）；promote=人 review 后 apply（破坏）——保护 scoring.py:68 的 5 gene 因子热路径
- [x] 降级范式：db 缺/坏 fallback 冻结值 + provenance marker（不阻塞生产）+ valid-but-wrong sanity check
- [x] 回滚 + 审计：per-dimension 版本表 + 原子读 + old→new multiplier trail
- [x] backfill 无效已诚实标注（真 OOS blocker 非 lazy wait）

## 6. 关联

- [[RB-8]] backlog / §44 v2 P0 (c) / [[S151-评价层]] R3 / [[S180-r3-sizing-wiring]] / [[S159-§44应用规约v2]]
- first_board_layer_lift.py（day_paired_lift harness，需扩展算 days_robust+CI 或 spec 承认不产）
- forward_test.py get_forward_test_summary（评估逻辑，已实现）
- 对抗审：wrs3bqhis（6 视角 verdict needs-revision，3 CRITICAL + 7 HIGH + 16 spec_revisions）
- memory: [[backfill-historical-data-before-waiting]]（RB-8 backfill 试过无效，真 blocker）

## 7. 实现时序

- **现在（9-13）**：spec v2 修订（设计决策不依赖数据）+ 定义共享 contract（db schema + harness 输出格式模块）
- **9-25 数据到**：forward_test 30 天 live → 实现 R1-R5 + 共享 contract mock 测 + 真跑首次评估（enforce→人 review→promote）
- **9-25 后**：60 天复验 DUE（reverify）→ 升降级 verdict（带迟滞 + 月频非周频）
- **关键**：写代码前先定义共享 contract，否则 mock tautology 给假信心（mock 发明格式循环自证，9-25 真跑炸）
