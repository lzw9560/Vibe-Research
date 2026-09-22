# S218 — 投研参考交付系统（验证→可行动参考→收益闭环）

> 状态：已实现（2026-09-18，commit 96d9c3e/348de8f/effaa99）+ spec v3（2026-09-18，织入 spec-review `w5ety6ysa` 21 修订 + 2026-07-06 交易新规 caveat）。
> **scope 声明**：交付层——把唯一 validated edge（consecutive_relay）包装成用户能照着做的投研参考，**不是新验证机器**。复用现有基建（S211 consecutive_relay arm + scheduled_tasks cron + Feishu notify + StockCockpit + JournalWinRateCurve 图表基建 + pre_limitup_scanner + compute_regime_labels + lift_for_arm）。是 freeze 解后「做减法优先」下唯一允许的加法。
> 触发：用户 2026-09-18 纠正「process theater 不产收益」+ 要「研究验证→正确投研参考→照做」。
> **cross-cutting 诚实性框架**（所有报告/通知/dashboard 必标）：consecutive_relay 是**统计 validation 非已实现收益**——edge 衰减中（train 1.57%→test 1.04% 跌 34%）、paper-only（无券商/xtquant/qmt 只有 PaperPortfolio，×0.75 咬模拟盘名义股数非真钱，零真交易）、within-regime only（bull validated，bear/range<60 test 天没法定）、照做有风险。×0.75=研究诚实性标注（统计信心）非保本；真钱仓位/止损用户手动决策。per-战法 scope：只 consecutive_relay（n=1 validated，别推广 16 战法）。
> ×0.75=base1.0（chrono p=0.0054 n_test=57）×decay0.75（**判断性 haircut**：34% 衰减+WR 52.7% 薄+borderline power 综合定 0.75；非 1-0.34=0.66 机械推导）×regime1.0（bull validated）×zuoT1.0（做T中性）。

## 问题
§44 验证产出 verdict + cap（抽象数），没接成「可行动参考」——×0.75 是数不是「今日哪些接力股、怎么进、怎么出、风险多大」。验证→参考→收益闭环断了。**更深问题**：把 validation 当 closed-loop edge 呈现=process theater。本 spec 须每个组件过「这产收益吗还是只是看起来正确」。

## 目标（6 组件 + 1 扩展 roadmap，各复用现有基建，都要实现）

### 组件 1 · 每日信号报告（最直接产收益——用户能 T 日照着做）← 先做
**T 日 14:50 前生成**（T-1 zt_history lbc≥2 封板数据 T 09:00 已可用），用户 T 日 14:57-15:00 收盘集合竞价买入。**非盘后报告**——盘后报告错过 T 收盘=错过整个 edge（spec-review critical 修）。
复用 `pre_limitup_scanner.scan_consecutive_relay`（返 {code,lbc}，offline T-1）+ `compute_regime_labels`（full-map 查 target_date，或 `_regime_for_date` journal_recorder.py:328）+ `evaluation.lift_for_arm("consecutive_relay", regime)`（bull 返 0.75）。
- **报告头必标**：「统计验证（非已实现收益）；edge 衰减中（train 1.57%→test 1.04% 跌 34%）；paper-only 无券商（零真交易）；照做有风险；本系统不自动下单——产投研参考非自动交易，接券商前所有战绩 paper，要真实获益须手动在券商下单」。
- **3-bucket 分类**（2026-09-18 C1 验证后修：原"别碰=非 bull regime"对 bear 过保守——arm 实际 bear ×0.5 交易，bear edge 是 underpowered/indeterminate 非"不可交易"）：
  - **可做** = bull regime + lbc 2-3 + 非一字板（`_is_unbuyable_next_bar`）—— edge validated，×0.75。
  - **探索性** = bear/range regime + lbc 2-3 + 非一字板 —— arm 交易（×0.5 保守）但 edge underpowered/indeterminate（bear<60 test 天没法定，**非 bull-validated**）。标「bear edge 未 validated，×0.5 保守」。
  - **别碰** = 一字板（`_is_unbuyable_next_bar`）。lbc≥4 在 scanner 层已排除（`scan_consecutive_relay`→`_zt_history_lbc_ge2` 过滤 lbc 2-3）。
