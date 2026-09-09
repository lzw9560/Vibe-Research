# Plan v2: S175 — 模拟盘自洽闭环（spec grill 后技术方案）

> spec v2（2 CRITICAL+7 HIGH 全修）后的技术方案。v1 的 R6"+3行"/R3 无截断/R4 无 _latest_close/R9 无 equity sizing/R11 未 deferred/R14 real_cost_pct 全纠正。

## 1. 模块拆分

### P0 — 最小可跑闭环（~200-210 行）

| 模块 | 行数估 | 职责 | 依赖 |
|---|---|---|---|
| `engine/bars_provider.py`（**已 v2 GREEN**） | ~60 | composite KlineCacheBarsProvider：A股→resolve_data_dir cache；ETF→fetch_etf_hist **+ 规范化 {date,close,ret}→{date,open:close,high:close,low:close,close}**（SH6，Executor T1OpenFill 需 open）；reload() | 无 |
| `engine/accounting.py`（改） | +6-9 | PathReturn dataclass 加 `exit_price: float`，**三分支均设**：stop=entry*(1+stop/100)，take=entry*(1+take/100)，max_hold=bars[exit_idx].close（:165 已算）。覆写 S173 :24 只读约束（SH7） | 无 |
| `scheduler/executors/journal.py`（新建） | ~40 | trade_journal_daily(payload)：构造 JournalRecorder(bars_provider=KlineCacheBarsProvider()) → settle_pending_breakout() → run_daily(target_date=prev_trading_date_str(), arms=['floor','breakout']) → update_floor_mtm(target_date=prev) | bars_provider + journal_recorder |
| `scheduler/executors/__init__.py`（改） | +2 | _executors dispatch 加 trade_journal_daily + thin wrapper | journal.py |
| `scheduler/seed.py`（改） | +8 | 加 cron `45 16 * * 0-4` trade_journal_daily（create_task 幂等） | executors |
| `strategies/journal_recorder.py`（改） | ~60 | settle_pending_breakout() 新方法（**截断 max_hold 留 hold SH5 + signal_id 绕过 .create() SH**）+ _latest_close target_date 参数（SH2）+ run_daily default target_date=prev（R4）+ import ETF_CODE（R5）+ exit_price=pr.exit_price（R6） | accounting PathReturn exit_price |
| `frontend` Recommendation.tsx/Disclaimer.tsx/Layout.tsx（改，**SC2 修路径**） | ~30 | §44-falsified 横幅 + 降 LEVEL_META + per-item 标（SH4）+ footer/Disclaimer/subtitle 三处 posture 一致=谋士 | 无 |
| `tests/test_s175_e2e.py`（新建） | ~80 | mock bars_provider（A股+ETF 含 open 延伸 T+2+max_hold）跑 3 次 run_daily + settle_pending，断言 A1（SH3 可复现验收） | T1-T5 |

### P1 — 多臂推荐 + PaperPortfolio（R9↔R10 接线）+ 诚实 UI

| 模块 | 行数估 | 职责 | 依赖 |
|---|---|---|---|
| `recommendation_engine.py`（rework，**root 非 strategies/ SC2**） | ~130 | gene-only→多臂 + **读 PaperPortfolio.equity() 作 floor sizing（R9↔R10 接线 SH1）**；诚实承认 3/4 槽位静态标签 | P0 trade_journal + PaperPortfolio |
| `routers/recommendation.py`（改） | +15 | GET /api/recommendation/multi-arm | recommendation_engine |
| `engine/paper_portfolio.py`（新建） | ~80 | thin read-only wrapper（委托 trade_journal.equity_curve + drawdown_breaker.full_status + final_size），**R9 消费 equity 非 SH1 空转** | P0 trade_journal+drawdown_breaker |
| `scheduler/executors/journal.py`（扩） | +5 | executor 末尾调 PaperPortfolio.equity() 落盘 + drawdown_breaker.compute_drawdown()（**R11 overlay deferred，只留 1 行 drawdown 接线**） | paper_portfolio |
| `frontend` JournalLedger.tsx/journal-contract.ts/api.ts/Recommendation.tsx（改，**SC2 路径**） | ~120 | verdict badge + dsr_method 标 + mock 标识 + PaperNotRealBanner + underpowered 顶置 + Sharpe 未年化 + cap 标签 + dormant 臂 stub 卡 + **保留 coverage/CI/unbuyable** + **删旧 gene 卡替换多臂面板** + 新建 ArmAggregate 类型（含 s44_verdict）+ StockRecommendation type 更新 | T7 数据 + T8 equity |

