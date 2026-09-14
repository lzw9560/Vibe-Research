# Changelog 2026-09-14

> 本会话累计成果（develop 已 push + vault origin/main 已 push）。

## 方法论/统计（backend）

- **S198 flip** 衰竭 regime 反转→动能延续（gate 5/5 PASS：day_paired lift=1.33 / permutation p=0.002 / regime bull 61.5%+bear 56.6% / 10日 lift=1.28）。gap_classifier.py:199 + fusion GAP_REGIME_ENCODE 补动能延续。
- **S199** 方向感知重测 → grill needs-revision → follow-up 2 测试：breakout 分层 lift（deconfound delta=0，非 breakout 驱动）+ binary gate ablation（无 edge）。**Final: gap "not in fusion" SOUND+STRONGER；"selection edge" 改正为"市场级 forward-return edge + Simpson's paradox（pooled 0.98<1 非每笔 winrate edge）"**。守 §44v2 外推禁令。
- **S201a** cost 可复现（F3 rewire 逐笔 _cost_pct，-1.0% falsified 诚实）。
- **S201b 阶段1** cost-only（RTC 0.70→0.15 + 14 脚本 3 类修 + cost-sweep BH 校正，§44 net -0.46% falsified）。阶段2 exit-optimism pending。
- **S201c** gap 前视修复（candidate 语义+arity bug+case 库）。
- **S202** get_kline+IC/IR+行业中性化（Spearman+Newey-West HAC+layered Jonckheere+demean，21 测绿）。
- **§44v2 P0 R3 写回闭环**（lift_override.py write_override+get_effective_dimension+apply_revalidation，不碰 frozen registry，override 表+新 frozen 实例；evaluation_backtest 自动写回；reader 接线 lift_for_arm/_apply_evaluation_layer/scoring.py:67。days_robust<60 cap ×0.5 已 done S161 R8 核实非重做）。§44v2 闭环结构上真通。
- **M4 edge-type 后端标注修** 5 类（verifier 去硬编码全 selection + overnight_gap 错标修 + population/path 诚实标注）。17 维度标对：selection(12)/path(path_lift)/population(low_volatility)/event(ofi/seal/bid_ask)/overnight_gap(gap_window_lift)。
- **backfill 2018** priority 320 股 8 年（OOS unblock，2018-2023 in/2024-2026 out 可跑）。

## 前端 IA（frontend）

- **Track A**：字体 Inter→Geist + primary 降饱和 89→75% + glass shadow tint 蓝黑 + cross-cutting CSS（tabular-nums/focus-visible/smooth scroll）+ GlassCard tier prop（primary/次/sub）。
- **Track B**：4 入口 IA（今日/盘面/持仓日志/复盘）+ CTA脊 NextStepBar + 信号诚实化 banner + PipelinePage 重定位 479→~190 + PortfolioPage 删空壳 tab 4→2 + nav 4 主入口 flat rail。
- **Track C**：多维度 IA 5 线（时间/选股/验证/策略/认知）各自闭环 + 7 状态灯汇总 + 跨线 drawer + fork-aware PipelinePage（@xyflow 9 步骨架+5 线横穿+fork 岔路）+ 风控横切 RiskBadge + 数据底座 /data + /图谱 认知线 + 共享组件 lines/。
- **Track D**：M1 席位 cross-cutting（选股 fork卡+盘后榜 SeatRankingBoard+per-stock StockSeatCard）+ M2 Cmd+K 命令面板（今日"研究深挖"→战法/因子/量化模型/图谱/数据 lazy-load）+ M3 M1-M7 规划态占位卡（/quant-models，live/规划态诚实标）+ M6 焦点日全局切（FocusDayStrip T-1/T/T+1，今日/复盘/持仓/盘面 跟切重拉）。
- **Track E**（跑着）：A3 财报季日历 + A4 OFI 提升可达 + A7 edge-type 前端筛 + A8 因子→§44verdict 直达。
- **路由修复**：404 catch-all（NotFound）+ 2 lossy redirect（/risk-dashboard→/risk，/workflow/topology→/topology）+ 4 孤儿页恢复（/intel /debate /strategy/funnel/forward-test /config）+ 2 lossy redirect（/value-verdict→/multiline，/workflow/pre-market→/limitup/premarket）+ 删板块 broken tab。
- **funnel/前瞻恢复**（/value-funnel + /prediction 路由，原 redirect 走致孤儿）。
- **watchlist 迁 backend DB**（apiWatchlist 跨设备同步 + localStorage fallback）。
- **PipelinePage tsc 修**（ReactFlow named import+dagre.graphlib+antd+unused）+ JournalWinRateCurve formatter type-clean。

## 知识图谱（vault origin/main）

- **graph-redesign 8 专家 verdict 落图谱**（4 CRITICAL 缺口补：执行层 pipeline_task/scheduled_task 实体 + 五域因果链 policy→expectation_gap→sector + behavior_type + §44v2 闭环 BROKEN 标；+10 新实体+23 关系+18 规则+5 动作+15 code-alignment+12 双语 2 行）。
- **gap-theory S198 flip** 4 处更新。
- **archify 项目架构图双语 2 行** + 5 子模块深度架构（datahub/strategies/s44-verifier/scheduler/knowledge-graph）。

## workflow/verdict（多专家对抗审）

- **graph-redesign**（8 专家，404k tokens）：增量改进+局部重构执行层/因果链。
- **前端审计**（6 视角）：HIGH 4 孤儿页+lossy 链（已修）+ MEDIUM 剩余 + LOW 1853 LOC 孤儿。
- **S199 grill**（6 视角 needs-revision→follow-up）：gap edge 混淆+binary blind+underpower → 2 测试定夺（not in fusion SOUND+STRONGER）。
- **IA deep-refine**（6 专家）：additions A1-A11 + gaps G1-G12 + design D1-D6 + must-decide M1-M6（用户逐项定：5 线+风控横切+数据底座+多线看+fork图+席位 cross-cutting+Cmd+K+M1-M7 卡+edge-type 先修后端+不实现图谱可交互+焦点日全局切）。

## 待办（pending）

- root junk rm（backend/assets/gep + 根 package.json + node_modules 23M）—— 待用户确认
- S201b 阶段2（exit-optimism 修 stop gross line 172 只 stop-side + journal version preserve）—— 承重+破坏冻结待用户定
- backfill full 5230（冷门股，priority 320 功能够）
- 知识图谱 P3（跨项目关系：TradingAgents 30 策略 §44 验证 / a-Plate STI↔Vibe 情绪校准）—— M5 不实现图谱可交互，P3 跨项目内容也 pending
- S199 open（regime-conditional edge bear-day + s199_s44_verify.py Section C overlap bug）—— 跑着 fork
- Track E（A3/A4/A7/A8）—— 跑着 fork
