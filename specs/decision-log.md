# 决策记录（Decision Log）

> 记录 Vibe-Research 项目中关键技术/架构决策。每条含：选择、理由、应用方式、被否决方案、日期、状态。
> 编号 DEC-NNN 递增。新增决策追加到文件末尾。

---

## DEC-001：S004 候选池漏斗性能优化技术路线

**选择：** 采用「漏斗级缓存 + 盘后预计算 + top-N 限界 + 独立 source 并行」组合方案优化 `run_funnel` 性能；**不**对 `fund_flow`/`catalyst` 做逐只并发。

**Why：** `astock.em_get` 有全局串行限流锁（QPS≤2）。`fund_flow` 逐只调用都走 em_get（每只 ~2s × ~100 只 ≈ 200s，为 >60s 主因）；逐只并行在锁约束下退化为串行，**无收益**且并发请求放大东财封 IP 风险。故性能杠杆排序为：缓存+预计算（主杠杆，把 ~200s 冷算挪到盘后离线，请求侧恒 ≤1s）> top-N 限界（r1_kept ~100→≤80，降预计算墙钟且封顶）> 独立 source 并行（仅对非 em_get 串行的 gene/board/auction 有真收益）。

**How to apply：**
- 按优先级实现 `specs/S004-candidates-funnel-performance/tasks.md`：B1 限界（`CANDIDATE_FUNNEL_MAX_R2` 默认 80）→ B2 缓存（`_FUNNEL_CACHE` TTL 300s + 路由 `@cache_response` 60→300）→ C1 并行（独立组 A 用 `ThreadPoolExecutor(4)`）→ D1 预计算（`TaskExecutor._executors["candidate_funnel_precompute"]`）→ E1/E2 验收。
- 复用各 source 既有 `em_get` 限流路径，**不裸调**东财（合规红线）。
- 回滚：恢复顺序 `run_funnel`、删预计算任务、TTL 回 60。

**被否决的方案：**
1. **fund_flow 逐只并发**：em_get 全局锁使并发退化为串行，反而放大封 IP 风险，收益为负。
2. **`run_funnel` 改 async 逐 source `to_thread`**：改动面大，source 内部仍串行 em_get，收益不如缓存+预计算；且 S003 已在路由层做 `asyncio.to_thread`，重复。

**日期：** 2026-07-29

**状态：** 已采纳（S004 spec 仍为草案，待用户审批后进入 TDD 实现）

---

## DEC-002：S018 第二批 macro 特征 7 系列定稿 + short_sector 计数 + pre-existing 失败处置

**选择：** `macro.py` 定稿 7 个 FRED 系列：us_10y_yield(DGS10)、dxy(DTWEXBGS)、us_fed_funds_eff(DFF)、us_10y2y_spread(T10Y2Y)、usd_cny(DEXCHUS)、wti_crude(DCOILWTICO)、lme_copper(PCOPPUSDM)。全部 `availability_offset=1`、`compliance_flag=ok`，进入 `HEAD_FEATURE_SUBSETS["short_sector"]` → short_sector 从 21 增至 **28**（s1 14 + external 4 + calendar 3 + macro 7）。live 冒烟 2026-07-31 通过（7/7 系列 fetch+parse 非空）。

**Why：**
- 覆盖率：债券利率（DGS10）、美元指数（DTWEXBGS）、资金成本（DFF）、收益率曲线（T10Y2Y）、人民币（DEXCHUS）、原油（DCOILWTICO）、铜（PCOPPUSDM）——覆盖汇率/大宗/利差/利率路径四类宏观信号。
- USDCNH 无 FRED 现货源，以 DEXCHUS（CNY/USD）替代离岸；已满足 spec「汇率/大宗/利差」最小集。
- short_sector 冲突（S018 7 macro vs 既有 21）以 live 冒烟通过为准：S019 R5 门开，7 个全数入 short_sector，故 `test_feature_interface.py` 三处计数断言从 29→36、subset 21→28。