### P2 — 跟单 flow（per-fill fees）+ 4 源 gap（永久 dormant）

| 模块 | 行数估 | 职责 | 依赖 |
|---|---|---|---|
| `routers/journal.py`（改） | +35 | POST /api/journal/follow-order（**per-fill fees 非 real_cost_pct，匹配 S166 Fill.fee**）+ GET /api/journal/gap（不改 18 现有端点）；4 源 gap 结构建好诚实标激活条件不可达 | journal.py add 入口 |
| `journal.py`（改） | +10 | add 入口（routers/journal.py:104 journal_add + _save/_load_raw）加 signal_id 关联 | 无 |
| `frontend` FollowDecisionModal + FollowOrderGap（新建） | ~110 | 跟单按钮 + 成本计算器引导（输入佣金率/免五/印花→cost_pct）+ 4 源 gap 渲染 + dormant 标"激活条件不可达" | journal-contract FollowDecision 类型 |

## 2. 依赖序（构建顺序）

```
P0（无外部依赖，解锁全闭环）:
  T1 bars_provider 双源+ETF 规范化 ✅ GREEN
  T2 accounting PathReturn exit_price 三分支（无依赖）
  T3 journal_recorder settle_pending（截断 max_hold + signal_id bypass）+ _latest_close target_date + 3 fix（依赖 T1+T2）
  T4 scheduler/executors/journal.py + dispatch + seed cron（依赖 T3）
  T5 frontend §44-falsified 横幅 + 降 LEVEL_META + Disclaimer/footer/subtitle 三处（SC2 路径，无后端依赖，并行）
  T6 test_s175_e2e e2e 集成验收（依赖 T1-T5，SH3 可复现）
  → 验收 A1+A2：mock 3 天 trade_journal 有 floor 512890 + breakout is_realized=1（截断留 hold 验证）

P1（依赖 P0 数据积累）:
  T7 recommendation_engine 多臂 + 读 equity sizing（R9↔R10 接线，SH1）+ routers/recommendation
  T8 PaperPortfolio（R9 消费）+ executor 末尾调 equity+drawdown（R11 overlay deferred）
  T9 JournalLedger honest 标签 + dormant stub + 删旧 gene 卡换多臂面板（依赖 T7+T8）
  → 验收 A3+A4+A5

P2（依赖 P1 推荐卡 signal_id）:
  T10 follow-order API（per-fill fees）+ 4 源 gap 结构（永久 dormant 标激活条件不可达）
  T11 FollowDecisionModal + FollowOrderGap 组件
  → 验收 A6
```

## 3. 数据流（spec grill 后补 ETF 规范化 + 截断 + _latest_close + R9↔R10）

```
baostock_kline_cache.json（kline_refresh 16:30，5226 股 stock-only，OHLC）
  + fetch_etf_hist（akshare push2delay，[{date,close,ret}]）→ 规范化补 open/high/low=close（SH6）
  ↓
KlineCacheBarsProvider（双源 dispatch + ETF 规范化）
  ↓
JournalRecorder.run_daily(target_date=prev_trading_date_str())
  ├ settle_pending_breakout() ← 查 is_realized=0 'hold' → path_return 重算 → 截断 max_hold 留 hold → INSERT OR REPLACE 同 signal_id（绕过 .create()）
  ├ floor: build_position_batches → bars_provider(512890)→fetch_etf_hist→规范化 → MTM(unrealized_pnl, _latest_close target_date 过滤防前视 SH2)
  └ breakout: select_premarket_candidates(T-1) → T1OpenFill(T) → path_return(apply_cost=True, exit_price=pr.exit_price 三分支)
  ↓
accounting.path_return/gap_net_return（真成本）
  ↓
TradeJournal.insert → trade_journal.db（.vibe-research/，C7 隔离 winrate.db）
  ↓
aggregate_by_arm（复用 s44_verifier；floor aggregate 恒 empty by design）
  ↓
PaperPortfolio.equity()（scheduler 路径）→ R9 recommendation_engine 读作 floor sizing（R9↔R10 接线，非空转 SH1）
  + drawdown_breaker.compute_drawdown()（从 API 层移 executor 生产，1 行；overlay deferred）
  ↓
多臂 RecommendationEngine（删旧 gene 卡）→ 推荐 UI
  ↓
跟单 flow（per-fill fees）→ 4 源 gap（永久 dormant 除非 validated 盘中臂）→ 诚实呈现
```

