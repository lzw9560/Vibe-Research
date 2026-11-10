# S246 tasks · 维护模式激活

## Phase B · 低风险可逆（已完成 2026-11-10）

- [x] 建 spec S246 目录 + spec.md
- [x] hithink-finance symlink：`/usr/local/bin/hithink-finance -> /Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/hithink-finance`（不改 6 plist，全局生效）
- [x] DB 分诊 disable falsified 战法回测：`s066_validation_checkpoint` / `daily_backtest_run` / `forward_test_backfill` enabled=0
- [x] DB 修 daily_full_pull cron：`35 17 * * 0-4` → `30 19 * * 0-4`（修 depends_on trade_journal_daily 19:00 时序倒挂）
- [x] home 数据泄漏诊断：~/.vibe-research 有 4 stale first_board_scores_*.json（9-1~9-4）+ logs/feishu 32K

## Phase C · 系统配置

- [x] **重启 backend 激活 6 practitioner 监控**（2026-11-10 完成）：`launchctl kickstart -k gui/$(id -u)/com.vibe-research.backend`，PID 599→20882，6 任务全 FOUND enabled=1，count 57→63
- [~] **VR_HEALTHCHECKS_URL 跳过**（用户决定 2026-11-10）：cron 线程死无外部告警盲区暂留（11-03 nightly-review 静默断同类温床未闭合）。data_ops.py:187 executor 仍 skip。后续若接：用户注册 healthchecks.io check → PlistBuddy Add → 重启
- [ ] **home 数据收口**（盘后做，待用户确认）：mv ~/.vibe-research/logs/feishu → .vibe-research/logs/feishu + symlink 转接；4 stale first_board_scores_*.json 删除（破坏性待确认）
- [x] **seed.py daily_full_pull cron 留痕同步**（2026-11-10）：seed.py:1042 cron `35 17`→`30 19` + 注释 + logger 文案

## 附带 runner-up（2026-11-10 推进）

- [x] combo_notify daily 推送 disable（combo_daily_notify enabled=0，combo FALSIFIED）+ docstring 改标 FALSIFIED（regime_gate_combo_log 保留 enabled=1，settle 流程日志）
- [x] commander_runner.py:375 stale "项目迄今最强 edge weight 0.5" → "FALSIFIED 2026-11-08"
- [x] CLAUDE.md §1.2 §44 v2 "P0 待落地" → "P0 已落地（核于 2026-11-10）"（grep 核 lift_to_multiplier verifier.py:135 / days_robust evaluation.py / r3_enforce seed.py:384 三项真落地）
- [ ] **僵尸代码归档（medium 级，blast radius 大，待 spec 或授权）**：
  - tail_dip：backend 已 410-sunset（router `dependencies=[Depends(_falsified_gone)]`），只前端 TailDipDeviationPanel.tsx + IntradayCockpit 清理剩
  - sector_rotation endpoint（routers/strategy.py:181-273）：可 410-sunset 像 tail_dip；**sector_cycle.py 模块不能归档**（trend_swing_arm.py:45 + dimension_registry.py:48 live 依赖 aggregate_sectors/classify_phase/zt_count_today）
  - **market_scan.py 不能归档**（workflow.py:302 + strategy.py:254 live pipeline 依赖）
  - 前端 SectorRotationNode（SelectionPipeline.tsx:225，sharedSectorRotation=true 默认已不渲染）+ useSectorCycle/useSectorRotation hooks + api.ts:241 清理
  - test_sector_cycle.py 更新
