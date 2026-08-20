# Spec: S088 — 盘前暴风雨预测模型

> 状态：Q1/Q4/Q5/Q2/Q3 已实施（commit b29afa6 承重修复 + 本轮 Q2/Q3 探测落地），待 push。Q6 done。R10 blocking（scheduled_tasks 并发重构中）。见 §10/§11。
> 作者：lzw9560　日期：2026-08-20
> 关联：S063（SentimentContext 事后 STI 检测）/ S087（语境 tab 接入）/ S086（战法 pipeline）
>
> grill 记录：经 grilling skill 多轮审查（极端行情预测可行性 + 因子优先级），用户全部认可。
> 2026-08-20 二次对抗性核实：6 agent 并行反例尝试，发现 Q1 修不彻底（T-1 语义偷换）、Q5 阻塞性取数 bug（items 取不存在的顶层键）、Q4 真实 wiring 缺口（仅 ④⑤ 非 handoff 说的四字段全缺）。详见 §10。

## 1. 问题 / 目标

0819 暴风雨行情损失惨重。现有 `sentiment_weather` STI 是**事后检测**（盘后 15:30 算，用当日已发生跌停家数），盘前无预测。外围信息（美股隔夜收盘 + A50 期货夜盘 + 新闻盘后发酵）跟 A 股有**时差优势**，可用于盘前预测当日天气情绪。

**目标：建独立盘前暴风雨预测模型（B 方案），盘前 8:00 用外围隔夜 + 前日内部先行 + 估值水位 + 新闻密度 + 日历，算"暴风雨概率分"(0-100) + 推荐仓位，接入语境 tab。跟事后 STI 互补（盘前预测 + 盘后检测验证）。**

## 2. 背景

- 现有 STI（`sentiment_weather._calculate_weather_state`）：5 因子全市场内部事后数据（STI/risk=跌停家数/sector_continuity=涨跌比/capital_momentum/ public_sentiment），盘后算。
- 0819 STI score=7.73（冰点）/ 跌停 118 / STI 暴跌 26 —— 事后监测到，但盘前无预警。
- 外围数据源**已有但没用于预测**：`market.get_global_indices`（美股三大/A50/港股/大宗，含隔夜）、`newsradar._fetch_global_intel`+`fetch_radar`（全球情报+12 赛道 RSS）、`gene_scores`（前日连板/炸板率/溢价率/封板率）。
- 估值水位（全市场 PE/PB 历史分位）需算（数据源待定，可能 astock 或代理）。
- 衍生品（VIX/期权 PCR/期货贴水/融资余额）预测力最高但数据难接——**先跳过**，用现有数据源。

**诚实判断**（20 年量化视角，不迎合"能预测"）：暴风雨纯预测不可行（黑天鹅不可测），但**"条件积累可监测"**——外围隔夜大跌 + 前日内部情绪转弱 + 估值高位 + 利空新闻密度 → 暴风雨概率升高。产出是**概率分 + 仓位前置**，不是 100% 预测，是降低被黑天鹅重伤的概率。

## 3. 需求清单