- **参考价**（非"D 收盘价"——pre-close 报告 T 14:50 生成时 D 收盘 15:00 还没有）：三级 fallback——target_date bar close / 最近缓存 bar close（带 source 日期）/ `query_quote` live 当前价。标「参考价 ¥X（来源 YYYY-MM-DD）；入场=今日 14:57-15:00 收盘集合竞价市价买，实际成交≈参考±小」。
- **预期收益**（+1.04% test 均值，非个股价格预测；实际出场=D+1 09:30 开盘价市价卖，个股波动远大于均值）+ edge 带衰减标注「+1.04%（test，train 曾 1.57% 跌 34%，p=0.0054）」。
  - **lbc 数字标注**：lbc=2/3 的 +0.90%/+2.05% 是 deep_dive 子条件分析数字（非 chrono forward-OOS 主验证结果）；chrono 主结果=bull 聚合 +1.04%（test）——报告 edge 数字用 chrono 主结果带衰减，lbc 数字仅过滤标注不作为独立验证 edge。
  - **name resolver 依赖**：`query_quote`（stock_tools.py:27）取名 + 参考价 fallback。
- **仓位标注**：「75%=统计信心 ×0.75=base1.0×decay0.75（判断性 haircut）×regime1.0×zuoT1.0；非保本；真仓位用户定」。
- **风险标一字跌停 realizability bias**：「`gap_net_return` 假设 D+1 开盘能卖，但 lbc≥2 股 D+1 一字跌停卖不掉→实际收益可能比测的差，待量化」非静态数字。
- **regime 新鲜度 check**：读 `_load_regime_cache()`（gap_regime_stratified.py:182）last-key 日期，标「regime cache 到 MM-DD（若滞后→实际 ×0.5 非 ×0.75）」。
- **人话**：「今日 N 只接力股可做（code+名+入场价+预期收益），M 只别碰（一字板/非牛市）」非术语堆。

### 组件 2 · 实时报警（第 4 优先，data-source-blocked）
intraday 监控涨停封板 lbc≥2 + bull regime → notify alert。
- **intraday lbc≥2 检测路径**（spec-review high 修，不能用 `scan_consecutive_relay` offline T-1）：(a) live 涨停池 via `em_get`/`zt_pool_source.fetch_zt_pool_map`(today) 取当日封板股 + `zt_history` prior-lbc 交叉比对（prior lbc+1=current lbc）识别 lbc≥2 intraday；OR (b) 降级为「17:15 封板确认后」EOD alert 复用 `snapshot_zt_pool`（zt_history_store.py:126，EOD 非真 intraday）。实现时二选一，推荐 (b) 先做（(a) 需 intraday 涨停池 live 数据）。
- **Feishu 路径**（spec-review medium 修）：复用 `scheduler TaskExecutor._send_notification`（executors/__init__.py:215）→ `NotificationService.send` → `FeishuSender.send_to_feishu`（notification/senders/feishu_sender.py:449）；富文本用 `send_feishu_card`（:507）。**不调 routers/feishu.py**（webhook endpoint 非复用 send path）。
- alert 标 lbc 等级 + regime verify（若 cache 滞后标「regime 未确认→保守 ×0.5」）+ 一字板 bias + 人话。

### 组件 3 · 关键点位决策通知
time-triggered（D 收盘 15:00 / D+1 开盘 09:30）。**复用组件 1 shared core**（`get_consecutive_relay_signals`，不重复 scan+regime+lift）。
- D 收盘入场通知「今日收盘买这些」+ D+1 开盘出场通知「开盘卖这些」。
- **【关键 framing】**「gap-down 诚实标通知」非「止损通知」。WHY：做T/补救对 1-bar gap 结构性不适用（无日内窗口/T+1 禁同日卖无底仓/exit=D+1 开盘 gap-down 点实现非 preempt/`record_t0_fill` 生产零调用）；**stop 对隔夜 gap-down 是仪式非保护**（`at_risk.py:17-19` §R3 诚实风险标签：止损价只在能成交价位生效，隔夜跳空可击穿止损价开盘）；真实风控=仓位 sizing（×0.75）+ gap-down 诚实标；`gap_net_return`（`accounting.py:262-285`）纯 2-price 无 stop/take/max_hold。
- 通知带 ×0.75 公式理由 + 一字跌停 gotcha（若 D+1 开盘一字跌停，出场可能卖不掉，实际收益比预估差）。

