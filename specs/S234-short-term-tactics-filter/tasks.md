# S234 tasks.md - 可执行 checklist

> 依赖序：filter.py → commander 接入 → cron → 测试
> 状态：降级完成版收口（2026-10-17）。Phase 1-4 核心已实现于 2184f92（核于 2026-10-07），T1.6 blocked（依赖 S235 Phase B 实时竞价）、T1.8/T1.9 deferred（数据源 plan stale：baostock bar 实际无 ltsz + falsified 战法过滤器边际低）
> 分支：develop（2184f92 已合）

## Phase 1: 核心排雷脚本 short_term_tactics_filter.py
- [x] T1.0 骨架建好（FilterResult dataclass + to_json + __main__）
- [x] T1.1 第一层财务过滤骨架（ST/5日均成交；市值+资产负债率降级 TODO hithink）
- [x] T1.2 第二层情绪因子匹配骨架（战法1 fbt代理/战法2换手+收盘位置；标 falsified verdict）
- [x] T1.3 JSON 输出（is_passed/risk_level/hit_rules/reason/safe_action/verdicts/tactics_meta）
- [x] T1.4 verdict 诚实标注（R30：战法1 direction-confirmed magnitude-uncertain / 战法2 假edge / 红利低波✅）
- [x] T1.5 不编主力意图（§1.2，只基于可观测量价/席位）
- [ ] T1.6 chasing 维度（gap>=3% 回避）—— 需 T+1 open 数据，待实时竞价接入（S235 Phase B 补）
- [x] T1.7 资金流梯度（inst_dominant exploratory）—— 2184f92 接 inst_dominant 到 filter 战法3_机构抱团 + commander（核于 2026-10-07）
- [~] T1.8 流通市值 30-150 亿 —— **deferred 2026-10-17**：plan 写"baostock kline ltsz" stale（baostock bar 实际无 ltsz，核于 2026-10-17），真源需重定（astock/akshare/hithink market snapshot）+ falsified 战法过滤器边际低 + T1.6 blocked 不完整。降级版用 ST+5日均成交。
- [~] T1.9 资产负债率 >85% 剔除 —— **deferred 2026-10-17**：同 T1.8，数据源需重定（akshare fetch_financial_substitute_factors 2s/票慢 + hithink financials）+ falsified 战法边际低。降级版不查负债率。

## Phase 2: commander 接入
- [x] T2.1 commander_runner 沸点期（score>70）调用 filter（commander_runner.py:119 调 filter_stock）
- [~] T2.2 候选池从 pre_market_workflow / funnel 取（不重造）—— 实际用 zt_history 涨停前 5，非 funnel（核 2184f92）
- [x] T2.3 verdict 诚实标注附仓位建议（commander_runner.py:105-113 position.verdicts）

## Phase 3: 双时段 cron
- [x] T3.1 scheduled_tasks 加 sentiment_commander_morning (09:15)
- [x] T3.2 scheduled_tasks 加 sentiment_commander_close (14:50)
- [~] T3.3 复用 premarket_auction_notify (9:25) + daily_ai_summary (15:30) 框架 —— 实际用独立 sentiment_commander executor（非复用 premarket 框架，核 2184f92）

## Phase 4: 测试 + 验收
- [x] T4.1 pytest 第一层过滤测试（ST/成交额/市值）—— TestFirstLayerFilter
- [x] T4.2 pytest 第二层因子+JSON 输出测试 —— TestJsonOutput
- [x] T4.3 端到端跑通（commander + filter + 飞书）—— TestEndToEnd
- [x] T4.4 不臆造数据验收（所有因子从 cache 取）—— TestNoFabricationT44：cache 空时三战法不臆造 pass/match + filter 无网络依赖（核于 2026-10-07）
- [x] T4.5 不编主力意图验收（"主力意图"话术剔除或标"主观推断"）—— test_no_main_force_intent_fabrication

## 验收点（spec §4）
- [~] 第一层可跑（baostock + gene_scores + hithink）—— baostock/gene ✅，hithink 市值/负债率待 T1.8/T1.9
- [x] 第二层可跑（zt_history + dragon_tiger + intraday）—— inst_dominant 接 dragon_tiger，intraday 待
- [x] JSON 合法（5+字段）
- [x] verdict 诚实标注
- [x] 不编主力意图