- [ ] R1：独立盘前预测模型（`storm_predictor.py`），跟事后 STI 分离（盘前预测 vs 盘后检测）
- [ ] R2：外围隔夜因子——美股三大指数收盘涨跌 + A50 期货夜盘 + 港股（`get_global_indices`，权重 ~40%）
- [ ] R3：前日内部先行因子——连板梯队高度（见顶信号）+ 炸板率趋势 + 涨停次日溢价率 + 封板率（`gene_scores`，权重 ~40%）
- [ ] R4：估值水位因子——全市场 PE/PB 历史分位（权重 ~20%；数据源待定，先跳过或代理）
- [ ] R5：新闻密度辅助——`newsradar` 盘后利空新闻密度（关键词热度，不先做 NLP 情绪量化）
- [ ] R6：日历事件风险加成——宏观日历（议息/CPI/PMI）+ 解禁日历 + 交易日历（节前/月末）
- [ ] R7：暴风雨概率分（0-100）= 加权因子 → 概率映射
- [ ] R8：推荐仓位映射——概率分 → 仓位建议（高概率降仓/空仓，低概率正常）
- [ ] R9：接入语境 tab（ContextTab 展示概率分 + 仓位 + 因子明细）
- [ ] R10：定时盘前跑（scheduled_tasks 8:00 触发，写 cache）
- [ ] R11：端点 `GET /api/sentiment/storm-predict?date=` 返概率分 + 因子明细 + 仓位

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| 新增 `backend/strategies/storm_predictor.py` | 预测模型：因子采集 + 加权 + 概率分 + 仓位映射 |
| `backend/routers/sentiment_weather.py` 或新 router | 加 `GET /api/sentiment/storm-predict` 端点 |
| `backend/scheduled_tasks.py` | 加 `storm_predict_pre` 定时任务（盘前 8:00，待并发编辑器重构完再补） |
| `frontend/src/components/workflow/ContextTab.tsx` | 接入暴风雨概率分 + 仓位 + 因子明细展示（R9） |
| `frontend/src/lib/api/` | 加 stormPredict api 封装 |

## 5. 设计方案

### 5.1 因子加权（第一档，grill 确认）

```
暴风雨概率分 = 外围隔夜×0.40 + 前日内部先行×0.40 + 估值水位×0.20
             + 新闻密度辅助（加分）+ 日历事件风险（加分）
```

- **外围隔夜**（0.40）：美股三大涨跌均值 + A50 夜盘 + 港股。美股大跌 + A50 跌 → 外围因子高分。阈值：美股跌>2% / A50 跌>1% 触发。
- **前日内部先行**（0.40）：连板梯队高度见顶（前日 max_boards 高 → 见顶信号）+ 炸板率上升 + 涨停次日溢价率转负 + 封板率下降。这些是 A 股情绪高潮→崩盘先行。
- **估值水位**（0.20）：全市场 PE/PB 历史分位（高位易暴风雨）。数据源待定——先跳过（权重临时分给外围+内部）或用代理（如全市场涨跌位置）。
- **新闻密度**（辅助加分）：newsradar 盘后利空新闻数量 + 关键词热度 → 加分（不先做 NLP）。
- **日历**（辅助加分）：议息日/CPI 日/大额解禁日/节前 → 风险加成。

### 5.2 概率映射 + 仓位

| 暴风雨概率分 | 风险等级 | 仓位建议 |
|---|---|---|
| 0-30 | 低 | 正常（100%） |
| 30-50 | 中 | 降仓（70%） |
| 50-70 | 高 | 半仓（50%） |
| 70-100 | 极高 | 空仓/轻仓（20-30%） |

### 5.3 取舍

- **独立模型 vs 加因子到 STI**：选独立（B）—— STI 是事后检测，混入外围因子口径乱；独立盘前预测清晰，互补。
- **衍生品因子（VIX/期权/期货）**：先跳过（数据难接），用现有数据源搭骨架，后续接衍生品增强。
- **新闻 NLP 情绪量化**：先跳过（工程量大），只抓密度。
- **估值水位**：数据源待定，先跳过或代理，不臆造。

## 6. 验收标准

- [ ] A1：`storm_predictor.py` 算出暴风雨概率分（0-100）
- [ ] A2：外围隔夜因子读 `get_global_indices` 正确（美股/A50/港股涨跌）
- [ ] A3：前日内部先行因子读 `gene_scores`（连板/炸板率/溢价率/封板率）
- [ ] A4：概率分 → 仓位建议映射
- [ ] A5：`GET /api/sentiment/storm-predict` 返概率分 + 因子明细 + 仓位
- [ ] A6：语境 tab 展示暴风雨概率分 + 仓位 + 因子明细
- [ ] A7：0819 回测验证——用 0818 外围+内部数据预测 0819，概率分应高（事后验证）
- [ ] A8：既有端点 0 回归（不破坏 STI/sentiment_weather）