### 组件 4 · dashboard 强化
**StockCockpit.tsx**（`frontend/src/pages/stock/StockCockpit.tsx`）加 validated-edge 信号卡。复用现有 'signals' activePanel slot（:299）或加新 'validatedEdge' slot。
- **图表基建复用**（spec-review medium 修）：复用 `JournalWinRateCurve.tsx`（`frontend/src/components/journal/`）的 useECharts hook + GlassCard + Disclaimer pattern，**数据源新写**——衰减轨迹（train 1.57→test 1.04 二点 + p=0.0054 + WR 52.7%）；**勿直接复用 JournalWinRateCurve 本体**（它画 cumulative winrate-over-time，数据形状不对）。历史战绩 live paper 胜率曲线可复用本体。
- 信号卡标「provisional/within-regime only/衰减中」非「validated=可放心照做」。
- 衰减轨迹 + ×0.75 provisional 非 ×1.0（统一 ×1.0 gate 见组件 5）。
- 历史战绩显 paper P&L（标「模拟盘名义额，非真钱」）。
- cap 标注「×0.75=研究诚实性标注非资金保护」。
- regime cache 新鲜度指示（滞后标红「实际 ×0.5」）。

### 组件 5 · 阶段性汇总复盘
周度复盘 + **统一 cap 升降 gate** + process-theater 自检闭环。
- 本周信号实际表现（paper P&L，诚实标「只能看 paper，没真交易收益；接券商才有真 closure」）。
- **【统一 ×1.0 cap-up gate（spec-review medium 修，替组件 4/5 三处不一致）】**：升 ×1.0 须 **ALL** 满足：(a) bear 累积 120+ 天 cross-regime chrono 够 power (b) 60 天 re-check 衰减稳（decay 0.75→0.9）(c) lbc=3 积累 60 天——当前全不满足。降 ×0.5 = 衰减续恶化（>34%）OR 一字跌停 realizability bias 量化 material。
- **process-theater 自检（spec-review medium 修，替模糊 vibe check）**：weekly 复盘若 paper P&L mean<0 OR 衰减轨迹跨 negative → **自动生成 cap-down 提案（×0.5）交用户 review**（proposal 级，非自动降 cap）。
- consecutive_relay arm 待办 monitor：regime cache 滞后（升 ×1.0 前必修）+ K1 cache 滞后（baostock_kline_cache 到 09-11）致 picks hold。
- **创业板做市商结构性断点 §44 caveat monitor（留占位，后期实现——用户 2026-09-18 定）**：§44 forward-OOS 样本跨 2026-07-06 创业板做市商引入，edge 可能被 pre/post-做市商 regime 混淆；未来对创业板 picks 做 pre/post-2026-07-06 子样本分析。本次不跑，留占位。
- context：consecutive_relay 是 126 verdict 唯一 robust_edge（3% 稀有 positive），深挖子条件增强非堆新战法。

### 组件 6 · 证否战法再验（新增——bounded，非无限验证机器）
保留 + 再验 §44 证否的文献/经验背书战法。**复用 §44 selection-lift harness**（窗口/regime/combo 再验，不新建）；**trading-EV 复用 `path_return`（accounting.py:134，含 stop/take/max_hold）非 §44 selection harness**——两者不同测量轴（spec-review medium 修）。
- 保留 5 个：gene_score/turnover/path_lift/first_plate_h2/sector_phase。storm_reversal（未 validated）也在队列。
- 再验维度：换窗口/regime-pooled vs 单独 bull/bear/combo/trading-EV（path_return）。
- **【kill criterion（spec-review high 修，防 perpetual 验证机器）】**：每个证否战法**只再验一轮**。一轮后仍无 edge → 标「honestly falsified—frozen，停止再验」，退出周度队列。所有 5 个一轮内无 edge 复现 → 组件 6 自终止（无更多再验队列），符合做减法 + honest exit。
- 再验产出：周度报「证否战法再验进展」（哪个换窗口/regime/combo 测了，结果如何）→若复验出 edge 参考扩到组件 1-4，若仍证否诚实标 exploratory。
- **标组件 6 明确 non-revenue**（spec-review high 修）：产验证进展报告非收益；按用户决定保留不删；最低优先级；无 P&L 预期。
- 人话：「被证否的 X 战法换牛市单独测/换隔夜窗口测/跟 filter 组合测，看 edge 是否回来」。

### 扩展路径 / 多因子 roadmap（forward-looking 非 current scope，spec-review apply=False 保留）
- 当前只 consecutive_relay 单 edge。参考扩到多 edge 时用**去噪 5 层**（IC 前置剔非alpha→FF 残差化→FA 验族→PCA 冗余诊断→§44 walk-forward）非堆因子。先剥风险因子再降维（A 股 beta+波动率占大头）。walk-forward 验**载荷结构稳定非个数稳定**；选主成分数=过拟合超参须预注册。
- multi-factor banked（B_bank_for_later）：5 un-bank triggers 全满足才动五层（做减法 done/consecutive_relay cap 稳/S203 dims validated/FF-CH4 data acquired/consecutive_relay forward-OOS 稳不衰减 negative）——当前全不满足。
- open risk：consecutive_relay 若 live-monitor 衰减到 negative→多因子前提消失→honest exit。
- **声明：本节是 roadmap 非 S218 实现 scope**。