**How to apply：**
- 全部走 `register_macro` 循环注册；`get_fred_api_key()` 读 `resolve_data_dir()/fred_api_key`，key 永不打印；`fetch_fred_series` 无 key→None、非 200/异常→None、proxy 优先 `$VR_HTTP_PROXY`。
- live 冒烟在 pytest 外运行（`conftest.py` import 期无条件覆盖 `VR_DATA_DIR` 为临时目录，pytest 内拿不到真实 key）。
- 4 个 `pytest -m "not live"` 失败判定为 **pre-existing 基线失败**，与本分支改动无关（相关文件 `git status` 未修改；隔离单跑 4/4 仍失败）：
  1. `test_newsradar_global_intel.py::test_fetch_radar_has_global_intel_track`：`news_sources.json` 于 commit `185c9e4`（S001 时期）删除，测试陈旧。
  2-4. `test_s003_fixes.py` 三个 mootdx 用例：monkeypatch `astock._mootdx_client` 抛 ValueError 未打通，端点返回 600519 真实数据（疑模块级 import 时已实例化 client）。

**被否决的方案：**
1. **live 冒烟纳入 pytest**：`conftest.py` 强制临时 `VR_DATA_DIR`，pytest 内无真实 key；改 conftest 影响全仓。否决，冒烟留独立脚本。
2. **USDCNH 直接采用**：FRED 无现货源，改用 DEXCHUS。
3. **阻塞修 pre-existing 失败再合并**：4 个失败与本 spec 无因果关系，基线已红；修它属 S003/新闻雷达职责范围。否决，仅记录，随各自 spec 修复。

**日期：** 2026-07-31

**状态：** 已采纳（T15 实现完成，T12/T13 集成验证通过：`pytest -m "not live"` 全量 718 passed / 12 deselected）

---

## DEC-003：短线胜率优化 grill 会话 D1-D7 裁决记录（WR-Workflow）

**选择：** 2026-08-11 grill-me 会话，D1-D7 全部裁决通过，落地 `docs/workflows/short-term-win-rate-optimization-workflow.md`（v1.1）。要点：
- D1 weather 相位升级为漏斗硬闸门：同意；先跑"相位×次日收益"证据脚本定闸门强度，不拍脑袋直接硬闸
- D2a 区分 `no_history`/`data_missing` 两类零分因子，不做一刀切完整度闸门：同意（一刀切误杀首板战法目标群）；D2b `data_missing` 行暂留列表标记展示，观察期后收敛
- D3a 战法回测补 date/code/name 归因；D3b 分层口径 weather 四态（与 D1 同口径）；D3c 止损/止盈参数校准缓做，每战法×weather 格 n≥30 时通知
- D4a 展示层改"校准次日红盘概率+样本量 n"，gene_score 降为内部排序字段；D4b 校准表挂 S041 定时回测滚动重算；D4c n<30 分桶并入相邻档标定
- D5a 纪律执行率指标（结算回放 vs 战法理论出场偏离归因）；D5b half-Kelly 仓位建议接 S042 统一持仓建议引擎；D5c 排 P2（winrate_records ≥30 笔启用）
- D6a ML 栈冻结至 W2-W4 落地+归因样本达标；D6b walk-forward 协议+"必须跑赢 S047 分桶基线"为未来模型工作硬门槛
- D7a 三 edge 族架构（动量溢价/事件溢价/均值回归），并行管道独立打分；D7b value_funnel 增"波段回归"变体（20-60 日持有期）；D7c 结算记录加 edge 族/持有期目标字段；D7d 试错协议四条（影子先行/t≥2 门槛/小仓 kill 线/明日验证条件）

**Why：**
- 优化目标是期望值不是胜率；项目自有证据（S047，n=5267）显示候选池已有正 edge（+2.17%/61.3%），免费胜率来自"不做坏日子/不选坏票/不做坏出场"，不是找更好的股票
- 外部证据：ashare-sop-engine 回测（6839 只/119 交易日）报告加 L1 宏观闸门后 D5 超额 +0.02%→+0.53%；vibe-astock 派生情绪指标体系（赚钱效应用中位数/晋级率 1进2 最敏感/梯队断层）作指标定义参照
- 用户自诊"短线凭感觉做"→ 新增 W0 行为闭环（交易票根+影子对照）先于一切新能力，先把感觉变成可对账数据

