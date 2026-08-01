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
