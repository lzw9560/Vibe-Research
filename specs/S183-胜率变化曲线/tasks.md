# S183 tasks（按 spec v2 grill 修订）

- [x] T1 R2 改 `engine/trade_journal.py:_wilson_ci:389` n=0 返 (0,1) + 注释改 + test_trade_journal 加 n=0 边界测试
- [x] T2 R5 `DORMANT_ARMS` 移 trend + `ARM_VERDICT["trend"]="exploratory"`（S181 一致）+ 测试
- [x] T3 R1 `engine/trade_journal.py` 加 `query_winrate_trends()` 方法（实时聚合按周分桶，is_realized=1 AND is_dead_arm=0 AND net_pnl IS NOT NULL，exit_date cutoff，双轴标签）+ test_s183_winrate_trends 单测
- [x] T4 R1 `routers/journal.py` 加 `GET /api/journal/winrate-trends` 端点 + API 单测（TestClient 空表返 []）
- [x] T5 R3 前端 `lib/journal-contract.ts` type + `lib/api.ts` method + `lib/query/journal.ts` hook
- [x] T6 R3 `components/journal/JournalWinRateCurve.tsx`（echarts stack CI band + 50% markLine + 方向色 + 空态 + Disclaimer compact）+ 组件测试
- [x] T7 R3 `pages/Journal.tsx` 挂载（closedloop tab，JournalLedger 上方）
- [x] T8 A5-A8 跑 test_trade_journal + test_s183 + test_s173/s175/s181 无回归 + tsc0（后端 7+23 passed + 前端 4 passed + tsc exit 0）
