# S244 · 红利低波 512890 仓位规则落地（PaperPortfolio + 飞书提醒）

> 状态：**已实现 Phase 1**（2026-11-08，AC1-AC5 全过，AC6 Phase 2 可选）
> 编号：S244 | 类型：feat | 分级：medium（涉及交易信号，不可跳过 spec）

## 1. 问题 / 目标

选股 alpha 穷尽（短线+行业轮动+基本面 3 族+combo/inst/跟庄全 falsified）后，practitioner reframe 落地——散户 edge 在 sizing/风控/行为不在选股（memory `expert-review-2026-11-08`）。项目已落地 underpricing yield 看板（S243），**但 sizing/仓位规则没落地**（gap）。

memory `dividend-low-vol-base` 给了规则（仓位 20-30% + 长期持有 + 不设止损设总仓 -15% 减仓 + 季再平衡），`portfolio-allocation-backtest-2026-11-08` 回测验证：
- 20% 仓位 Sharpe 最高 1.223 / 30% Sharpe 1.035（最优区间）
- drawdown control（-15% 减半）边际效果小（512890 低波减半错过反弹）→ 简化
- 30% 仓位 regime 稳健（3 个 regime 都正 5-6%/Sharpe>1/回撤<5%）

本 spec 把规则落地：512890 底仓 arm（arm_status）+ 季再平衡 cron + drawdown 监控 cron + 飞书提醒。非自动交易（PaperPortfolio 无 broker），提醒辅助用户手动执行。

## 2. 需求清单

| # | 需求 | Phase |
|---|---|---|
| R1 | arm_status 加 `dividend_low_vol` arm（is_active=1, weight_override=0.25, 默认 25%） | 1 |
| R2 | 季再平衡 cron（每季初提醒调回目标仓位 25%） | 1 |
| R3 | drawdown 监控 cron（512890 从峰值跌 -20% 提醒减仓，回到 -10% 恢复） | 1 |
| R4 | 飞书提醒：季再平衡 + drawdown 触发 + 仓位状态 | 1 |
| R5 | /api/portfolio/position 端点（当前仓位 + arm_status + drawdown 状态） | 2（前端可选） |
| R6 | 不自动交易（PaperPortfolio 模拟，真盘用户手动） | 全局 |

## 3. 受影响文件

**新增**
- `backend/strategies/divlowvol_arm.py`——512890 底仓 arm（仓位规则 + drawdown 状态）
- `backend/scheduler/executors/portfolio.py`——`portfolio_rebalance_remind` + `portfolio_drawdown_monitor`
- `backend/tools/_setup_divlowvol_arm.py`——初始化 dividend_low_vol arm（is_active=1, weight=0.25）
- `backend/tests/test_portfolio_rule.py`——季再平衡 + drawdown 触发逻辑

**修改**
- `backend/scheduler/executors/__init__.py`——`_executors` 注册 2 个 + wrapper
- `backend/scheduler/seed.py`——2 cron tasks（季初再平衡 + 日 drawdown 监控）
- `backend/tests/test_task_executor.py` + `test_regression_bugs.py`——`_EXPECTED_TASK_TYPES` 两处同步

## 4. 验收标准

- **AC1** `dividend_low_vol` arm 写入 arm_status（is_active=1, weight_override=0.25）✅ 待实现
- **AC2** `portfolio_rebalance_remind`：每季初（1/4/7/10 月首个交易日 09:15）发飞书提醒调回 25% 仓位 ✅ 待实现
- **AC3** `portfolio_drawdown_monitor`：512890 从滚动峰值跌 -20% → 发飞书减仓提醒；回到 -10% → 恢复提醒；未触发 → skip 不打扰 ✅ 待实现
- **AC4** drawdown 阈值 -20%（非 -15%，基于回测：-15% 减半边际效果小，放宽 -20%）✅ 待实现
- **AC5** 不自动交易（PaperPortfolio 模拟，提醒辅助手动）✅
- **AC6** /api/portfolio/position 返回当前 arm_status + drawdown 状态（Phase 2 可选）✅ 待定

## 5. 仓位规则（基于回测验证）

- **512890 底仓 25%**（20-30% 最优区间中值，Sharpe 1.035 @ 30% / 1.223 @ 20%）
- **季再平衡**（每季初调回 25%）
- **drawdown control 简化**：-20% 减仓提醒（非 -15% 减半，回测显示 -15% 边际效果小）
- **regime aware 非强制**：30% 仓位 regime 稳健，不强制 regime 切换；破发潮 regime 回归时打新暂停（S243 红线 regime-aware 联动，待破发潮触发）
- **现金 return**：GC001 逆回购 sweep（S243 已实现，底仓闲置资金 2-15%/年）

## 6. 合规自查（§1 弱合规）

- ✅ 工程底线——不臆造：512890 数据走 akshare 公开接口，仓位规则基于回测验证（`explore_portfolio_allocation.py`）
- ✅ 工程底线——私有数据隔离：无持仓/API key 涉入（arm_status 只存仓位规则状态，不存用户真盘仓位）
- ✅ 工程底线——防封：512890 走 akshare fund_etf_hist_em（非东财 datacenter，无熔断风险；但走 circuit_breaker 更稳）
- ✅ 弱合规：资产配置层（分红现金流+低波），非个股推荐，非选股 alpha；提醒辅助手动，用户最终决策

## 7. 非自动交易说明

PaperPortfolio 无 broker / xtquant / qmt——提醒 + 规则辅助用户手动执行。飞书推送（季再平衡 4 次/年 + drawdown 触发，不轰炸）。

## 8. 测试

- `test_portfolio_rule.py`：季再平衡触发 + drawdown -20% 触发 + -10% 恢复 + 未触发 skip
- `_EXPECTED_TASK_TYPES` 两处同步（test_task_executor + test_regression_bugs）
- TDD：先写测试（RED）→ 实现（GREEN）→ 重构

## 9. 依赖

- 512890 数据：akshare fund_etf_hist_em（已验证 1888 天 2019-2026）
- arm_status：trade_journal.db（已有 4 arm，加 dividend_low_vol）
- 飞书：notification_service（S243 已验证到达）
- 回测验证：`explore_portfolio_allocation.py`（commit 3c7ca6b）
