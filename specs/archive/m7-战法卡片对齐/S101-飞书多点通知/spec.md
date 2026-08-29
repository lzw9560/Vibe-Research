# Spec: S101 — 飞书多点通知（T-1 选股 / 9:25 竞价 / 9:35 开盘 / T+1 复盘）

> 状态：✅已实现（2026-08-27）
> 作者：Claude 会话  日期：2026-08-27
> 级别：medium（跨 scheduled_tasks + notification + bidding_monitor + tencent_quote + funnel_cache；不碰外部数据源新增 / 不碰 AI 提示词 / 不碰前端 / 不涉财务验算）
> 流程门：spec.md + issue 层单轮 review；直接 develop（免 feature 分支 / 免完整 grill）
> 依赖：S093 R10（T-1 通知已实现，S101 第1步已修 cron+guard）、S075（first_board_t1_review 复盘基础设施）、S055（bidding_monitor 竞价监控）
> 关联：S098（§44 合规，raw-shadow 口径）、记忆 `first-board-grill`（系统不下单红线）、`grill-reframe-final-verdict`（§44 无 validated edge）

## 1. 问题 / 目标

S093 R10 实现了 T-1 17:15 前瞻选股通知（单点）。但用户盘前/盘中/盘后只收到一条选股结果，盘中开盘表现、竞价确认、T+1 复盘都得被动打开页面看——不能在关键时点主动推送。

**S101 第1步已修**：T-1 通知"结果不对"根因（candidate_funnel_precompute cron 被手改为 16:05，早于 gene_scores 写入完成 → final=0 → 推"0 只"）。已修 cron 回 17:15 + final=0 guard。

**目标（第2步）**：在 T-1 选股通知基础上，新增 3 个时点飞书推送，覆盖一个完整交易日的关键决策时刻：
- **9:25** 竞价确认后：前瞻标的开盘竞价表现（哪些高开/低开/平开）
- **9:35** 开盘 5min 后：前瞻标的开盘表现（实时价/涨跌幅/封板状态）
- **T+1 16:35** 复盘：前瞻标的 T+1 收益评价（均值/胜率/§44 诚实口径）

4 点串成"选股→竞价确认→开盘→复盘"闭环，用户不用盯盘也能在关键时点收到状态。

## 2. 背景

- **T-1 通知（已修）**：`candidate_funnel_precompute` 17:15 跑 `run_funnel('all', F)` → final_cards + dual_count + strategy_map → `_build_premarket_notification_content` → NotificationService.send()。S101 第1步已加 final=0 guard + cron 17:15 迁移。
- **竞价监控**：`bidding_monitor.py` `monitor_auction()` 9:15-9:25 采样，`analyze_final_auction` 产 `AuctionSignal`（code/signal_type/gap_pct）。**只 API 不发飞书**。候选池是 `load_gene_scores` top-N（非 final_candidates）。
- **实时行情**：`astock.tencent_quote(codes)` 批量取实时价（WatchlistBoard useQuote 在用），含 price/change_pct/limit_up_price。
- **funnel_cache**：`candidate_funnel/funnel_cache.py` `save_funnel_result(F, 'all', result)` 17:15 落库；`load_funnel_result(F, 'all')` 读 final_candidates。9:25/9:35/T+1 读此缓存获前瞻标的 code 集合（不重跑漏斗）。
- **T+1 复盘基础设施**：`first_board_settlement.run_t1_premium_review(signal_date)` 对首板流快照候选做 baostock T+1 kline 收益评价 + lift 四态。`first_board_t1_review` task 16:30 跑（首板流专用，**不覆盖 final_candidates**）。
- **NotificationService**：`notification/notification_service.py`，`send(content, route_type="alert", severity="info")`，14 渠道，读 `config.feishu_webhook_url`。
- **§44 口径**：前瞻选股是 raw-shadow（§44 三族 8 月 <2x 无 validated edge）。通知内容标"参考值非执行指令"，不宣称 alpha。T+1 复盘标"§44 未验证，n 样本不足不下结论"。
- **系统不下单红线**：通知只推状态，不触发交易（记忆 `first-board-grill`）。