## 4. 备选方案为何不选（spec grill 后补）

- **不建 §44 R3 enforce 自动复验**：DIMENSION_LIFT_REGISTRY 静态 frozen dict，Recorder.save 不回写；0 可毕业臂。S175 仅读 days_robust 作诚实标签"lift cap 未接 trade_journal sizing 路径"。
- **PaperPortfolio 建 thin wrapper + R9 接线消费**（用户拉回 + spec grill SH1 fix）：承认 DRY（trade_journal.equity_curve 已聚合），价值在 R9 读 equity sizing（非空转）。spec v1 的"供推荐 sizing"声称没在 R9 接线 = 空转，v2 修：R9 加读 equity() + §4 接线点。
- **R11 portfolio overlay stub 移 deferred**（spec grill）：stub 无 consumer（R9 只读 PaperPortfolio.equity 非 overlay）无 impl（EWMA/MAB defer）= 纯 YAGNI。drawdown_breaker 接 executor 1 行单独留 P1（不依赖 overlay stub）。EWMA/MAB/SRTS + overlay 骨架全 deferred 待 ≥2 validated 臂 + 60d vol input。
- **4 源 gap 建结构 + 诚实标激活条件不可达**（用户拉回 + spec grill SH fix）：breakout paper-only 无真盘记录可 diff，floor ETF 无 unbuyable/T+1 问题；**永久 dormant 除非未来 validated 盘中臂出现**（非"暂时等插槽"，v1 自欺包装纠正）。价值在 R14 follow-order flow 本身。
- **不建 /trade-desk cockpit**：属 page-architecture-redesign 独立 spec（router.tsx 仍 55 path 未落）。S175 UI 扩展现有 Journal/Recommendation 页。
- **不建 conditioning harness 作信号生成器**：§44 falsified selection（S168），应作数据收集器（写盘中 OFI 到独立 intraday store）非喂 trade_journal ledger。
- **ETF 走 push2delay 非 em_get 全防护**（spec grill SC1 如实）：fund_etf_hist_em IS 东财（akshare push2delay+sleep），无 circuit_breaker/代理降级，§7 如实标"弱保护非 em_get 全防护"，不虚假声称"非东财"。单 ETF 日调封禁风险低可接受。

## 5. 关键设计决策（spec grill 后补）

- **bars_provider 双源 + ETF 规范化**（C1+SH6）：A股 cache（OHLC），ETF fetch_etf_hist（{date,close,ret}）→ 规范化补 open/high/low=close（Executor T1OpenFill 需 open，否则 entry_f=0 全 unbuyable）。
- **settle_pending 重算 + 截断 max_hold 留 hold + signal_id bypass .create()**（C2+SH5+SH）：不缓存 'hold' 状态，每日重算 → path_return → **截断 max_hold exit（exit_idx==len-1）留 hold 非过早 realized**；**直接构造 JournalRecord(signal_id=pos.signal_id) 绕过 .create()**（生新 UUID 无法 INSERT OR REPLACE 同 id）。
- **_latest_close target_date 过滤**（SH2）：返 date<=target_date 的最后 close 非 reversed 最后，防历史重跑用未来 close 前视偏差。
- **target_date=prev_trading_date_str**（C5）：run_daily default 改 prev（不只 executor 传参），防其他调用方复发 no_t1_bar 误标 unbuyable。
- **PaperPortfolio thin wrapper + R9 接线**（用户拉回 + SH1）：委托 trade_journal.equity_curve+drawdown_breaker（DRY-acknowledged），R9 读 equity sizing（非空转）。
- **诚实标签多档 + cap 精确措辞**（C7+C6+SH4）：falsified/validated/externally_validated/exploratory/underpowered/mock_not_ready/dead_arm；breakout=§44_falsified 非 weak；floor=externally_validated。cap 标"lift cap 未接 trade_journal sizing 路径（drawdown cap 已接但 underpowered=1.0 no-op）"非笼统"未接生产"。