## 受影响文件
- `backend/tools/signal_report.py`（新）：**shared pure-fn core `get_consecutive_relay_signals(target_date)->dict`**（组件 1 + 组件 3 共用，不重复 scan+regime+lift）+ `render_daily_report(signals)->str`。内部：`scan_consecutive_relay`→`compute_regime_labels` full-map→`lift_for_arm`→filter 可做/别碰+`query_quote`(stock_tools.py:27)取名+`KlineCacheBarsProvider`(bars_provider.py:153)取价+`_load_regime_cache`新鲜度+`_is_unbuyable_next_bar`一字板过滤。
- `backend/scheduler/executors/signals.py`（新）：domain fns `daily_report`/`keypoint_notify`（复用 comp1 core）/`weekly_review`/`falsified_retest` + `intraday_alert`（组件 2，live 涨停池 or EOD 降级）。
- `backend/scheduler/executors/__init__.py`：`TaskExecutor._executors` 加 4-5 项 + thin `_execute_*` wrappers（mirror `_execute_limitup_precompute` :247）。
- `backend/scheduler/seed.py`（spec-review 补）：`_ensure_seed_tasks` 加 ScheduledTask 行（daily_report 14:50 pre-close / keypoint_notify 15:00+次日09:30 / weekly_review weekly / falsified_retest weekly）。
- `backend/routers/signals.py`（新）：`GET /api/signals/daily` + `GET /api/signals/status`（regime 新鲜度 + arm status）+ `GET /api/signals/falsified-retest`。app include_router 注册（mirror 现有 router）。
- `frontend/src/components/cockpit/ValidatedEdgeCard.tsx`（新）：useECharts+GlassCard+Disclaimer pattern（JournalWinRateCurve.tsx 同 pattern），数据新写（衰减轨迹二点+p+WR+provisional labels+paper P&L tag）。slot 进 `StockCockpit.tsx`（:299 signals slot 或新 validatedEdge slot）。
- 复用：consecutive_relay arm（`_process_consecutive_relay`→`_arm_size`→`final_size`→`lift_for_arm`，§44 cap 真咬 PaperPortfolio，2026-09-18 codegraph 核）+ `_send_notification` notify path + §44 selection-lift harness（组件 6）+ `path_return`（组件 6 trading-EV）。

## 验收（诚实性 gate 绑定具名 pytest——spec-review high 修，防 dev 静默跳过）
- **test_daily_report_header_marks_validation_not_realized**：assert header 含「统计验证」+「非已实现收益」+「paper-only」+「零真交易」+「照做有风险」+「非自动交易」。
- **test_daily_report_edge_carries_decay**：assert「1.57%」+「1.04%」+「34%」+「p=0.0054」present，+1.04% 带衰减标注非静态。
- **test_report_uses_ev_not_price_target**：assert「预期收益」present，「预估出场价」absent。
- **test_report_says_not_auto_trading**：assert「不自动下单/非自动交易/须手动下单」present。
- **test_regime_freshness_flag**：assert cache_date + stale flag present。
- **test_lbc_numbers_labeled_deep_dive_not_chrono**：assert +0.90%/+2.05% 标 deep_dive 过滤非 chrono edge。
- **test_dashboard_card_not_safe_to_act**：assert label ∈ {provisional, within-regime only, 衰减中}；assert「可放心照做」absent。
- **test_paper_only_pnl_label**：assert「模拟盘名义额」+「非真钱」+「接券商前所有战绩 paper」。
- **test_keypoint_notify_reuses_comp1_core**：assert 不重复 scan+regime+lift。
- **test_gapdown_is_honest_label_not_stop_loss**：assert「诚实标」present，「止损通知」absent。
- **test_cap_up_gate_uses_reconciled_definition**：assert ×1.0 gate = ALL（bear 120+天 AND 60d 衰减稳 AND lbc=3 60d）。
- **test_cap_down_triggers_on_decay_worsening**：assert 衰减>34% → cap-down 提案生成。
- **test_falsified_retest_has_kill_criterion**（**deferred to P2**，reality-check P1-4 2026-09-18）：C6 `falsified_retest` stub（`scheduler/executors/signals.py:536` 返 "skipped"），premature 到 consecutive_relay edge 真衰减才做。assert 一轮后无 edge → frozen 退出队列。
- **test_component6_labeled_non_revenue**（**deferred to P2**，同 C6 stub）：assert「non-revenue/产验证进展非收益」present。
- **实时 behavioral**（**deferred to P2**，reality-check P1-4 2026-09-18）：C2 `intraday_alert` stub（`signals.py:320` 返 "skipped"），data-source-blocked（live 涨停池须 intraday 数据，spec §6 组件 2 路径 (a) live 涨停池 or (b) EOD 降级）。real-time lbc≥2 涨停封板 + bull regime（regime cache 新鲜度 verified）触发 notify，标 lbc 等级 + 一字板 bias——deferred 到 live 涨停池数据可得后。
- 关键点位：D 收盘入场通知 + D+1 开盘出场通知 + gap-down 诚实标通知（非止损）。

