# Spec: S175 — 模拟盘自洽闭环（Paper Trading Unified Loop）

> 状态：已实现（2026-09-09，P0+P1+P2 done 128 tests+tsc0；spec grill 2 CRITICAL+7 HIGH 全落代码；2026-09-11 trend 进 cron paper_track commit 98555b6）
> 作者：lzw9560  日期：2026-09-09
> 关联：S173-TradeJournal闭环（journal_recorder 已建，本 spec 接线生产）/ S172-红利低波指数复制臂（floor 臂 ETF 512890）/ S161-§44v2验证框架（verifier 复用）/ S166-TradeJournal+RiskLedger（journal.py 手动账本，跟单走它）/ S174-godmodule拆分（scheduler 包 P6 拆完）
> 分级：large —— 整体自洽系统接线 + 多臂推荐 + 虚拟账户 + 跟单；P0 core ~200-210 行（grill C8+spec grill 核证据后如实估，非"30 行"非"150 行"）

## 1. 问题 / 目标

north-star 三问（买什么/何时买/何时卖）+ 胜率闭环 + 谋士 posture（献计不替决）的**统一框架**：系统=模拟盘+推荐+模拟闭环+模拟交易日志(S173)+诚实跟踪；用户=看推荐+跟踪→选择跟单（真盘用户定）。

**核心痛点**：S173 造好了引擎（journal_recorder.run_daily 顺序管线 + trade_journal SQLite ledger + drawdown_breaker + accounting），但**引擎没接电瓶线**——journal_recorder.run_daily 未注册为 scheduler executor（实测 scheduler/executors/__init__.py 31 条 dispatch 0 journal 条目，seed.py 24 task_type 0 journal），生产 cron 不跑 → trade_journal.db 空 → 所有下游验证/推荐/跟单 vacuous。整个自洽系统是「引擎造好没点火」。

一句话：S175 = 接 call-point wiring（~200 行非 30）+ 修 4 处断裂 + 诚实呈现 + 多臂推荐 + 虚拟账户 + 极简跟单，把九层串成一个自洽回路。0 validated edge → 模拟盘诚实模式（纸面积累不碰用户真钱，等 60 天 live 复验）。

> **grill 核证据后 scope 如实重估**（设计 grill 8 CRITICAL + spec grill 2 CRITICAL/7 HIGH，主 agent fresh 核证据）：P0 真实 ~200-210 行 = 双源 bars_provider（A股 cache + ETF fetch_etf_hist + **ETF bar 规范化 open/high/low**）+ settle_pending_breakout 新方法（+ **截断 max_hold 留 hold 防过早 realized** + **signal_id 绕过 .create()**）+ ETF code/exit_price 2 fix（**三分支 exit_price 均设**）+ _latest_close target_date 过滤 + scheduler 接线 + 诚实标签。详见 §5。

## 2. 背景

### 2.1 现状（fresh grep + Read + python 实测，2026-09-09，主 agent 核证据非凭记忆）

九层已大半建成，但主轴断裂。

**已建可直接接**（fresh 确认）：
- `journal_recorder.run_daily(arms)` (strategies/journal_recorder.py:80) — orchestrator 主入口，DI 注入 journal/executor/bars_provider，顺序调 _process_floor/_process_breakout/_process_gap/_process_mock_arm。**但 `DEFAULT_ARMS=['floor','breakout']`（:44）只有 2 臂**，gap/limitup/trend 生产不跑（"4 臂 orchestrator"是假，spec 如实标 2 臂，gap 审计走 tools/s44_gap_run_60d.py 独立脚本）。
- `index_replication_floor.build_position_batches(one_shot, start_date)` (strategies/index_replication_floor.py) — floor 臂 signal，`ETF_CODE="512890"`（:34，红利低波）。
- `accounting.path_return(apply_cost=True)` (engine/accounting.py:91) + `gap_net_return` (:184，无 apply_cost 开关 always 经 _cost_pct) + `_cost_pct` (:67, 5 元最低+印花+滑点)。**PathReturn dataclass（:40-54）无 exit_price 字段**，path_return 三分支中仅 max_hold（:165）算 exit_price 局部变量未暴露，stop（:148）/take（:156）分支根本没算。
- `TradeJournal.insert/aggregate_by_arm/query_records` (engine/trade_journal.py) — SQLite ledger，复用 s44_verifier stats。**`JournalRecord.create()`（:94）每次生新 UUID signal_id**，`cls(signal_id=str(uuid.uuid4()), ..., **kwargs)` 若 kwargs 含 signal_id → TypeError。aggregate_by_arm 查 `is_realized=1 is_dead_arm=0`（:300）。
- `DrawdownBreaker.compute_drawdown/full_status/final_size` (engine/drawdown_breaker.py) — C4 绝对回撤，H5 三层乘积。**underpowered multiplier=1.0（:114-116）非 ×0.5**；`lift_to_multiplier` 在 scoring.py:66（gene 臂）+ routers/verifier.py:112（API R8 wiring）两处，**但均不在 trade_journal→drawdown_breaker→per-arm sizing 路径**（主 agent grep 核实）。
- `s44_verifier` (stats.py + wiring.py compute_dsr/haircut) — S161 done。
- `JournalLedger.tsx` (frontend) — ArmStatCard 已显 winrate/Wilson CI（:45-48）/coverage_rate（:49-54）/unbuyable（:91），但缺 verdict badge + dsr_method 标 + mock 标识 + 纸面≠真盘横幅 + cap 标签 + Sharpe n<60 未年化标。
- `fetch_etf_hist` (tools/fetch_etf_tracking.py:150) 返 `[{date, close, ret}]`——**无 'open' 键**（_parse_daily_returns :125-147 只取 date/close/ret）。Executor T1OpenFill 读 `bars[idx+1]['open']`（fill_policies.py:78，_bar_get 黔返 0.0）→ ETF entry_f=0.0 → 全 unbuyable。**bars_provider ETF 分支须规范化 {date,close}→{date,open:close,high:close,low:close,close}**（ETF 净值口径四价相等）。
- 前端：`Recommendation.tsx` LEVEL_META "高质量关注"=emerald green（:11）+ gene_score display（:92）+ subtitle "基于基因得分的教育研究式关注清单"（:52）。`Disclaimer.tsx` 在 `components/ui/Disclaimer.tsx`（:8 compact "不推荐个股..."，:16 full "不给买卖时机..."）。`Layout.tsx` 在 `components/layout/Layout.tsx`（:161 footer "不荐股·不预测·无倾向"）。