## 7. 合规与工程底线自查

- [ ] 研判/预测属系统能力（CLAUDE.md §1.1 弱合规）；挂轻量风险提醒「概率预测非确定，市场有风险」
- [ ] 判断可复现：因子来自公开数据（美股/A50/新闻/gene_scores），禁臆造
- [ ] 估值水位数据源不臆造（缺数据标 missing 降级，不编）
- [ ] 新增端点无东财直连（走既有 em_get/数据源）
- [ ] 用户私有数据未进 git

## 8. 测试计划

- 单测：storm_predictor 因子采集 + 加权 + 概率映射（mock get_global_indices/gene_scores/newsradar）
- 0819 回测：用 0818 数据预测 0819，验证概率分高
- 既有端点回归：STI/sentiment_weather 0 回归

## 9. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 估值水位数据源缺 | 中 | R4 先跳过或代理（权重临时给外围+内部），不臆造 |
| 新闻密度无 NLP | 低 | R5 只抓数量不量化情绪，辅助加分 |
| 衍生品因子跳过 | 中 | 第一档用现有数据搭骨架，后续接 VIX/期权增强 |
| 概率分预测力 | 中 | A7 0819 回测验证；诚实标注概率非确定 |

回滚：删 storm_predictor.py + 端点 + ContextTab 接入（纯新增，无数据迁移）。

## 10. grill Q1-Q6 决议记录（2026-08-20 对抗性核实）

> 6 agent 并行反例核实，每项跑"找反例调用点 / 验 done 是否真生效 / 扫更深 bug"。结论：Q6 done；Q1/Q2/Q3 partial（done 被高估）；Q4 partial（认知成立，补丁就绪）；Q5 pending（种子方向对但低估阻塞性取数 bug）。

### Q1 — storm-daemon T-1 快照　状态：partial（修不彻底）

种子称已修历史 bug（0819 预测取了当日外围没预警）。核实**反驳**：
- `storm_daemon.py:72-88` `get_t1_global_snapshot` 用 `last_trading_date(d)` 算 T-1 文件名
- `vr_paths.py` `last_trading_date(d)` 在 d 为交易日时**返回 d 本身**（实测 `last_trading_date(2026-08-19)=2026-08-19`）→ 预测 0819 读 `0819.json`（当日快照）而非 `0818.json`（前一日夜间），与要修的 bug 同源
- `storm_daemon.py:119` 模块级 `start()`，但全仓仅 `storm_predictor.py:69` lazy import 触发，`app.py` lifespan 无接入 → 冷启动当日无快照必 fallback，首次 fetch 等 30min
- 实测：`storm_snapshots/` 目录不存在 → `get_t1` 必返 None → 外围因子恒 fallback_current

成立部分：conftest `VR_STORM_DAEMON=0` 真禁、daemon 线程不阻塞、fallback 标注透明。**待办**：
1. `get_t1_global_snapshot` 改用"先退一日再回退交易日"（`last_trading_date(d - timedelta(days=1))` 或新增 `prev_trading_date(d)`），确保预测 0819 读 0818.json
2. `app.py` lifespan startup 加 `import strategies.storm_daemon`（触发模块级 start）或显式 `storm_daemon.start()`
3. 补 `tests/test_s088_storm_predictor.py` 覆盖 A7（0819 回测）

### Q2 — 日经225 secid + 权重0.15　状态：partial（核心前提未验证）

种子称已 done。核实**反驳**：`gstock.py:32` 注释"试 secid 确认"=作者自认未验证；`gstock.py:24`"均已实测"只覆盖原 6 指数。akshare 证 `100.N225` 在 **clist/get 批量端点**有效，但 `gstock._push2_stock_get` 用的是 **stock/get 单引端点**（端点不同，不保证可用）。fetch 空则 `storm_predictor.py:96` `n225_chg=0.0` 静默归零、0.15 权重白给无再归一、detail 显示"日经 +0.00%"缺失与平盘不可区分。成立：commit+权重和=1.0。**待办**（live_emoney_block 推迟）：跑一次 live em_get 确认 stock/get 返 100.N225；加 per-index missing 标志 + 缺失项权重再归一。