## 3. 需求清单

### A. 9:25 竞价确认通知（premarket_auction_notify）
- [ ] R1 新 task type `premarket_auction_notify`，cron `25 9 * * 0-4`（工作日 9:25）
- [ ] R2 读 F 日（上一交易日）`load_funnel_result(F, 'all')` final_candidates code 集合；无缓存→跳过不发（不臆造）
- [ ] R3 对 final_candidates codes 调 `tencent_quote` 取竞价/开盘价（9:25 集合竞价完成，有 open_price）；算 gap_pct（open vs last_close）
- [ ] R4 通知内容：F 日期 + "竞价确认 N 只" + 逐只（name/code/高开X%/低开/平开）+ §44 标签
- [ ] R5 final=0 或 quote 全缺→不发（guard，同 T-1 逻辑）

### B. 9:35 开盘表现通知（premarket_open_notify）
- [ ] R6 新 task type `premarket_open_notify`，cron `35 9 * * 0-4`（工作日 9:35）
- [ ] R7 读 F 日 final_candidates codes（同 R2）
- [ ] R8 `tencent_quote` 取实时价 + change_pct + limit_up_price；算封板状态（price>=limit_up_price）
- [ ] R9 通知内容：F 日期 + "开盘 5min N 只" + 逐只（name/现价/涨跌幅/封板/未封）+ §44 标签
- [ ] R10 final=0 或 quote 全缺→不发

### C. T+1 复盘通知（premarket_t1_review）
- [ ] R11 新 task type `premarket_t1_review`，cron `35 16 * * 0-4`（工作日 16:35，晚 first_board_t1_review 5min 避抢 DB）
- [ ] R12 读 F 日 final_candidates codes + t1_close（F 日收盘）；baostock kline 取 T 日（F 下一交易日）收盘算 T+1 收益
- [ ] R13 算 mean_return_pct / win_rate / n；§44 诚实口径：n<30 标"样本不足"、lift<2x 标"无 validated edge"、不宣称 alpha
- [ ] R14 通知内容：F 日期 + "T+1 复盘 N 只" + 均值收益/胜率 + 逐只（name/code/T+1收益）+ §44 标签
- [ ] R15 final=0 或 kline 缺→不发

### D. seed + 通知构建
- [ ] R16 `_ensure_seed_tasks` 加 3 个新 task seed（幂等）
- [ ] R17 新增 `_build_auction_notify_content` / `_build_open_notify_content` / `_build_t1_review_content` 通知内容函数（复用 `_build_premarket_notification_content` 风格）
- [ ] R18 3 个 executor 直接调 NotificationService.send()（同 T-1，不走 _send_notification）

### E. 测试
- [ ] R19 3 个新 executor 单测（final=0 不发 / 有数据发 + 内容断言 / NotificationService 不可用不崩）
- [ ] R20 通知内容函数单测（格式 + §44 标签 + 逐只行）
- [ ] R21 seed 迁移测试（新 task 幂等创建）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/scheduled_tasks.py` | 3 个新 executor（`_execute_premarket_auction_notify` / `_execute_premarket_open_notify` / `_execute_premarket_t1_review`）+ 3 个通知内容函数 + `_ensure_seed_tasks` 加 3 seed + `_executors` map 加 3 项 |
| `backend/tests/test_s093_notification.py`（或新建 test_s101_*.py） | 3 executor 单测 + 内容函数单测 + seed 测试 |
| `specs/S101-飞书多点通知/spec.md` | 本 spec |
| `specs/MILESTONES.md` | M7 加 S101 行 |

## 5. 设计方案

### 5.1 4 时点时间轴

```
T-1 17:15  candidate_funnel_precompute  → 前瞻选股结果（final_candidates + dual + top5）  [已实现+已修]
T   9:25   premarket_auction_notify      → 竞价确认（final_candidates 高开/低开/平开）     [S101 新增]
T   9:35   premarket_open_notify         → 开盘5min（final_candidates 现价/涨跌幅/封板）   [S101 新增]
T  16:35   premarket_t1_review           → T+1 复盘（final_candidates 收益/胜率/§44）      [S101 新增]
```

T = F 的下一交易日（forward）。final_candidates 是 F 日漏斗产出 = "选 T 的标的"。9:25/9:35 是 T 日盘中，读 F 日存的 final_candidates。T+1 复盘在 T 日 16:35 算 final_candidates 在 T 日的收益（F→T 持有1日）。

### 5.2 标的集合来源（不重跑漏斗）

9:25/9:35/T+1 都读 `load_funnel_result(F, 'all')` 的 final_candidates（17:15 已存）。F = 上一交易日（`last_trading_date_str`）。不重跑漏斗（成本低 + 数据一致）。无缓存→跳过不发（不臆造）。

### 5.3 通知内容格式（§44 诚实口径）

```
📊 9:25 竞价确认 2026-08-28（选 08-27 标的）

