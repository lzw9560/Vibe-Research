# S066 实施提示词（交给 Claude Code）

## 你的任务

实现 S066 策略特定漏斗架构重构。spec 在 `specs/S066-策略特定漏斗架构重构/spec.md`，
计划在 `plan.md`，原子任务在 `tasks.md`（113 个），因子全景表在 `factor-catalog.md`（74 条）。

**严格按 Phase 顺序实现，不跳步。** Phase 0a-0e 串行，Phase 1/2 可并行，Phase 3 依赖 Phase 1。

## 项目约定（AGENTS.md）

- 全程中文交流；commit message 中文，代码标识符英文
- 未经确认不 git commit/push
- 不臆造数据 / 私有数据隔离 / em_get 防封
- 后端：`cd backend && ../.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8900`
- 前端：`cd frontend && npm run dev`（vite 5899）
- venv 在仓库根 `.venv`（Python 3.11.8）
- 数据库在 `.vibe-research/`（gitignored）
- 测试：`cd backend && ../.venv/bin/python3 -m pytest <path> -v --no-cov`
- 大改动走 feature 分支 `feature/S066-<module-slug>`，合并后删分支

## Phase 0a 第一步（立即开始）

1. 从 `.vibe-research/gene_scores.db` 取全部 6537 条 (date, code) 对
2. 用 BaoStock（`baostock` 已装）批量拉 qfq 日K（adjustflag=2，含 turn/pctChg/amount）
3. 对每条匹配 next_bar：取 open/close/high/low + 涨停价
4. 计算 gap_pct + fill_rate + benchmark_A + benchmark_B
5. 输出 `.vibe-research/backtest_samples.json`
6. 写分析脚本输出因子 r/CI/p 值到 `factor_significance.json`

BaoStock 已验证可用（2026-08-14 实测）。备用源：新浪 API + kline_multi。

## 关键设计决策（不可偏离）

1. 策略分权重不是拍脑袋——由 Phase 0b 全样本回归结果确定，CI 排除 0 才用
2. 3 套权重（涨停类/非涨停类/暴风暴），不是 9 套
3. 天气硬开关——不适配的战法不跑，不是降权
4. 暴风雨天气跑 storm_reversal（逆势涨停子策略），仓位 x 0.3
5. 板块周期是 3 日时序分析（启动/发酵/高潮/退潮），不是单日计数
6. 日历因子：周五 x0.7，节前末日 x0.3（不 x0.0），节后红包确认策略
7. 质量标准待 Phase 0b 验证后才做过滤，验证前仅展示
8. L0-L3 渐进式披露——默认极简，用户点击展开
9. 双层 kill criteria（策略级 >= 5 + 组合级 >= 8/5 日）
10. 动态滑点（按下单量占比计算，不是固定 0.2%）
11. 半 Kelly（0.5x），不用满 Kelly
12. 优雅降级——数据源不可用时降级不崩溃，最后防线是人工输入模式

## 不要做

- 不要跳过 Phase 0 直接实现 Phase 1
- 不要在 74 样本上定权重（等 6537 样本回填后）
- 不要做 NLP 情感分析引擎（用 LLM API 替代）
- 不要做月度/年度效应、北向资金、天地板
- 不要加量比/成交额/游资净流出硬过滤（回测证明降低胜率）
- 不要一上来就实现全部 113 个任务——按 Phase 顺序，每 Phase 完成验证后进下一个

## 文件结构

```
specs/S066-策略特定漏斗架构重构/
  spec.md              # 18 节完整 spec（1595 行）
  plan.md              # 实现计划 + 依赖链 + 时间估算
  tasks.md             # 113 个原子任务
  factor-catalog.md    # 74 条因子全景表
  ui-mockup.html       # 前端交互 mockup
  HANDOFF-PROMPT.md    # 本文件
```

## 实施数据文件

```
backend/data/
  holidays.json              # 节假日日历
  hot_money_seats_preset.json  # 预设游资席位画像
  hot_money_seats.json       # 60 日龙虎榜聚合画像（周更）
  sector_mapping.json        # 雷达赛道 -> 东财行业映射
  sector_stocks.json         # 板块成分股缓存
  ex_dividend_calendar.json   # 除权除息日历

.vibe-research/
  backtest_samples.json      # 6537 样本回填缓存
  factor_significance.json   # 因子回归结果
  strategy_weights.json      # 3 套策略分权重
```

## 开始

从 tasks.md 的任务 001 开始。每完成一个 Phase 写一段总结，不要跳到下一个 Phase 直到当前 Phase 验证通过。
