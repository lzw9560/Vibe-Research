# S249 · trade_journal_daily timeout 根因修复

**状态**：已实现（2026-11-13）
**分级**：medium（perf 修复，3 文件，230 测试绿）

## 问题
trade_journal_daily 11-12 19:00 fire → timeout 1200s failed（11-10 success 110s）。daily_full_pull depends_on trade_journal_daily → 链断 skip。

## 根因（5-agent workflow 诊断 + 4 reader 独立收敛 + 逐行核验）
`update_floor_mtm()`（journal_recorder.py:1086）循环内 163 条 floor 未平持仓（DB 实测全 512890，distinct=1，自 2026-01-05 每日累积 1 条）每条调 `bars_provider('512890')` → `fetch_etf_hist`（akshare fund_etf_hist_em，retries=3 但**无 socket timeout 无 cache 无 dedup**，失败走 baostock fallback）。
- 正常日 163×0.5s≈81s + combo record 30s + 杂项 = 110s success
- 退化日（11-12 akshare/baostock 退化）163×(30-90s) 远超 1200s timeout
- 经典 N+1 + 三重缺陷（无 cache/无 dedup/无 timeout）

次要：record_combo_5d（combo 11-08 FALSIFIED）load_combo_5d_today 全表 1.28GB load+parse ~30s 压低 timeout 余量。

## 修复（3 Edit）
1. **journal_recorder.py update_floor_mtm N+1 去重**：循环外按 unique stock_code 预取 bars 到 cache，循环内复用（N+1→unique_count，512890 case 163→1）
2. **fetch_etf_tracking.py fetch_etf_hist socket timeout**：`socket.setdefaulttimeout(10)` + try/finally 恢复，防 akshare hang 单调用无限阻塞
3. **journal.py 砍 record_combo_5d**：combo FALSIFIED weight=0.0，给死策略攒 paper picks 零价值 + 1.28GB 30s 压低 timeout。保留 settle_combo_5d 收尾 61 pending ~12-19

## 验收
- [x] 230 测试绿（journal/etf/scheduler/cron）
- [ ] 11-13 19:00 trade_journal_daily fire 验（应在 timeout 内 success + daily_full_pull 链恢复）
- [x] grep 确认 163 floor distinct=1 + update_floor_mtm N+1 + fetch_etf_hist 无 timeout（改前）

## caveat
11-12 timeout 无步骤级计时（result={} 空，timeout 杀进程前未记），"哪步吃满 1200s"是推断非直接 profiling。但强旁证链：4 reader 独立收敛 + DB distinct=1 + 代码 N+1 核验 + 11-10 success 110s floor_mtm=162 占大头。调大 timeout（1200→1800）不是修复——163×无 timeout 击穿任何合理 timeout。