**4 处断裂（THE connective tissue gaps）**：
- **BREAK-0（最关键）**: scheduler→journal_recorder 未接 — 31 dispatch 0 journal 条目，seed.py 0 journal cron。THE orchestrator 主线断裂。
- **BREAK-1**: ETF code 不一致 — `journal_recorder.py:240` 硬编 `etf_code="510300"`（CSI300）但 `index_replication_floor.py:34 ETF_CODE="512890"`（红利低波）。且 kline cache 是 stock-only（python 实测 5226 个 key 全 000xxx 股票，512890/510300/510050/510310 全 False）→ 即使修 code，bars_provider('512890') 须走 fetch_etf_hist（ETF bar 规范化补 open/high/low）非 cache。
- **BREAK-2**: `settle_pending_breakout` 不存在（grep 0 命中）— breakout path_return 的 T+1 guard（accounting.py:120 idx+2>=len→None）需 T+2+ 天 bar，盘后 T 跑 bars 只到 T → 全记 is_realized=0 'hold' 永不更新 → aggregate_by_arm 查 is_realized=1 得空集 → breakout 永远 empty。**且 path_return max_hold exit（:164 exit_idx=min(idx+1+max_hold_days,len(bars)-1)）在 bars 不足完整持仓期时截断返 exit_reason='max_hold' PathReturn（非 None）→ settle_pending 须区分"完整 max_hold exit"（可标 realized）vs"截断 max_hold exit"（留 hold 等更多 bars），否则过早标 realized 后续 stop/take 永不检查**。
- **BREAK-3**: R3 enforce 仅 reminder — seed.py "到点只提醒不自动验证"；且 DIMENSION_LIFT_REGISTRY 是静态 frozen dict（evaluation.py），Recorder.save() 不回写 → "60d 自动复验→days_robust 升→cap 自动放"是假的。S175 不建 R3 自动复验（deferred），仅读 days_robust 作诚实标签。

**其他 latent**：portfolio overlay 无模块（grep PortfolioOverlay/EWMA/MAB/SRTS 全空）/ ash-mcp B 臂未 clone / 跟单 flow 零实现 / 推荐 engine gene-only（§44 falsified）/ PaperPortfolio 无独立类 / `_latest_close`（journal_recorder.py:401-414）无 target_date 过滤 → 历史重跑用未来 close 前视偏差（spec grill 新抓，设计 grill C1-C8 未覆盖）。

### 2.2 为什么现在做

- gap falsified → 0 validated edge → 系统不能假装给真盘信号 → **模拟盘是诚实的模式**（跟踪模拟表现不碰用户真钱，等 60 天 live 复验）。
- S173 引擎造好没点火 — 1 个 executor + 1 条 seed cron + settle_pending + 2 fix + 双源 provider + _latest_close 过滤 就让全系统跑起来。
- north-star 三问+胜率闭环需要 signal→PnL 全链路跑起来才有诚实数据。
- 用户「全局考虑」+「模拟盘+推荐+跟踪+跟单」自洽框架 — **整框建好**，每件显式标当前状态（floor=外部验证 actionable / breakout=§44_falsified paper-only / limitup-trend=mock / gap=dead / overlay=deferred 待 ≥2 臂 / 4 源 gap=dormant 激活条件当前不可达除非未来 validated 盘中臂），空跑件不假装有数据，结构在等插槽。

### 2.3 grill verdict（设计 grill 8 CRITICAL + spec grill 2 CRITICAL/7 HIGH，主 agent 核证据全真）

设计 grill 8 CRITICAL（C1-C8，见 v1 §2.3）+ spec grill 新抓：