**实测落地**（2026-08-20 探测 + 实现，本轮 commit）：100.N225 stock/get 返数据（price=66216 chg+1.36%）确认生效——agent 担心的"未验证"排除；per-index missing 标志 + 缺失项权重再归一已实现（`storm_predictor._collect_global_factor`，缺指数 detail 标"缺 X"、权重 ÷剩余和）。Q2 done。

### Q3 — SOX/纳指科技/KOSPI secid　状态：partial（三者状态不同）

种子称 PENDING + search 风控。核实**反驳**两点：(1) KOSPI 非真未知——akshare `cons.py:173`+`index_global_em.py:28` 双重佐证 `100.KS11`（返空是错猜 `100.KOSPI` 名而非 `100.KS11` 码）；(2) "search 接口风控"标错对象——`gstock.py:86` 指数走 hardcoded secid + push2 stock/get，不经 search（search 仅个股）。未反驳：SOX 确无 push2 secid（走 datacenter `RPT_INDUSTRY_INDEX/EMI00055562`）、NDXT 全仓无证据（`100.NDXT` 仅规律猜）。**待办**（live_emoney_block 推迟）：KOSPI 可照 N225 先例加 `100.KS11` 后 live 验；SOX 换 datacenter 路线（不需 ut、走 em_get）；NDXT 需破"国外源不并入"约束或 yahoo/stooq。安全探测：≥10min 间隔、push2→push2delay 降级、照 `tools/first_board_quote_source_probe.py` 范式。

**实测落地**（2026-08-20 探测 + 实现，本轮 commit）：KOSPI `100.KS11` push2 返数据（price=6852 chg+5.89%，已加 `_INDICES`）；SOX datacenter `RPT_INDUSTRY_INDEX/EMI00055562` 返数据（report_date=08-19 value=11738 chg=-2.12%，已加 `_fetch_sox_datacenter` 分流进 `global_indices`）；NDXT `100.NDXT` push2 返空，**放弃**（SOX 已覆盖半导体周期同维度）。探测脚本 `tools/s088_secid_probe.py` + matrix 落 `.vibe-research/s088-secid-probe/`。Q3 done（NDXT 放弃）。

### Q4 — 八项 ④⑤ missing 补全　状态：partial（认知成立，补丁就绪）

种子称"四字段全缺"。核实**修正**：真正 wiring 缺口仅 ④⑤。生产路径 `funnel.py:471/568` `market_ctx=board`，而 `board=fetch_board_ladder`（`board_ladder.py:43-52`）只返 `{lianban_stocks}` 无 fbt/zbc → `eight_standards.py:114-116` `_check_seal_time`（④）与 `:151-153` `_check_reopens`（⑤）恒 missing。⑥ seal_amount 已在 `diagnosis.py:238-244` 从 `pool_item.fund` 接线（test_s085 实测生效）、① float_market_cap 已在 `diagnosis.py:139` 从 activity 接线。**待办**：`diagnosis.py:245` 调 `check_eight_standards` 前注入 per-card ctx：
```python
eight_ctx = dict(market_ctx or {})  # 必须拷贝：board 在 run_funnel 全 N 卡复用，直接赋值会泄漏上一只票 fbt
if pool_item:
    from strategies.first_board_filter import _fbt_to_hhmm, _to_float  # 复用，zt_pool_source:23 已有先例
    fbt = pool_item.get("fbt")
    if fbt is not None:
        hhmm = _fbt_to_hhmm(fbt)  # 必须经转换：_time_within 无法解析 5 位 fbt(92500→h=925 恒 fail)
        if hhmm is not None:
            eight_ctx["first_seal_time"] = hhmm
    zbc_raw = pool_item.get("zbc")
    if zbc_raw is not None:
        zbc = _to_float(zbc_raw)  # 须 coerce int：_check_reopens line163 r<=MAX 若 r 是 str 会 TypeError
        if zbc is not None:
            eight_ctx["open_count"] = int(zbc)
eight = check_eight_standards(ind, eight_ctx)
```
`_fbt_to_hhmm` 复用（跨包 `_` import 是 smell，最干净是下沉到共享位置，但最小可用=直接 import，不推荐下沉重复 15 行逻辑）。文件稳定：`diagnosis.py`(8/19)/`funnel.py`(8/19)/`first_board_filter.py`(8/19)，并发编辑器今日只动 `strategy_funnel_registry.py`。

