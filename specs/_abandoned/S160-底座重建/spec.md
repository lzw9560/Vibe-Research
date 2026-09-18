# Spec: S160 — 底座重建方向 + re-scoped scope（世纪大辩论 verdict + spec-grill v2）

> 状态：草案 v2（世纪大辩论 10 视角收敛 + grill 10 holes + 开源调研 + spec-grill 37 holes/8 refuted，2026-09-06）
> 关联：grill-foundation-holes-2026-09-06 / open-source-quant-framework-research-2026-09-06 / S159 / multiline-strategy-direction / spec-grill output
> 分级：large（多组件+逻辑闭环+架构）—— feature 分支 + grill + 分步实施（S161-S166 v2 增量）
> v2 修订：spec-grill 8-lens 45 holes/37 real/8 refuted 后镜像修 S161-S166——PBO N=1 空壳 / Bonferroni K=20 over-correction / gap=event-edge vs selection verdict category mismatch / Recorder 数据态不锁 / Trades.entry_price vs Executor / simulate_holding 拆分重构非复用 / day_paired+walk-forward+Bonferroni+IC 归 verifier 非 Accounting / PIT store=deferred lake / S166 resurrect 非 port / lift_to_multiplier 接线非 REGISTRY 改标 lipstick / tools/ 前缀不改（refuted）/ CronScheduler 改性删（已 done）。

## 0. 问题

底座方向（辩论裁决 + grill 定 scope）经 grill 8 视角审查找 10 承重漏洞（77% verify 真）+ 世纪大辩论 10 视角辩论。10 视角强收敛：否 B（再辩论=拖延），建 edge-agnostic 诚实测量基建 NOW，gap=hypothesis/证伪-pending 非 verified edge，defer fill/multi-line/gap-capture，修 reuse rot，reframe 三层。分歧经综合：engine 三层解耦（非 no-fill 降级），gap verify-now via 基建（daily-bar 非 60 天 intraday），scope medium-thin。

核心命门（grill #1+#2）经辩论**化解**：①"gap 未 verified 却当 edge 建基建"——建的是 edge-agnostic 验证基建（判定器），非 edge-capture 基建；gap 是 daily-bar 可 NOW 跑 §44v2 verify/falsify（非 60 天 intraday）。②"design-agnostic 引擎不可能"——engine 三层解耦：Decision+Accounting design-agnostic / Executor 可插拔 fill（deferred），非 no-fill 降级。

**spec-grill v2**（37 真洞/8 refuted）修 S161-S166 细节：方法论 bug（PBO N=1/Bonferroni K=20/gap event vs selection category mismatch/DSR lenient 静默/n<60 vs R6 矛盾）+ 架构 bug（Trades.entry_price vs Executor/simulate_holding 拆分重构非复用/day_paired+walk-forward+Bonferroni+IC 归 verifier 非 Accounting）+ 数据 bug（Recorder 数据态不锁/前复权 mutation/gap 数据链错描 em_zt_topic_pool 非 ths）+ reuse rot（lift_to_multiplier 接线生产非 REGISTRY 改标 lipstick）+ S166 resurrect 非 port（cb54a96 add→f9898f9 delete 同在 develop own history）。

## 1. 目标

底座重建 = 建 edge-agnostic 诚实测量基建（验证任何候选 edge 的判定器，不依赖 gap 是否 verified）+ UI 契约先行 + gap hypothesis 跑 §44v2 verify/falsify（两 verdict：event population + selection）+ defer 方向绑定件 + 修 reuse rot（lift_to_multiplier 接线）+ reframe 三层。不在未验证 edge 上建 capture 基建。

## 2. 需求清单（re-scoped core v2，design-agnostic 建 NOW）