| # | 严重 | 问题（fresh 核实） |
|---|------|------|
| SC1 | CRITICAL | §7 em_get 虚假声称——fund_etf_hist_em IS 东财（akshare.fund_etf_em）走 push2delay 非 em_get 全防护，spec 写"非东财"绕过 §1.2 工程底线自查 |
| SC2 | CRITICAL | §4 三路径错（spec-scope-mis-trace 重犯）：recommendation_engine.py 在 root 非 strategies/；Disclaimer 在 ui/；Layout 在 layout/ |
| SH1 | HIGH | R9↔R10 断线——R10 equity() "供推荐 sizing"但 R9 recommendation_engine 零引用 equity → 空转非价值 |
| SH2 | HIGH | _latest_close 无 target_date 过滤 → 历史重跑前视偏差（设计 grill C1-C8 未覆盖） |
| SH3 | HIGH | A1/A2 不可验——A1"跑3天模拟"无命令/mock；A2"aggregate 非 empty"对 floor 结构性不可能（floor 永远 is_realized=0，aggregate 查 is_realized=1 恒空） |
| SH4 | HIGH | R7 矛盾 UI——加 §44-falsified 横幅但留 LEVEL_META"高质量关注"绿色徽章+gene_score → 不是真止血 |
| SH5 | HIGH | R3 过早 realized——path_return max_hold 截断返非 None → "pr is not None → is_realized=1"过早标 realized，后续 stop/take 永不检查 |
| SH6 | HIGH | ETF bar 缺 open——fetch_etf_hist 返 {date,close,ret} 无 open → Executor entry_f=0 → 全 unbuyable → A1 必败 |
| SH7 | HIGH | R6 stop/take exit_price=0——":165 已算"只 max_hold，stop/take 分支没设 → 加默认 0.0 后新 bug |

**spec 前必修**：SC1-SC2 + SH1-SH7 全部在 P0/P1 落地。

## 3. 需求清单

### P0 — 最小可跑闭环（~200-210 行，grill+spec grill 核证据后如实估）

- [ ] R1 **双源 bars_provider + ETF bar 规范化**：建 `engine/bars_provider.py`（**已实现 v1，须补 ETF bar 规范化**），composite provider——A股 code→读 `vr_paths.resolve_data_dir()/"baostock_kline_cache.json"`（用 resolve_data_dir 不硬编）；ETF code→调 `fetch_etf_hist`（akshare fund_etf_hist_em qfq）**+ 规范化 {date,close,ret}→{date,open:close,high:close,low:close,close}**（ETF 净值口径四价相等，Executor T1OpenFill 需 open）。cache 是 stock-only（C1/SH6）。
- [ ] R2 **scheduler 接线**：建 `scheduler/executors/journal.py`（P6 域文件范式）+ `TaskExecutor._executors` 加 `trade_journal_daily` dispatch + `seed.py` 加 cron `45 16 * * 0-4`（16:45 盘后，晚 kline_refresh 16:30）。executor 调 `JournalRecorder(bars_provider=KlineCacheBarsProvider()).run_daily(target_date=prev_trading_date_str(), arms=['floor','breakout'])` + `settle_pending_breakout()` + `update_floor_mtm(target_date=prev_trading_date_str())`。
- [ ] R3 **settle_pending_breakout 新方法**（+ 截断 max_hold 留 hold + signal_id bypass .create()）：`JournalRecorder.settle_pending_breakout()` — run_daily 开头 query `is_realized=0, is_dead_arm=0, arm='breakout'` 的 'hold' 记录（query_records 无 exit_reason 过滤，Python 层 filter `[r for r in records if r.exit_reason=='hold']`）→ per pos bars_provider 取 bars → 构造 Trades(entry_price=pos.entry_price 预填, fill_status=FILL_ACCEPTED, 不走 Executor) → `path_return(apply_cost=True)` → **若 pr is not None 且非"截断 max_hold exit"**（pr.exit_reason=='max_hold' 且 exit_idx==len(bars)-1 = 截断 → 留 hold 不标 realized，等更多 bars）：**直接构造 `JournalRecord(signal_id=pos.signal_id, ...)` 绕过 .create()**（.create() 生新 UUID，无法 INSERT OR REPLACE 同 signal_id 幂等更新；`cls(signal_id=str(uuid.uuid4()),...,**kwargs)` 传 signal_id 会 TypeError）→ INSERT OR REPLACE 同 signal_id（trade_journal.py:162 幂等）更新为 is_realized=1 + net_pnl + exit_date + exit_price=pr.exit_price（C2/SH5/SH7）。
- [ ] R4 **target_date 修正 + _latest_close 过滤**：run_daily 默认 target_date 改 `prev_trading_date_str()`（:91 从 last_trading_date_str 改，R4 fix C5；不只 executor 传参，default 也要改防其他调用方复发）；**`_latest_close(bars, target_date=None)` 加 target_date 参数**，返 bars 中 date<=target_date 的最后一根 bar close（非 reversed 最后一根），适用 _process_floor（:274）+ update_floor_mtm（:317）防历史重跑前视（SH2）。
- [ ] R5 **ETF code fix**：`journal_recorder.py:240` 改 `from strategies.index_replication_floor import ETF_CODE` 替代硬编 "510300"（C1）。
- [ ] R6 **exit_price fix（三分支）**：`accounting.py` PathReturn dataclass 加 `exit_price: float = 0.0` 字段，**三分支均设**：stop→`exit_price=entry*(1+stop_pct/100)`（乐观水平，gap-through 未建模，fills_json 带 optimism_flag='gap_through_unmodeled'）；take→`exit_price=entry*(1+take_profit_pct/100)`（同）；max_hold→`exit_price=_bar_get(bars[exit_idx],'close')`（:165 已算）。`journal_recorder.py:193` 改 `exit_price=pr.exit_price`（替代 `position_notional/DEFAULT_SIZE`=entry_price bug，SH7）。**注：R6 覆写 S173 journal_recorder.py:24 "不改 accounting 接口"只读约束——S175 需在 PathReturn 暴露 exit_price，属 S173→S175 架构演进**。
- [ ] R7 **诚实标签 P0（真止血非矛盾）**：Recommendation.tsx 顶部加 §44-falsified 警告横幅 **+ 同时降 LEVEL_META "高质量关注" 绿色为灰/改标"§44证否·基因分" + 每条推荐卡加 §44-falsified per-item 标**（不只加横幅留矛盾徽章，SH4）。`components/ui/Disclaimer.tsx`（compact :8 + full :16）删"不推荐个股/不预测涨跌/不给买卖时机/不构成投资建议"→保留"历史统计特征，市场有风险"轻量提醒（CLAUDE.md §1.1 弱合规，§5.3 谋士 posture 允许方向性研判）。`components/layout/Layout.tsx:161` footer "不荐股·不预测·无倾向"→"模拟盘跟踪·真盘你定"。三处 posture 一致=谋士（献计+用户决）。
- [ ] R8 **验收 P0**：见 §6 A1-A2（可复现 test_s175_e2e.py mock bars_provider 跑 3 次 run_daily，A1/A2 拆分）。