### Q5 — 新闻利好对比　状态：pending（种子低估阻塞性取数 bug）

种子称 PENDING（缺利好对冲）。核实**补充**更优先的阻塞性 bug：`storm_predictor.py:161` `items = radar.get("items", [])` 取**不存在的顶层键**——`newsradar.fetch_radar` 返回 dict 顶层是 `industries` 嵌套（实测 keys=generated_at/recent_days/industries/stats），正确取法是 industries 遍历聚合。故 news 因子**恒返 50.0/missing，0.20 权重完全失效**。`storm_daemon.py:50` 同款 bug（T-1 快照 news_items 永远空）。另：`bearish_kw` 含"增长/合作/风险"等中性高频词，实测增长匹配 5 条——关键词口径本身需收窄到强情绪词。**待办**：
1. （必做，阻塞性）`storm_predictor.py:161` 改 `items = [it for ind in (radar.get("industries", []) or []) for it in (ind.get("items", []) or [])]`；`storm_daemon.py:50` 同改
2. （种子实质）收窄关键词到强情绪复合词：`bearish_kw=[暴跌,崩盘,跌停,退市,爆雷,违约,大利空,重挫,闪崩,熔断]`，`bullish_kw=[涨停,大涨,暴涨,突破新高,超预期,大订单,增持,回购,大利好]`；占比口径 `ratio=bearish/max(bearish+bullish,1)`，`score=ratio*100`（避免总量膨胀使差值失真）；`bearish+bullish==0` 返 50.0 标 missing；detail 输出三值可审计。权重 0.20 下对总概率分最大 ±10 分，足以跨 50→70 极高阈值，值得做。spec §5.3 NLP 跳过不违——关键词级属密度范畴。

### Q6 — 估值水位 R4 跳过　状态：done（无需修）

核实**确认**：grill 共识 A 已落地——`storm_predictor.py:10` docstring + `:233` 加权 0.35+0.35+0.20+0.10 + `:249` factors 列表无估值因子（非占位空壳），spec §3 R4/§5.1/§5.3 一致"先跳过、不臆造、权重重分"。commit `86e0e4a` 显列 Q1-Q6，Q6=A 估值跳过。无需修。相邻未完项（非 Q6 范畴）：R10 定时盘前 8:00（`scheduled_tasks._executors` 无 storm 条目，grep=0）——**blocking**，`scheduled_tasks.py` 当前 976 行并发编辑器 diff，须推迟到该文件稳定后。

## 11. 实施状态

- [x] push 9 commit（develop→origin，df0bd90..6cf9ecb）
- [x] Q5 取数 bug 修复（storm_predictor + storm_daemon）— commit b29afa6
- [x] Q1 T-1 计算 + lifespan 接入 + test_s088 回测 — commit b29afa6
- [x] Q4 八项 ④⑤ 补全（diagnosis.py）— commit b29afa6
- [x] Q2 日经 secid 实测生效 + 静默失败修复（per-index missing + 权重再归一）— 本轮
- [x] Q3 KOSPI(100.KS11)/SOX(datacenter) 实测加入；NDXT(100.NDXT) 返空放弃 — 本轮
- [blocking] R10 storm 定时任务（scheduled_tasks 并发重构中，待并发编辑器 commit 后补）