1. **§44v2 验证框架**（priority 1，design-agnostic + edge-independent，S161 v2）：wire `vendor/skill-backtest-overfit`（DSR lenient 透明标 dsr_method / PBO N<2→N/A 非 crash / PurgedKFold.split() 非 cross_val_score_purged / haircut）+ 合并 `backend/tools/` 散落 day_paired_lift+permutation+Bonferroni/BH+walk-forward（两集分离：Parameterize-ROOT 集 10 + Merge-source 集 12）为单一 verifier。Verdict dataclass 含 edge_type/tradeable/event_metrics/event_status/dsr_method/not_validated/n_effective/updated_*/data_snapshot_id。Recorder pin 数据态（as_of + 完整 return series 非 hash + 两复现判据）。gap run 出两 verdict（event population K=1 t-test + selection K=small BH），42 天结构性 underpowered。lift_to_multiplier 接线生产（days<60→×0.5 替代直读冻结 weight_multiplier）。详见 S161 v2。
2. **反前视回测引擎**（priority 2，三层解耦，S162 v2）：Decision+Accounting 层 design-agnostic——Decision 取 Trades input（R1a NOW，signal_date+fill_type，entry_price Executor 填非 Decision 带；R1b generate_trade_decision 待 qlib gh-proxy 源码核实）/ Accounting **只算 path return+cost+survivorship**（接 filled Trades+bars，喂 S161 verifier raw return series；**不含 day_paired/walk-forward/Bonferroni/IC**——这些归 verifier，IC 是 cross-sectional scalar ≠ return series 是 category error）/ Executor 可插拔 fill（T+1OpenFill offset≥1 默认，IntradayConditionalFill stub 返 untradeable，refused fills 无 return）。**simulate_holding 拆分重构非复用**（FillPolicy.fill→Executor / path_return→Accounting）。**PIT FeatureStore defer**（= 被砍 lake 换名无消费者，S163 §5 改"读 cache"；re-introduce 用 SQLite+as_of 非 parquet/duckdb 未装）。借 qlib Nested Decision Point + backtrader 0/-1+cheat_on_open（借鉴模式，batch enforcement = FillPolicy offset）。详见 S162 v2。
3. **数据质量门 + 轻量血缘**（priority 3，design-agnostic，S163 v2）：源边界 schema 校验 + 血缘记录（script+commit+**as_of/data-snapshot-id** 非 content hash + write-once/append-only + recompute-verify acceptance）。**砍 lake/ETL**（无消费者 YAGNI）。诚实 scope（lineage = provenance trail + 可复现脚手架；sophisticated fabrication 仍需人读 raw output，不外推）。**tools/ 前缀不改 backend/tools/**（refuted——cwd-relative backend-cwd 约定，parents[2]+evaluation.py 确认；real fix = 硬编码绝对路径 Vibe-Research-S151 → VR_DATA_DIR，两者非互换）。详见 S163 v2。
4. **防封 backbone robust + secrets gate**（priority 3，design-agnostic，S164 v2）：breaker 持久化（SQLite state 跨进程）+ per-端点拆 **2 组**（{push2his/push2/fflow} + {datacenter}，非 4 组——sina/fflow 已 separate/共享 host）+ **proxy_pool 降级 optional/exploratory**（非 acceptance gate；MITM 真 fix = lint/grep CI no direct requests.get on eastmoney/tencent，全走 em_get；em_get 现有 system-proxy fallback 保）+ hithink key 轮换入 §1.2 secrets gate。详见 S164 v2。
5. **UI 契约先行**（priority 1，contract-first，S165 v2）：DimensionValidationCard UI（mock 先跑，字段匹配 S161 v2 Verdict——5 值 enum 含 not_validated + edge_type/tradeable/event_metrics/dsr_method + 三窗口 mean+中位+胜率+base_rate 不算 IC/lift + overfit 占位 PBO N/A single-strategy vs 待建 区分 + field source map ci_low/updated_commit null 标"待"非臆造）+ 实验记录 UI。UI 数据形状锚定 **S161 v2 Verdict + Recorder schema**（**drop evaluation_lifts.db phantom 锚**）。gap 非 REGISTRY 维是 §3 event verdict。UI 先行非被动呈现（[[ui-first-implementation-order]]）。详见 S165 v2。
6. **Trade Journal + Risk Ledger**（priority 3，design-agnostic risk carve-out，S166 v2）：**resurrect S149 journal.py/excursion.py/at_risk.py/risk_rules.py/attribution.py/inbox.py from develop own git history**（cb54a96 add → f9898f9 deliberate delete，同在 develop own history，非 feature→develop port；extract via `git show cb54a96:backend/<file>`）+ re-wire 8 consumer files（app.py/chat.py/daily_review.py/candidates/review/topology/frontend）。**drop routers/risk.py port**（已在 develop S055/S126 market-risk dashboard，勿覆盖；16 端点全在 routers/journal.py）。**drop backtrader Analyzers**（YAGNI 无消费者，excursion/at_risk plain functions）。Investigate f9898f9 why-deleted before resurrect。Honest risk label（stop 对 gap-down 仪式非保护）。详见 S166 v2。

## 3. defer（方向绑定/YAGNI，不建 NOW）

- fill Executor impl（IntradayConditionalFill，gap 方向绑定，grill #2）。stub 返 untradeable。
- 多线路骨架（line_id/注册/资源分配，零 validated 线路 YAGNI，grill #4）。只建 shared infra 接口。
- gap capture/intraday 执行（封板检测/pre-seal buy，方向层，需 60 天 live 积累）。
- OMS / 组合层风控（风控 core 无牙，依赖 OMS，grill #8）。
- lake/ETL/血缘重 + **PIT FeatureStore**（v2 加，S162 R4 = 被砍 lake 换名无消费者，grill yagni #20）。
- edge emergence/decay 监控（无 edge premature，grill #9）。只留数据质量监控。
- generate_trade_decision signal→Trades 自动生成（待 qlib gh-proxy 源码核实，S162 R1b）。

## 4. 修 reuse rot + reframe 三层（hygiene v2，adopt A mechanics）

- **lift_to_multiplier 接线生产**（v2 修，CLAUDE.md §1.2 P0，治 grill honesty/reuse_rot 证"REGISTRY 改标是 lipstick"）：`evaluation.py` lift_to_multiplier 加 days_robust 参数 + days<60→×0.5 provisional cap + 接 _apply_evaluation_layer:199/205 + strategy_funnel_registry:434 替代直读冻结 weight_multiplier。**删"REGISTRY 改标"交付**（已完成 evaluation.py:43-46，relabel 是化妆非 wiring）。
- harness 9 脚本 ROOT 参数化（绝对路径 `Vibe-Research-S151` → VR_DATA_DIR 或 Path(__file__).parents[2]，两者非互换；**tools/ 前缀不改 backend/tools/** refuted——cwd-relative 约定）。
- ~~CronScheduler 改性~~（v2 删，已 done——scheduled_tasks.py:2/1012/2258 已自标 cron-like fire-and-forget 非 DAG，无 rot 可修）。
- reframe 三层为"1 built infra + 2 conceptual（selection=展示终态, direction=deferred 未建）"，无层间 producer-consumer 契约。regime gate 移 timing 层（grill #5）。
- 落地名门更新：S150 done / §44v2 spec-only / intraday direction-layer 非 design-agnostic（grill #7）。
- anti-overfit 措辞改"重用 §44v2 部分（walk-forward+Bonferroni/BH），PBO/CSCV/DSR/Harvey wire backtest-overfit"（grill #6，v2 PBO N<2→N/A 透明）。

## 5. gap 处理（hypothesis 非 verified edge）

- gap = 14 天 underpowered hypothesis（t=10.65 naive 池化，net+0.45% WR46.5%<50% 薄，S159 自标 underpowered）。
- NOW 跑 §44v2 重方法论 on gap（**re-run first_board_premium_baseline.py --days 42** 读 gene_scores.db eastmoney_live dates + **em_zt_topic_pool**（东财涨停池，非 ths_limit_up_pool 同花顺）per-date + baostock kline → regenerate baseline.json ~42 天，再跑 gap_window_lift on regenerated baseline；gap return series 读 baseline.json 非 kline_cache 直接，kline_cache 仅一字板 filter）。**非 60 天 intraday**——gap 是 daily-bar 量 D 收盘→D+1 开盘。day-paired 非池化+permutation null+**Bonferroni/BH K=1 或小 K（gap 实测假设数，绝不引 §44v1 ~20 因子数不同 family）**+walk-forward（42 天 0 窗→优雅降级标 insufficient skipped 非静默空）+DSR n_trials=20（唯一跨实验校正，justify 为 judgment）。
- **两 verdict**（v2，治 grill honesty 证 gap=event-edge 非 selection）：population event-edge verdict（K=1 DSR n_trials=1 edge_type=event，day-clustered t-test+binomial，**非 lift/permutation/Bonferroni 测 selection**）+ selection verdict（K=small BH edge_type=selection）。"gap 是否 edge"由 event verdict 答。
- verdict：robust edge / 仍 underpowered（42 天结构性 underpowered days<60，expected，NEVER robust/证否）/ 证否（须 days≥60 且 lift<1）。
- gap capture/intraday defer 到方向层（60 天 live 积累，非 NOW）。
- Chen2017 nuance：gap 是大户的不可复制，但 retail 可 intraday 打板捕获（非完全不可复制）——prior 倾向薄/难，但 verify via 基建（便宜，daily-bar NOW）。

## 6. 受影响文件

- 新建：`specs/S160-底座重建/spec.md`（本 spec）+ S161-S166 v2 per-component specs。
- §44v2 验证框架（S161 v2）：新建 `backend/s44_verifier/`（verifier+recorder+wiring）+ wire `vendor/skill-backtest-overfit` + 改 `backend/tools/` Merge-source 集 12 脚本合并 + Parameterize-ROOT 集 10 脚本参数化 + 改 `first_board_premium_baseline.py`（days_back+em_zt_topic_pool+口径一致）+ 改 `evaluation.py` lift_to_multiplier 接线。
- 反前视引擎（S162 v2）：新建 `backend/engine/` 三层（decision/accounting/executor/fill_policies）；~~pit_store.py defer~~；拆分重构 `kline_returns.py` simulate_holding。
- 数据质量门+血缘（S163 v2）：新建 `backend/data_quality/` 模块；改 `backend/tools/` 10 脚本 ROOT 参数化（绝对路径）。
- 防封（S164 v2）：改 `circuit_breaker.py`（持久化+拆 2 组）+ em_get system-proxy fallback 保 + lint/grep CI gate（非 proxy_pool 服务）+ secrets gate。
- UI（S165 v2）：新建 `frontend` DimensionValidationCard + 实验记录页 + verifier-contract.ts 锚 S161 v2。
- Trade Journal+Risk Ledger（S166 v2）：resurrect S149 6 模块 + 4 测试 from cb54a96 git history + re-wire 8 consumer files + routers/journal.py（drop routers/risk.py port）。
- 修 reuse rot：改 `evaluation.py`（lift_to_multiplier 接线）+ 10 harness 脚本（ROOT 参数化绝对路径）；~~CronScheduler 改性删（已 done）~~。

## 7. 验收标准

- [ ] S161-S166 v2 per-component specs 写完（design-agnostic + edge-independent 验证，spec-grill 37 真洞修）。
- [ ] §44v2 验证框架 wire backtest-overfit（DSR lenient 透明 / PBO N<2→N/A / PurgedKFold.split() 调用非裸 import / haircut）。
- [ ] gap 跑 §44v2 重方法论（re-run first_board_premium_baseline.py --days 42 em_zt_topic_pool → 两 verdict event+selection → 42 天 underpowered 预期）。
- [ ] 引擎三层解耦（Decision Trades input R1a NOW / R1b 待 qlib 核实 / Accounting path return+cost+survivorship design-agnostic 不含统计 / Executor pluggable fill / simulate_holding 拆分重构 / PIT defer）。
- [ ] reuse rot 修（lift_to_multiplier 接线生产 + 10 harness 绝对路径参数化；CronScheduler 删已 done）。
- [ ] UI 契约先行（DimensionValidationCard mock 跑 + 锚 S161 v2 harness 契约，drop evaluation_lifts.db）。
- [ ] 防封 backbone（breaker 持久化 + 2 组拆 + em_get system-proxy + lint/grep CI + hithink key 轮换）。
- [ ] Trade Journal+Risk Ledger resurrect S149 from cb54a96 history + re-wire 8 files。
- [ ] pytest -m "not live" --deselect (newsradar+s032+s040) 全绿。

## 8. 合规与工程底线自查

- [x] 不臆造：gap §44v2 重方法论实算（day_paired+permutation+Bonferroni/BH+walk-forward+DSR），禁 naive 池化；gap 数据链诚实（baseline.json 非 kline_cache 直接；em_zt_topic_pool 非 ths）；generate_trade_decision 待 qlib 源码核实非凭未核实签名。
- [x] 私有数据隔离：数据 cache 写 .vibe-research 不进 git；hithink key 轮换 + secrets gate；Recorder pin as_of 数据态。
- [x] em_get 防封：lint/grep CI no direct requests.get（非 proxy_pool 服务）+ breaker 持久化 + 2 组 + em_get system-proxy fallback。
- [x] §44 降级参考性建议：v2 强化"前置 sanity+回溯主场"，不强制不阻塞。
- [x] verdict 外推禁令：gap 标 hypothesis 非 verified，跑 §44v2 后才称 robust/证否；selection-falsified 带 note 不外推"无 edge"；edge_type 结构化。
- [x] 不闭门造车：10 专家辩论 + 开源调研 + 文献（Chen2017/Hua'an/Harvey/López de Prado）+ spec-grill 8-lens 对抗验证修 37 真洞。

## 9. 分级

**large**（底座重建，多组件 + 逻辑闭环 + 涉及架构）。feature 分支 + grill + playwright 验收。分步实施（S161-S166 v2 增量，每步 §44v2 验证+复盘）。per-component v2 specs 已写完（spec-grill 过，37 真洞修）。priority 1：S161 v2 §44v2 验证框架 + S165 v2 UI 契约先行并行 → gap §44v2 run 两 verdict → S162 v2 引擎（priority 2）→ S163/S164/S166 v2（priority 3）。