### P1 — 多臂推荐 + PaperPortfolio（R9↔R10 接线）+ 诚实 UI

- [ ] R9 **多臂 RecommendationEngine + 读 PaperPortfolio.equity() sizing**：rework `backend/recommendation_engine.py`（gene-only §44 falsified，root 非 strategies/）为多臂——floor=ETF 批次计划（actionable，build_position_batches）**+ floor 仓位 sizing 读 `PaperPortfolio.equity()`（R10 接线，equity × floor_allocation / N batches，R9↔R10 接线点写进 §4，SH1 fix 空转）**；breakout=§44 selection 已证否·盘中 conditioning 未测（paper-only）；limitup/trend=mock 未就绪；gap=dead_arm 不推（gate is_dead_arm=1）。每臂带 honest_label（externally_validated / §44_falsified / mock_not_ready / dead_arm）+ coverage_rate + days_tracked。**grill C7**：breakout 标"§44 selection 已证否"非"weak signal"非"underpowered_tracking"。**诚实承认**：当前仅 floor 1 臂 actionable，breakout/limitup/trend/gap 返静态 honest_label 卡非动态信号——为 1 actionable 臂建多臂框架是用户拉回的取舍，3/4 槽位是空标签（非引擎泛化价值，留插槽等 conditioning harness）。
- [ ] R10 **PaperPortfolio（thin read-only wrapper，R9 接线消费）**：建 `engine/paper_portfolio.py`（~80 行）—委托 `trade_journal.equity_curve()` + `drawdown_breaker.full_status()` + `final_size()`，不存独立 state（S088 重算范式，DRY-acknowledged）。**价值（SH1 fix）**：scheduler executor 末尾调 `PaperPortfolio.equity()` 落盘，**R9 recommendation_engine 读它作 floor 仓位 sizing**（R9↔R10 接线，非空转）。
- [ ] R11 ~~portfolio overlay stub~~ → **deferred**（spec grill：stub 无 impl 无 consumer = 纯 YAGNI，移 deferred）。drawdown_breaker 接生产路径（executor 末尾 1 行调 `breaker.compute_drawdown()`）单独留 P1（不依赖 overlay stub）。EWMA/MAB/SRTS + overlay 接口骨架全 deferred 待 ≥2 validated 臂 + 60d vol input。
- [ ] R12 **推荐 UI + 诚实标签（dormant 臂有数据源）**：`Journal.tsx`/`JournalLedger.tsx` 扩展（**不建 /trade-desk 新页**，属 page-architecture-redesign 独立 spec）——加 floor 批次推荐面板（actionable）+ 其它臂 honest 状态卡（**dormant 臂 honest_label 数据源**：后端 closed-loop 端点返 dormant 臂 stub 条目 {arm, honest_label, zero_data:true}，前端渲染灰卡；非硬编码）+ ArmStatCard 加 verdict badge + dsr_method 标（lenient_single_estimate→"宽松估计"，N/A→"不适用"）+ mock 标识（"(mock)·非真实信号"，解析 fills_json.mock）+ PaperNotRealBanner（静态警告 + 动态跟单 gap）+ underpowered 顶置 + **Sharpe n<60 标"未年化"（显 sharpe_n_days，contract:488 已有）** + **cap 标签**（"lift cap 未接 trade_journal sizing 路径"，C6/SH）+ **保留现有 coverage_rate/unbuyable/Wilson CI 显示**（防重构丢）。R9/R12 明确**删旧 /api/recommendation/today gene 卡 + LEVEL_META，替换为多臂面板**（非并存，SH4 fix）+ `lib/api.ts` StockRecommendation type 更新（多臂数据无 gene_score，旧 type 期望会 crash）。
- [ ] R13 **验收 P1**：GET /api/recommendation/multi-arm 返 floor actionable + 其它 honest 标签；JournalLedger 显 verdict badge + dsr_method + mock 标识 + 横幅 + cap 标签 + dormant 臂 stub 卡。