竞价确认 N 只:
  - 贵州茅台(600519) 高开 +1.2%
  - 平安银行(000001) 低开 -0.5%
  - 宁德时代(300750) 平开

参考值，非执行指令；§44 未验证，市场有风险
```

9:35 / T+1 同结构，换标题 + 逐只行内容。所有通知尾挂"参考值，非执行指令；§44 未验证，市场有风险"（raw-shadow 口径，不宣称 alpha）。

### 5.4 T+1 复盘 §44 口径

T+1 收益评价须守 §44（记忆 `section44-pre-conclusion-gate`）：
- n<30 → 标"样本不足，不下结论"
- 不报"胜率 X%"作结论（lift<2x=噪声），改报"均值收益 X%（n=N，§44 未 validated）"
- 不宣称 alpha / 不 pivot

### 5.5 关键设计决策

- **复用 funnel_cache 不重跑漏斗**：9:25/9:35/T+1 读缓存，成本低 + 标的集合一致。
- **复用 tencent_quote 不引新数据源**：实时价已有（WatchlistBoard 在用）。
- **T+1 新建不复用 first_board_t1_review**：后者评首板流快照候选（不同集合），混入 final_candidates 污染语义。新建 `premarket_t1_review` 评 final_candidates 独立闭环。
- **final=0 guard 统一**：4 点全加"无数据不发"（T-1 已修，3 个新点同逻辑）。
- **系统不下单**：通知只推状态，不触发交易（红线）。
- **cron 9:25/9:35 单次触发**：cron 跑一次读当下 quote 推送，不持续轮询（盘中实时监控是前端 WatchlistBoard 的事，通知只抓关键时点快照）。

## 6. 验收标准

- [x] A1 3 个新 task 在 DB seed（cron 9:25/9:35/16:35，enabled=True，幂等）
- [x] A2 9:25 executor：final=0 不发 / 有数据发 + 内容含 F日期+逐只高开低开+§44
- [x] A3 9:35 executor：final=0 不发 / 有数据发 + 内容含现价/涨跌幅/封板状态
- [x] A4 T+1 executor：final=0 不发 / 有数据发 + §44 口径（n<30 标样本不足，不宣称 alpha）
- [x] A5 NotificationService 不可用/send 抛异常 → 不崩（增强不阻断）
- [x] A6 离线全测绿（全量 2295 passed，1 pre-existing test_spec_consistency 硬编码 S066 非 S101；S101 零回归）

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机：通知是状态推送非买卖推荐，尾挂"参考值非执行指令；§44 未验证"（raw-shadow 口径）
- [x] 判断可复现：final_candidates 从 funnel_cache 读（17:15 已存的快照），tencent_quote 实时价，baostock kline T+1 收益——全可复算，不臆造
- [x] §44 不 auto-rank：通知推 final_candidates 全集（S098 已改 select 不 auto-rank），通知不排序不截断
- [x] 私有数据：funnel_cache 在 .vibe-research/（已隔离），不上传
- [x] em_get 防封：tencent_quote 非东财（不被限流），baostock 非东财，不涉 em_get

## 8. 测试计划

- `pytest tests/test_s093_notification.py tests/test_scheduled_tasks.py -v --no-cov`（通知 + seed）
- 新增 3 executor 单测（mock tencent_quote + funnel_cache + baostock）
- `pytest -m "not live" --deselect tests/test_newsradar_global_intel.py --deselect tests/test_s032_workflow_state.py --no-cov`（全量回归）

## 9. 风险与回滚

- **9:25/9:35 数据延迟**：tencent_quote 盘前/盘中可能延迟或部分 code 无 quote。处置：quote 缺失标"—"，全缺不发（guard）。
- **baostock T+1 kline 当日未更新**：T 日 16:35 baostock 可能还没更新当日 bar。处置：kline 缺标"kline 待更新"，不臆造收益。
- **cron 并发抢 DB**：9:25/9:35 各单次，不并发；T+1 16:35 晚 first_board_t1_review 5min，不抢。
- 回滚：`git revert` S101 commit（3 executor + 3 seed + 测试）。T-1 通知已修部分（第1步）独立 commit，不回滚。

## 10. 实现记录

### 10.1 第1步：T-1 通知结果不对修复（已实现 2026-08-27）

- cron 迁移：`candidate_funnel_precompute` DB 实际 `5 16`（16:05）→ `15 17`（17:15），等 gene_scores 写完 + 龙虎榜 16:30 后。`_ensure_seed_tasks` 加幂等迁移（startup 自动跑）。
- final=0 guard：`_execute_candidate_funnel_precompute` 加 `if final_cards:` guard，final=0 跳过通知 + WARNING 日志（避免推"0 只"误导）。
- 测试：`test_notification_skipped_when_final_candidates_empty` 新增。
- 验收：test_s093_notification 11 绿 + test_scheduled_tasks 8 绿 + test_task_executor 19 绿。

### 10.2 第2步：飞书多点通知（已实现 2026-08-27）

**3 新 executor**（`scheduled_tasks.py`）：
- `_execute_premarket_auction_notify`（cron `25 9 * * 0-4`，9:25 竞价确认）：读 F 日 funnel_cache final_candidates → tencent_quote 取竞价 open/last_close → 算 gap_pct（高开/低开/平开）→ 推飞书。
- `_execute_premarket_open_notify`（cron `35 9 * * 0-4`，9:35 开盘表现）：取实时 price/change_pct/limit_up_price → 算封板状态 → 推飞书。
- `_execute_premarket_t1_review`（cron `35 16 * * 0-4`，T+1 复盘）：baostock_kline_cache 取 F 日 close + T 日 close → close2close 收益 → 均值/红盘/逐只 + §44 口径（n<30 标样本不足，不宣称 alpha）。

**辅助函数**：
- `_load_final_cards(F)`：读 funnel_cache final_candidates（model_dump 列表），无缓存返空。
- `_fetch_quotes(codes)`：批量 tencent_quote，失败返空。
- `_send_notify(content)`：NotificationService.send 封装，不可用/失败返 False 不崩。
- `_compute_t1_returns(cards, F, T)`：baostock kline close2close 收益。
- `_build_auction_notify_content` / `_build_open_notify_content` / `_build_t1_review_content`：3 个时点通知内容，尾挂 `_S101_DISCLAIMER`（"参考值，非执行指令；§44 未验证，市场有风险"）。

**seed**：`_ensure_seed_tasks` 加 3 个新 task（幂等）。

**验收**：
- 3 executor 单测（final=0 跳过 / 有数据发 + 内容断言 / NS 不可用不崩）+ 内容构建函数单测 + seed 幂等测试 = `test_s101_notification.py` 13 测全绿。
- 全量 2295 passed + 1 pre-existing（test_spec_consistency 硬编码 S066 已归档，非 S101）+ 1 skipped + 39 deselected。S101 零回归破坏。
- 实跑验证：用 F=2026-08-21 历史缓存跑 3 executor，通知内容正常产出（9:25 竞价高开低开 / 9:35 封板状态 / T+1 逐只收益均值红盘 §44 口径）。
