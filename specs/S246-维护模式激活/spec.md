# S246 · 维护模式激活（让声明的东西做真）

**状态**：进行中（Phase B 已完成，Phase C 待用户确认系统配置）
**日期**：2026-11-10
**分级**：medium（多文件 + 系统配置 + DB 改动，但非新功能/非数据逻辑变更）

## 问题

2026-11-08 做减法定型后声明"维护模式 + 底仓监控"，但运行系统中维护模式**不在跑**：

1. **监控任务纸面**：S243/S244/S245 的 6 个 practitioner 监控任务（yield_repo_remind/yield_cb_remind/yield_ipo_remind/portfolio_rebalance_remind/portfolio_drawdown_monitor/ipo_regime_monitor）executor + seed 代码都写好，但 backend PID 599 于 11/3 启动早于 S244(11/8)/S245(11/9) commit，`_ensure_seed_tasks` 仅 startup 跑一次（`cron_runner.py:164`）。DB 实查 `scheduled_tasks` 57 条，这 6 个 task_type **count=0 全 NOT FOUND**（核于 2026-11-10 sqlite3）。
2. **飞书推空数据 7 周**：6 个 feishu plist PATH=`/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin` 缺 nvm bin，hithink-finance CLI 在 `/Users/lizhiwei/.nvm/versions/node/v24.21.0/bin/` 不在 PATH → exit 127 → 推送送达但 dragon-tiger/hot-stock/index/limit-up 数据段空（自 9-23 迁移起）。
3. **失败无人察觉**：5 failed + 1 degraded 任务静默；daily_full_pull 停 6 周（depends_on 时序倒挂：cron `35 17` 但依赖 trade_journal_daily cron `19:00`）；VR_HEALTHCHECKS_URL 未设 → S188 RB-2 外部死告警 executor 跳过——正是 11-03 nightly-review 静默断 6 天同类温床。

## 需求（3 件激活）

1. 重启 backend 激活 6 practitioner 监控任务（launchctl kickstart）
2. 修飞书 PATH（hithink symlink，不改 plist）
3. 设 VR_HEALTHCHECKS_URL 外部死告警 + 分诊失败任务

## 受影响

- `~/Library/LaunchAgents/com.vibe-research.backend.plist`（加 VR_HEALTHCHECKS_URL）
- `.vibe-research/market_data.db` scheduled_tasks 表（分诊 + cron 修复，已做）
- `/usr/local/bin/hithink-finance` symlink（已做）
- `backend/scheduler/seed.py:1048` daily_full_pull cron 留痕同步（待做，避免 seed 重建回退）

## 验收标准

- [ ] 重启后 sqlite3 查 6 个 practitioner task_type FOUND + enabled=1
- [ ] 手动触发 feishu 推送，dragon-tiger/hot-stock/index/limit-up 数据段非空 + hithink-finance exit code=0
- [ ] VR_HEALTHCHECKS_URL 设值后 data_ops executor 日志不再 "skip no URL"
- [ ] daily_full_pull 11-10 19:30 fire 且 success（cron 已改 30 19）
- [ ] 分诊后无未标注 silent fail（s066/daily_backtest/forward_test 已 disable）

## 合规自查（工程底线）

- **不臆造数据**：分诊 disable 的是 falsified 战法回测（combo/§44/forward_test），属做减法延续非臆造。
- **私有数据隔离**：home 收口（~/.vibe-research/logs/feishu → 项目内 + symlink 转接）闭合 §1.2，待盘后做。
- **防封**：不涉及东财端点裸调，无新增 em_get。

## 风险

- launchctl kickstart 重启会秒级打断在跑任务（建议盘后 19:30 后做，daily_full_pull 已改 19:30 不冲突）
- VR_HEALTHCHECKS_URL 需用户去 healthchecks.io 注册 check 拿 ping URL（不能代注册）
- home 收口 mv 日志目录避开活跃推送时段