### P2 — 跟单 flow（R14）+ 4 源 gap（R15-R17 永久 dormant 除非方向转）

- [ ] R14 **跟单 flow（per-fill fees 匹配 S166）**：POST /api/journal/follow-order {signal_id, fills:[{side, date, price, shares, fee?}]}（**改 per-fill fees 非 real_cost_pct 聚合百分比，匹配 S166 journal.py Fill.fee 数据模型，journal.py:120 _fee_of**）→ 复用 `journal.py` 手动账本（S166，C7 隔离 winrate.db）加 signal_id 关联 → 算 paper-vs-real gap = real_pnl - paper_pnl。**FollowDecisionModal 提供成本计算器引导**（输入佣金率/免五/印花→算 cost_pct 供用户校验，散户易错）。**FollowDecisionModal 不下单**（系统不碰用户真钱），只记录用户自报成交。
- [ ] R15 **4 源 gap 分解（dormant，诚实标激活条件不可达）**：gap 四源——unbuyable/滑点/T+1/成本。结构建好，**诚实标"激活条件当前不可达"**：breakout §44 falsified 不会 validated（memory s168：12 harness 全 falsified 无 validated edge）；floor ETF 无 unbuyable/T+1 问题（spec 自承"对 floor overkill"）；§44 验证已停（memory pragmatic-selection-priority）。即 4 源**永久 dormant 除非未来 validated 盘中臂出现**——非"暂时等插槽"（spec grill 纠正 v1 自欺包装）。价值在 follow-order flow 本身（R14 用户跟单手动账本）+ 未来若有 validated 盘中臂可激活 4 源。
- [ ] R16 **FollowOrderGap 组件**：复用 JournalLedger 模式，每笔跟单显 4 源 gap 分解 + 总 gap。未跟单显"未跟单（无法验证真盘偏差）"。dormant 状态显"激活条件当前不可达（待 validated 盘中臂）"。
- [ ] R17 **验收 P2**：POST follow-order 后 GET /api/journal/gap 返 gap 分解（dormant 显"激活条件不可达"）；FollowOrderGap 渲染。

### Deferred（grill YAGNI + spec grill + 用户未拉回）

- §44 R3 enforce 自动复验（C3：DIMENSION_LIFT_REGISTRY 静态，Recorder.save 不回写；0 可毕业臂）——S175 仅读 days_robust 作诚实标签"lift cap 未接 trade_journal sizing 路径"。
- conditioning harness 作信号生成器（§44 falsified selection，应作数据收集器写盘中 OFI 到独立 intraday store 非 喂 trade_journal）。
- ash-mcp B 臂（gh-proxy clone + smart-beta capped，floor 验证后补）。
- /trade-desk cockpit + SplitLayout + nav 5→7（属 page-architecture-redesign 独立 spec）。
- 多臂 signal 生成器（打板 conditioning / 趋势 7 维 / limitup hithink wire）——等 conditioning harness。
- **R11 portfolio overlay 接口骨架 + EWMA/MAB/SRTS impl**（spec grill：stub 无 consumer 无 impl = 纯 YAGNI；待 ≥2 validated 臂 + 60d vol input 再建完整含 stub；drawdown_breaker 接 executor 生产路径 1 行留 P1）。

## 4. 受影响文件（spec grill SC2 修三路径）