**§4 验收状态**（2026-09-18 reality-check `s218-reality-check` P1-4）：12/14 named test + 1/2 behavioral 满足（C1/C3/C4/C5/P0 done，63 test green）。C2 intraday_alert + C6 falsified_retest = deferred to P2（stub，非隐藏 gap——C2 data-source-blocked 须 live 涨停池，C6 premature 到 edge 真衰减）。详见 memory `s218-reality-check-2026-09-18`。

## 合规自查（弱合规——私人助理，给方向性参考+风险标注，用户最终决策）
- 不臆造：信号来自现成 scanner+regime+lift_for_arm（2026-09-18 codegraph 核全链在），报告标 edge/胜率/衰减/风险；validation 数字来自 §44 verdict（chrono p=0.0054）。
- 私有数据隔离：信号记录在 .vibe-research/（不进 git）。
- 防封：scanner 复用 em_get+baostock（不裸调）。
- 不代客决策：给参考+风险标注，用户最终拍板+真仓位手动定。
- **validation 诚实性**（非合规仪式，是正确性）：所有报告/通知/dashboard 标 validation 非已实现收益+paper-only 无券商+edge 衰减中——「让胜率数字为真」的前提。

## 实现顺序（spec-review 修：加 P0 prereq + timing）
0. **P0 prereq：修 regime cache 更新机制**（index_ma20_regime.json 新鲜度）——否则 ×0.75 day-1 inert（regime=None→保守 ×0.5）。与组件 1 同步交付，非 C5 backlog。
1. 每日信号报告（组件 1，T 日 14:50 pre-close 生成 + deps name/price）← 先做
2. 关键点位决策通知（组件 3，复用 comp1 shared core）
3. dashboard 强化（组件 4，ValidatedEdgeCard）
4. 实时报警（组件 2，intraday live or EOD 降级）
5. 阶段性汇总复盘（组件 5，统一 cap gate + 自检提案 + 创业板 caveat 占位）
6. 证否战法再验（组件 6，bounded 一轮+kill criterion+non-revenue）

## 关联
- [[consecutive-relay-chrono-oos-supporting]]：唯一 validated edge，每日信号来源（stage-2 train 1.57%→test 1.04% 跌 34%，p=0.0054，×0.75 provisional）。
- [[process-theater-over-returns-and-§44-not-ground-truth]]：本 spec 对那纠正的响应——验证→可行动参考→收益，每组件标 validation 非定论。
- [[milestone-2026-09-18-pivot]]：freeze 解后转「验证唯一发现→交付参考」；本 spec 是做减法优先下唯一允许的加法。
- [[gap-edge-sizing-grill-2026-09-18]]：×0.75=base×decay×regime×zuoT 公式+做T 不适用+升降 gates——组件 3 framing+组件 5 cap 机制。
- [[multi-factor-reduction-methodology-2026-09-18]]：去噪 5 层+B_bank——扩展路径 roadmap 节。
- [[consecutive-relay-deep-dive-lbc3-sweet-spot]]：lbc=3 甜点/lbc≥4 死 edge——组件 1 可做/别碰过滤（lbc 数字标 deep_dive 非 chrono）。
- [[consecutive-relay-arm-live-wired]]：arm 生产 active+regime cache 滞后（P0 prereq）+ST 10% 适配（commit 1b9a4c2）。
- [[s44-lift-cap-bypassed-in-production-sizing]]：§44 cap 真咬 PaperPortfolio 名义股数（T4 DONE，2026-09-18 codegraph 核全链）。
- [[ashare-trading-rules-2026-07-06]]：2026-07-06 交易新规（ST 10% 已适配；创业板做市商=组件 5 §44 caveat 占位；盘后固定价格=组件 3 执行 venue 提一句）。