**How to apply：**
- 路线图见工作流文档 v1.1：W0 行为闭环 → W1 证据层 → W2 闸门 → W3 归因 → W4 展示 → W5 反馈 → W6 治理；各阶段独立拆 medium spec，S049 合并后启动
- 外部工具只借范式不引平台：qlib Rolling 重训范式 / vectorbt 扫参（D3c 时）/ quantstats tear sheet（W5）/ sklearn IsotonicRegression（W4，requirements 已有）；自动交易（easytrader/QMT）明确不引
- 合规：所有胜率/概率展示挂「历史统计特征」；闸门是系统行为不是方向建议；missing 按 AC6 口径标注

**被否决的方案：**
1. **因子完整度一刀切闸门**（完整度 <3/5 排除）：误杀 no_history 首板目标群，改分类处置（D2a）。
2. **拍脑袋直接硬闸门**（D1）：无相位×收益证据、误杀成本不可量化，改证据先行。
3. **动量+回归两管道并行上线**：都无法验证，改串行（W0 → 动量影子 → 回归影子）。
4. **引入 qlib/vectorbt 平台依赖**：重且与本地数据层重叠，只借范式；vectorbt 在 D3c 扫参时再引入。

**日期：** 2026-08-11

**状态：** 已采纳（工作流文档 v1.0 已落地，D7 与 v1.1 修订见文档 §10-§11）

---

## DEC-004：D8 盯盘教练、降级策略与方向建议口径（WR-Workflow v1.2）

**选择：** D8a 立 W-C 盯盘教练阶段（排期 W0→W-C→W1，MVP 时刻表+条件状态+教学点+降级选择，推送二期）；D8b 方向建议口径由用户推翻原建议（原"只报条件状态不给方向"）——核对 CLAUDE.md §1.1 弱合规与 chat.SYSTEM_PROMPT 后确认推翻成立，定稿为"有据才给"六条（数据+规则背书/n+t 值/多空两面+证伪条件/三情景测算禁确定性承诺/轻量风险提醒/个股按五维框架）；D8c 教学模式默认开；D8d 降级阶梯 A/B/C，C 档四条铁律（禁开新仓/止损前置条件单/到期持仓置顶/收盘汇总），`attention_mode` 进结算归因。

**Why：**
- 用户自报"不会盯盘"——动量侧设计（竞价确认/回封确认/止损执行）无可执行载体，须把高价值时刻表内置为教练；
- 无降级策略则缺席日交易完整性断裂，漏止损是最大尾部风险；完整性定义=每个持仓有出场路径、每个信号有状态；
- 产品目标升级为教练（教投研技巧、脱离助手也能决策）：方向建议例题化+独立性指标+毕业轨迹；
- "零方向结论词"经核对非本项目合规要求（过度从严误读），CLAUDE.md §1.1（2026-07-30）明确私人投研助理可给研判/推荐/买卖时机，工程底线（可复现/不臆造、私有数据隔离、em_get 防封）保留。

**How to apply：**
- 工作流文档 §12（v1.2）：W-C 阶段定义、时刻表种子、降级阶梯、方向建议口径、教学目标、里程碑修订（W1 双影子轨补事件溢价、W2 补指数中期趋势态、W5 补同题材集中度上限）；
- W-C 复用 trading_workflow（时段分阶段）/auction_screener/bomb_alert_system/STRATEGY_REGISTRY；新代码一律按弱合规口径；limitup_strategy.py 遗留"教育性展示"措辞随后续迭代清理，不属本工作流范围；
- 下单动作永远由用户在券商完成（C 档条件单亦然），系统不接交易。

**被否决的方案：**
1. **"零方向词"硬约束**：与 CLAUDE.md §1.1 弱合规定位不符，用户推翻，改"有据才给"。
2. **缺席日接自动交易代盯**：合规与定位红线；C 档以券商条件单前置解决出场完整性。
3. **W-C 排到 W1 之后**：用户不会盯盘则影子对照实盘侧全是感觉单、数据质量差，改 W0 后立刻做。

**日期：** 2026-08-11

**状态：** 已采纳（工作流文档 v1.2 已落地，§12）