| 文件 | 改动 |
|---|---|
| `backend/engine/bars_provider.py` | **已实现 v1，R1 补 ETF bar 规范化**（{date,close}→{date,open:close,high:close,low:close,close}，SH6） |
| `backend/scheduler/executors/journal.py` | **新建** R2 — trade_journal_daily domain 函数 |
| `backend/scheduler/executors/__init__.py` | R2 — _executors 加 dispatch entry + thin wrapper |
| `backend/scheduler/seed.py` | R2 — 加 cron `45 16 * * 0-4` trade_journal_daily |
| `backend/strategies/journal_recorder.py` | R3 settle_pending_breakout 新方法（截断 max_hold 留 hold + signal_id 绕过 .create()）+ R4 target_date=prev + _latest_close target_date 参数 + R5 ETF_CODE import + R6 exit_price=pr.exit_price |
| `backend/engine/accounting.py` | R6 — PathReturn dataclass 加 exit_price 字段（三分支均设：stop/take/max_hold，SH7） |
| `backend/recommendation_engine.py`（**root 非 strategies/**，SC2 fix） | R9 — rework gene-only→多臂 + honest_label + **读 PaperPortfolio.equity() sizing（R9↔R10 接线，SH1）** |
| `backend/engine/paper_portfolio.py` | **新建** R10 — thin read-only wrapper（委托 trade_journal+drawdown_breaker，R9 消费 equity） |
| `backend/routers/journal.py` | R14 — POST /api/journal/follow-order + GET /api/journal/gap（不改 18 现有端点） |
| `backend/routers/recommendation.py` | R9 — GET /api/recommendation/multi-arm |
| `backend/journal.py` | R14 — add 入口（routers/journal.py:104 journal_add 路径 + journal.py _save/_load_raw）加 signal_id 关联（S166 手动账本扩展） |
| `frontend/src/components/journal/JournalLedger.tsx` | R12 — verdict badge + dsr_method 标 + mock 标识 + PaperNotRealBanner + underpowered 顶置 + Sharpe 未年化 + cap 标签 + dormant 臂 stub 卡 + 保留 coverage/CI/unbuyable |
| `frontend/src/pages/Recommendation.tsx` | R7+R12 — §44-falsified 横幅 + 降 LEVEL_META + per-item 标 + 删旧 gene 卡替换多臂面板 |
| `frontend/src/components/ui/Disclaimer.tsx`（**ui/ 子目录**，SC2 fix） | R7 — 弱合规更新（compact+full 删"不推荐/不给买卖时机"→"市场有风险"） |
| `frontend/src/components/layout/Layout.tsx`（**layout/ 子目录**，SC2 fix） | R7 — footer :161 "模拟盘跟踪·真盘你定" |
| `frontend/src/lib/journal-contract.ts` | R9+R12 — **新建 ArmAggregate 类型含 s44_verdict**（非"加字段"，类型不存在）+ FollowDecision 类型 |
| `frontend/src/lib/api.ts` | R9 — StockRecommendation type 更新（多臂数据无 gene_score） |
| `backend/tests/test_journal_recorder.py` | R3+R6 — settle_pending 测试（截断 max_hold 留 hold + signal_id bypass）+ exit_price 三分支测试 |
| `backend/tests/test_bars_provider.py` | **已实现 v1，R1 扩 ETF bar 规范化测试**（open/high/low=close） |
| `backend/tests/test_s175_e2e.py` | **新建** R8 — mock bars_provider 跑 3 次 run_daily e2e（A股 mock bars + ETF 512890 mock bars 含 open 延伸到 T+2+max_hold） |

## 5. 设计方案

### 5.1 整体自洽闭环（S175 = UNIFIER 串九层）

```
cron 16:45（盘后，kline_refresh 16:30 刷完 baostock_kline_cache.json）
→ TaskExecutor._execute_trade_journal_daily [BREAK-0 修复 R2]
→ JournalRecorder.run_daily(target_date=T-1, arms=['floor','breakout']) [R4]
  ├ settle_pending_breakout() [R3 新方法，重算昨日 'hold'；截断 max_hold 留 hold；signal_id 绕过 .create()]
  ├ floor: build_position_batches() → bars_provider(ETF_CODE='512890')→fetch_etf_hist→规范化{open:close,...} [R1+R5+SH6] → MTM(unrealized_pnl, _latest_close target_date 过滤 [SH2])
  ├ breakout: select_premarket_candidates(T-1) → T1OpenFill(T 成交) → path_return(apply_cost=True, exit_price=pr.exit_price 三分支) [R6]
  └ gap/limitup/trend: 不跑（DEFAULT_ARMS=2 臂，C4）
→ accounting(path_return 净口径 / floor MTM)
→ TradeJournal.insert → trade_journal.db (C7 隔离 winrate.db)
→ aggregate_by_arm(复用 s44_verifier: day_clustered_t_test+Wilson CI+DSR+haircut+underpowered gate) [注：floor aggregate 恒 empty by design，floor 永远 is_realized=0]
→ PaperPortfolio.equity() [R10，scheduler 路径，R9 recommendation_engine 读作 floor sizing（R9↔R10 接线）]
→ drawdown_breaker.compute_drawdown() 接生产路径（executor 末尾 1 行，R11 overlay stub deferred）
→ 多臂 RecommendationEngine [R9，读 equity sizing] → 推荐 UI [R12，删旧 gene 卡]
→ 跟单 flow [R14 per-fill fees] → 4 源 gap [R15-R17 永久 dormant 除非 validated 盘中臂] → 诚实呈现
→ KG/memory 沉淀 → north-star(诚实+扣成本能赚钱+三问)
```

### 5.2 诚实呈现规则（grill C6+C7+spec grill SH 落地）

- **verdict 多档**：falsified/validated/externally_validated/exploratory/underpowered/mock_not_ready/dead_arm。各臂显式标，不软化（breakout=§44_falsified 非"weak signal"非"underpowered_tracking"，C7/SH4）。
- **胜率必带 Wilson CI** 不秀裸点估计；**underpowered 标"样本不足·待积累"不判"劣于随机"**；**DSR 显 method**（lenient_single_estimate→"宽松估计"，N/A→"不适用"）；**Sharpe n<60 标"未年化"（显 sharpe_n_days）**；**保留现有 coverage_rate/unbuyable/Wilson CI 显示**。
- **cap 诚实（C6 精确措辞）**：lift_to_multiplier 在 scoring.py:66（gene 臂）+ routers/verifier.py:112（API R8 wiring）两处，**但均不在 trade_journal→drawdown_breaker→per-arm sizing 路径**；drawdown_breaker underpowered multiplier=1.0（:114-116）非 ×0.5。S175 诚实标"**lift cap 未接 trade_journal sizing 路径（drawdown cap 经 final_size 已接但 days<60 underpowered=1.0 no-op）**"，不假装 enforced。
- **gap audit 走独立脚本**：gap 臂 dead_arm 不跑 run_daily（C4），§44 gap 复盘走 `tools/s44_gap_run_60d.py`（f833e8b 已接 gap_net_return 真成本）。

### 5.3 谋士 posture（献计不替决，三处 posture 一致）

- 系统=模拟盘+推荐+模拟闭环+诚实跟踪（paper PnL 真成本 apply_cost=True，给推荐各臂 honest_label）。
- 用户=看推荐+跟踪→选择跟单（真盘用户定）——follow-order 不下单（系统不碰用户真钱），只记录用户自报成交，事后对比 paper vs real gap。
- 弱合规（CLAUDE.md §1.1）：系统可给方向性研判+买卖时机+收益预期，**三处 posture 一致=谋士**：footer "模拟盘跟踪·真盘你定" + Disclaimer "市场有风险"轻量提醒（删"不给买卖时机"）+ Recommendation subtitle 改多臂措辞（删"教育研究式关注清单（非交易建议）"）。

### 5.4 取舍（grill+spec grill 核证据后）

- **不建 §44 R3 enforce 自动复验**（C3：DIMENSION_LIFT_REGISTRY 静态，0 可毕业臂）——S175 读 days_robust 作诚实标签。
- **PaperPortfolio 建 thin wrapper + R9 接线消费**（用户拉回 + spec grill SH1 fix）——承认 DRY（trade_journal.equity_curve 已聚合），价值在 R9 读 equity sizing（非空转）。
- **R11 portfolio overlay stub 移 deferred**（spec grill：stub 无 consumer 无 impl = 纯 YAGNI）——drawdown_breaker 接 executor 1 行留 P1；EWMA/MAB/SRTS + overlay 骨架全 deferred 待 ≥2 validated 臂 + 60d vol input。
- **4 源 gap 建结构 + 诚实标激活条件不可达**（用户拉回 + spec grill SH fix）——breakout paper-only 无真盘记录可 diff，floor ETF 无 unbuyable/T+1 问题；**永久 dormant 除非未来 validated 盘中臂出现**（非"暂时等插槽"，v1 自欺包装纠正）。
- **不建 /trade-desk cockpit**（属 page-architecture-redesign 独立 spec）——S175 UI 扩展现有 Journal/Recommendation 页。

## 6. 验收标准

- [ ] A1 **P0 闭环跑通（可复现 e2e）**：`tests/test_s175_e2e.py` 用 mock bars_provider（A股 mock bars + ETF 512890 mock bars **含 open/high/low/close 延伸到 T+2+max_hold**），连调 run_daily 3 次（target_date 递进 T-1/T/T+1）+ settle_pending_breakout，断言 trade_journal.db 有 floor 512890 记录（unrealized_pnl 非 None，_latest_close target_date 过滤无前视）+ breakout is_realized=1 记录（net_pnl 非 None，exit_price != entry_price，**截断 max_hold 留 hold 非过早 realized**）。明示 ETF bars 走 mock 不走 akshare（离线可跑）。
- [ ] A2 **aggregate 拆分（floor 恒 empty by design）**：明示 floor aggregate 恒 empty（floor 永远 is_realized=0，aggregate 查 is_realized=1 → empty，by design）；A2 仅验 **breakout arm 有 stats**（n_picks>0, day_clustered_t_test/Wilson CI/DSR/coverage_rate 有值）+ **floor MTM 非 None**（独立于 winrate aggregate 的 unrealized_pnl 序列）。
- [ ] A3 **诚实标签**：Recommendation.tsx 显 §44-falsified 横幅 **+ LEVEL_META 降饱和/改标 + per-item 标**（非矛盾，SH4）；删旧 gene 卡替换多臂面板；JournalLedger ArmStatCard 显 verdict badge + dsr_method + mock 标识 + 纸面≠真盘横幅 + cap 标签 + dormant 臂 stub 卡 + Sharpe 未年化 + 保留 coverage/CI/unbuyable；Disclaimer/footer/subtitle 三处 posture 一致=谋士。
- [ ] A4 **多臂推荐**：GET /api/recommendation/multi-arm 返 floor actionable（**含 equity sizing**，R9↔R10 接线）+ breakout/limitup/trend/gap honest_label（breakout=§44_falsified 非 weak，C7）。
- [ ] A5 **PaperPortfolio（R9 消费，非空转）**：scheduler executor 末尾调 PaperPortfolio.equity() 返非 initial_capital 值（注入 mock bars 使 floor close≠entry 或 breakout return_pct≠0，避 0 值边界误判）；**R9 recommendation_engine 读 equity() 作 floor sizing**（GET /api/recommendation/multi-arm payload 含 equity_derived_sizing 字段，A4 联动，SH1 fix）。
- [ ] A6 **跟单 flow（dormant + active 拆分）**：A6a dormant——无 follow 记录时 GET /api/journal/gap 返 {status:'dormant', label:'激活条件当前不可达（待 validated 盘中臂）'}；A6b active——POST follow-order（per-fill fees，关联某 breakout is_realized=1 记录，依赖 A1 breakout realized）后 GET gap 返 4 源分解（unbuyable/slippage/T+1/cost）+ 总 gap。
- [ ] A7 **cap 诚实（行为+文字）**：drawdown_breaker.size_multiplier(arm) 在 days_tracked<60 时返 (1.0,'underpowered') 且 final_size 不乘 0.5（行为验证）；UI 显"lift cap 未接 trade_journal sizing 路径（drawdown cap 已接但 underpowered=1.0 no-op）"标签（文字，C6 精确措辞）。
- [ ] A8 **私有隔离**：trade_journal.db 写 .vibe-research/（vr_paths.resolve_data_dir()），不进 git（.gitignore line 72）。

## 7. 合规与工程底线自查

- [x] 研判/推荐/买卖时机属系统能力（CLAUDE.md §1.1 弱合规）——Disclaimer 简化"市场有风险"轻量提醒，footer/subtitle 改谋士 posture，Recommendation 加 §44-falsified 横幅 + 降 LEVEL_META 不假装 edge（C7/SH4）。
- [x] 判断可复现——accounting path_return/gap_net_return 真成本（path_return apply_cost=True，gap_net_return always 经 _cost_pct 无开关）；trade_journal aggregate_by_arm 重算范式（S088）；settle_pending 重算非读 cache；_latest_close target_date 过滤防历史重跑前视（SH2）。
- [x] 涨停四池/连板股榜——floor ETF 512890 公开标的，breakout 候选 select_premarket_candidates 客观选股，可呈现 code/name。
- [x] 用户私有数据——trade_journal.db/.vibe-research/ 不进 git（.gitignore line 72），VR_DATA_DIR 防 home 分裂。
- [ ] **东财端点走 em_get——⚠️ 部分满足（spec grill SC1 如实纠正）**：bars_provider ETF 分支用 akshare `fund_etf_hist_em`（IS 东财数据，经 akshare push2delay 延时镜像 + sleep≥2s，**非 em_get 全防护**——无 circuit_breaker/代理降级）。单 ETF 日调一次封禁风险低，但**不满足 §1.2 "东财走 em_get 限流/熔断/代理"全防护**。取舍：单 ETF 日调封禁风险可接受（vs em_get wrapper 复杂度），如实标弱保护非虚假声称"非东财"。A股 cache 来自 baostock（不限流）。

## 8. 测试计划

- `cd backend && .venv/bin/python -m pytest tests/test_s175_e2e.py tests/test_journal_recorder.py tests/test_bars_provider.py tests/test_trade_journal.py tests/test_aggregate_stats.py tests/test_drawdown_breaker.py -v`（离线快测；test_s175_e2e mock bars_provider 跑 3 次 run_daily；settle_pending 截断 max_hold + signal_id bypass + exit_price 三分支 + ETF bar 规范化 + _latest_close target_date 新测试）
- `cd frontend && npx tsc --noEmit` 零错误
- TestClient 验收端点（memory devserver-port-occupied-use-testclient）：GET /api/recommendation/multi-arm + POST /api/journal/follow-order + GET /api/journal/gap
- test_s175_e2e 手动验收 A1（mock bars 跑 3 天，trade_journal.db 有 floor+breakout 真记录）
- newsradar flaky deselect（memory newsradar-flaky-network-test）：`--deselect tests/test_newsradar.py::test_fetch_global_intel_wm_import_fails`

## 9. 风险与回滚

- **bars_provider 双源+ETF 规范化**：A股 cache + ETF fetch 两路径，ETF bar 须规范化补 open/high/low（SH6）。回滚：ETF 分支加 cache_response(ttl) + 失败降级昨日 close。
- **settle_pending 性能 + 截断 max_hold 判断**：每日重算所有 is_realized=0 'hold'，4106 股 breakout 候选多时可能慢（memory c2-cold-cache-timing）。缓解：per-code bars_provider 读 cache O(1)；截断 max_hold 检查（exit_idx==len-1）O(1)。
- **cron 16:45 kline 未刷完**：baostock 5226 股日更可能 >15min。缓解：executor 检查 cache mtime >= today 16:30，未刷完标 status='waiting_for_kline_refresh' 跳过（degraded 非 crash）。
- **§44 R3 不建**：days_robust 静态，0 validated 臂——S175 诚实标"lift cap 未接 trade_journal sizing 路径"，不假装。回滚：如需 enforce，后续 spec 建 dimension→arm 映射 + 动态 days_tracked。
- **4 源 gap 永久 dormant**：激活条件当前不可达（breakout falsified/floor 无 4 源问题）——诚实标非包装"暂时等"。价值在 R14 follow-order flow 本身。回滚：若未来 validated 盘中臂出现再激活。
- **worktree 隔离**：.vibe-research/ symlink 到主仓，trade_journal.db SQLite WAL 跨 worktree 并发写——单写入者 journal_recorder（C7 已隔离 winrate.db）应安全，需验证。

---

关联 memory：`paper-trading-self-consistent-frame-2026-09-09` + `s173-trade-journal-impl-done` + `gap-edge-cost-never-wired` + `expert-round-portfolio-overlay` + `buy-what-when-buy-when-sell-three-questions` + `dont-t-rush-workflows-rigor-first`（spec grill 7 视角核证据非照单全收——主 agent 验证 SC1/SC2/SH1 全真）+ `spec-scope-mis-trace-pattern`（§4 三路径重犯，已修）。
