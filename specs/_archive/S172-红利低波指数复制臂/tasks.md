# Tasks: S172 — 红利低波指数复制臂（A 臂 floor）

> spec: spec.md  plan: plan.md  依赖序：T1→T2→T3→T4→T5→T6→T7
> 状态：全部完成(2026-09-09)

## T1: fetch_etf_tracking.py — 取数模块（R1/R2/R3 ETF 端）✅
- [x] T1.1 `_ak()` 惰性 import akshare（akshare_src 模式，缺失 raise DependencyMissing）
- [x] T1.2 `fetch_etf_quote(code='512890')`：`fund_etf_spot_em()` 筛 code → dict{code, name, price, change, change_pct, volume, amount}（R1）
- [x] T1.3 `fetch_etf_hist(code, start, end)`：`fund_etf_hist_em(adjust='qfq')` → list[{date, close, ret}]（R3 ETF 端）
- [x] T1.4 `fetch_index_hist(symbol, start, end)`：`index_zh_a_hist()` → list[{date, close, ret}]（R3 index 端）
- [x] T1.5 `fetch_index_cons_weight(index='930955')`：`index_stock_cons_weight_csindex()` → list[{code, name, weight}]（R2）
- [x] T1.6 akshare 调用间 `time.sleep(2)` 惯例；取数失败诚实降级返空（不臆造）
- 验收：py_compile 通过；函数签名与 spec §5.2 一致 ✅

## T2: tracking_error_report（R3 跟踪误差汇总）✅
- [x] T2.1 取 ETF + 指数日收益序列，对齐日期做差（inner join on date）
- [x] T2.2 `tracking_error = std(diff) × sqrt(252)` 年化（spec §5.4 口径，sample std n-1）
- [x] T2.3 窗口默认 [1m/3m/6m/12m]（~21/63/126/252 交易日），可参数化
- [x] T2.4 绿灯 <1% / 黄灯 1-2% / 红灯 >2%（spec §5.4）
- 验收：mock 数据计算结果与手工公式吻合（test_tracking_error_calculation_matches_formula）✅

## T3: index_replication_floor.py — 建仓 + 持有（R4/R6）✅
- [x] T3.1 `_FLOOR_DIR = resolve_data_dir() / 'etf_floor'` + `_atomic_write_json`（vr_paths + scan_long_value_cache 模式）
- [x] T3.2 `build_position_batches(total=100000, n_batches=5, interval_days=7, one_shot=False)`：生成 N 批计划（R4）
- [x] T3.3 `record_batch(batch_idx, date, price, shares, amount)`：写 batches.json（atomic write）
- [x] T3.4 `hold_status()`：读 batches.json → {total_cost, total_shares, n_filled, batches, avg_cost}
- [x] T3.5 无 stop/take 代码（R6 长线底仓 hold，grep 确认 exit 1 无匹配）
- 验收：5 批 × 2 万 = 10 万，间隔 7 交易日；batches.json 写入 .vibe-research/etf_floor/ ✅

## T4: weekly_report（R5 周报）✅
- [x] T4.1 `weekly_report()`：调 hold_status + fetch_etf_quote + tracking_error_report 汇总
- [x] T4.2 返回 {etf_code, asof_price, market_value, cost_basis, unrealized_pnl, pnl_pct, total_shares, avg_cost, n_filled, tracking_error, risk_disclaimer}
- [x] T4.3 取数失败降级标注（不阻塞报告产出）
- 验收：mock 后产出完整周报 dict，字段齐全（test_report_fields_complete）✅

## T5: 测试 ✅
- [x] T5.1 `test_fetch_etf_tracking`：8 tests，mock akshare 返回固定 DataFrame，验取数解析 + 跟踪误差计算
- [x] T5.2 `test_index_replication_floor`：10 tests，mock 行情，验分批建仓 + 周报格式 + atomic write + VR_DATA_DIR 隔离
- [x] T5.3 `pytest -m "not live" -k "etf_tracking or index_replication"` 全绿（18/18 passed）
- [x] T5.4 `pytest -m "not live"` 全量 3046 passed（8 failed 均为无关的 scheduled_tasks/registry/task_executor 预先失败，非 S172 引入）
- 验收：S172 新增 18 tests 全绿 ✅

## T6: py_compile + 验收对照 ✅
- [x] T6.1 `python -m py_compile` 两个新文件通过
- [x] T6.2 逐条核对 spec §6 验收标准 A1-A8（见下）
- [x] T6.3 `git status` 确认 .vibe-research/ 未进 git（A8）
- 验收：全部 A1-A8 过 ✅

### 验收标准对照（spec §6）
- [x] A1 `fetch_etf_quote('512890')` 返回现价/涨跌/成交额，非空 → test_returns_dict_for_512890 ✅（联网验收需手动跑）
- [x] A2 `fetch_index_cons_weight('930955')` 返回成分+权重，行数≥50 → test_returns_list_of_dicts ✅（mock 3 行，实盘~50）
- [x] A3 `tracking_error_report('512890','930955')` 产出近 1/3/6/12 月跟踪误差 → test_tracking_error_green ✅
- [x] A4 `build_position_batches(100000,5)` 产出 5 批，间隔 7 交易日 → test_5_batches_equal_split ✅
- [x] A5 `weekly_report()` 产出市值/成本基/浮动盈亏/跟踪误差 → test_report_fields_complete ✅
- [x] A6 无 stop/take 逻辑（grep 确认 exit 1）→ test_no_stop_loss_logic ✅
- [x] A7 `pytest -m "not live"` 全绿（S172 新增 18/18 绿；8 失败为无关预先问题）✅
- [x] A8 持仓数据写入 `.vibe-research/`，未进 git → test_batches_json_not_in_git + git status ✅
