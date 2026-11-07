# Changelog

本项目的版本号唯一来源是 `frontend/package.json`；后端 HTTP API、`/api/health`、
前端界面与 MCP `serverInfo` 全部从它读取（见 `backend/version.py`）。

## v0.6 — 2026-11

combo_5d edge 实盘定标 + 通知降噪 + 交易日历治理。15 commits。

### 新功能
- combo_5d edge real-exec 钉死：去 gap 版 net +0.336%，存活但薄，加 regime + walk-forward + 60 天滚动模拟历史实锤
- combo T+1 买点优化：T+1 close net +0.389% > T+1 open（+0.052% 提升）
- combo edge backtest-guard 验证：NW + T+1 过滤 + 滑点敏感性 + R51 潜伏 edge
- combo_daily_notify 接线 + audit 归档 + commander 去投毒
- combo_notify 输出 per-pick 1%ADV 建议仓位（容量定标）
- 通知轰炸审查 P0+P1+P2：炸板止血 + 砍 6 类噪音 + 降噪门

### 修复
- P0 修 combo 前向验证管道 5 bug 链（token ROI 审查发现）
- inst compute_stop_intraday/nostop 停牌过滤（orderbook-sanity 高危）——停牌冻结价当真实买卖点虚增 inst 回测
- feishu 推送加健康告警——send_feishu 成功/失败都 ping VR_HEALTHCHECKS_URL
- 交易日历去硬编码——akshare 自动刷新 + holidays.json 缓存 + fallback 三层兜底
- 补 2027 节假日降级 set

---

## v0.5 — 2026-10

RSI 择时策略全量验证 + A 组 edge 闭环 + 飞书推送进化。174 commits。

### 新功能
- RSI 择时策略（最强统计显著 alpha，p=0.0001 mean+6.24% WR93%）：4 指数全覆盖，v3 最优 +30% 止盈 +20 天退出 夏普 1.90 收益 +64.66%
- RSI+MACD 金叉组合信号：mean+9.53% WR100% p=0.0000，当前 RSI 触发但 MACD 死叉等待确认
- RSI 择时 API 端点 /api/strategy/rsi-timing/signal + /api/strategy/rsi-macd/signal
- RSI 择时自动监控脚本 + 定时任务（每日 08:25 盘前推送 + 9:35/14:00 盘中）
- RSI 策略实盘前向验证脚本——自动记录触发 + 60 天后结算（每日 18:05）
- RSI 策略完整执行脚本——信号检测到操作建议一条龙 + 上证 50ETF 买入计算
- 持仓 + RSI 联动监控脚本——自动检查止损/减仓/清仓/RSI 信号
- MACD 金叉自动监控脚本——预估金叉触发 + 三因子全部信号
- 2026 年唯一统计显著 alpha——小成交额错杀低吸策略（lvd）
- 策略 4 进化版引擎 v10——多专家共识尾盘错杀系统 + v10.3 scan 异步财务过滤 + v10.4 intraday 采集池扩大
- tail_dip v10.5 filtered 模式集成 tail_dip_engine 完整财务红线
- commander v10.5 filtered 模式集成
- combo-5d-edge 战法接线 + 60 天跟踪管道 + daily 自动化
- combo_5d 去涨停版确认 +0.62% alpha t6.85 真 edge
- 打板工作流闭环——5 Stage watchlist→二次确认→买→-3% stop→归因
- 反量化短线战法 Phase A——tactics 包 7 模块 + 99 tests
- 两个 edge-confirmed 接生产 + A 组 T+10 8 步全 PASS
- §44 固化 grill 方法论到 A 组脚本 + 长假节前 A 组严测 edge-confirmed-provisional
- §44 核实红利低波 512890 beta（工程底线 #2 闭合）
- §44 幽灵政策 R35-R40 落地（verifier gate + 模板自查）
- A 股 regime 监控——combo-5d-edge 何时可启信号
- 提交 96 个研究/基建脚本 + feishu 推送基建 + 策略 4 回测报告

### 修复
- §44 A 组 grill 后诚实降级 edge-confirmed-provisional → exploratory
- §44 A 组 T+10 / inst_dominant stop 口径修正（工程底线 #1：T+1 close→T+2 open 成交）
- baostock ensure_login liveness probe——长跑 session 过期 + 假熔断解除（reset + HALF_OPEN 直连验证）
- commander 920 北交所跳过扩展到 filtered 模式 + A 组飞书卡片诚实化
- lvd ST/退市股过滤——603272 *ST 联翔被选中暴露盲区
- rsi-timing 退出策略从 60 天改为固定 20 天（回测最优 +52.04% 回撤 -9.2%）
- s232 t1_gap_analysis 改 close_ev 诚实口径——戳破 open_ev 日内泄漏假 edge
- §44 v3 加 R6 成成交假设虚构根因 + S233 exit 假 edge 诚实修正
- tail-dip 减持误报致命 bug——stock_share_change_cninfo 返回全部股本变动非减持，93 只候选全被误杀
- scheduler kline_refresh timeout 2400→10800 + reaper 2500→11000

---

## v0.4 — 2026-09

§44v2 统计验证体系 + 模拟盘自洽闭环 + 信号融合 + 多臂推荐 + 前端 IA 重构 + 飞书 bot。688 commits。

### 新功能
- §44v2 统计验证体系：day-clustered event t-test + permutation + Bonferroni + walk_forward + days_robust<60 cap，首个 validated edge（breakout+volatility 破 2x）
- §44v2 R3 30/60 天写回闭环 + override-aware reader（verdict 升降级自动化）
- 缺口理论集成（S193）：classify_gap 四类缺口分类纯函数 + 11 测试
- 信号融合层（S194）：signal_align 对齐 + bayesian_signal_weight FS2 + fusion_layer AI 研判 + ablation_runner 消融 + F3 融合整体 §44 event edge
- S198 衰竭条件翻转：5 项 gate 全 PASS，翻衰竭 label 反转→动能延续
- S199 方向感知 gap regime 编码 + S194 ablation 重跑
- S201 cost 口径统一：accounting 逐笔 _cost_pct 保留 5 元门 + gap 前视修复 candidate 语义
- S202 get_kline 统一接口 + IC/IR 评价层（Spearman + Newey-West HAC）+ 行业中性化
- 龙头战法 3 战法 + Dragon Score registry + regime-stratified harness（S203）
- §44v2 verifier 双算 + event_drift drift-fix + family_grouping 去重（S204）
- 5 战法 per-战法维度集 + 7 维度 compute + 5 §44 harness（S205）
- 流程管线页 N8N 风格节点图（React Flow + dagre，9 主节点 + 34 task 子节点）
- 模拟盘自洽闭环（S175）：scheduler 接线 + 多臂推荐 + PaperPortfolio + follow-order 4 源 gap
- PaperPortfolio.bayesian_arm_size Beta-Bernoulli 后验驱动 arm_size
- Trade Journal 闭环（S173）：跨臂胜率全链路 orchestrator + 统计方法论 + drawdown 熔断
- 模拟盘累积胜率曲线——实时聚合 + Wilson 95% CI + 50% 随机基准
- consecutive_relay arm 通电生产 + 315 天满窗口 verdict +1.5677%（后证否为 D 涨停封板溢价非连板接力 edge）
- arm 级 kill switch 框架（plumbing）——arm_status 表 + lift_for_arm 读 override
- 财报季排雷 ReportSeasonCircuitBreaker（M5/S225）
- 图谱注入流（M7/S226）：公告→DeepSeek JSON→inbox/ 待审 + /graph 审核界面
- 盘中 conditioning 数据收集器（OFI 五档 + 封单诚意补全）
- OFI 盘中数据只读看板（read-only 非信号）
- 命令面板 CommandPalette（Cmd+K）+ SplitLayout + VerdictRenderer
- trade-desk cockpit：/screener + /stock/:code cockpit + /market 新页
- 项目架构图 standalone HTML（715KB inline SVG，五层 backend + 认知层 + 监控推送闭环）
- 宏观面板 MacroPanel——FRED 8 因子（加 VIXCLS 美股 VIX）+ FOMC 前后端闭环
- 国内流动性第 4 因素（DR007 + QVIX）+ 判定合并入口
- 盘前暴风雨预测模型（独立于事后 STI 检测）+ storm-daemon 定时存外围 + 新闻快照
- 飞书 WebSocket 长连接模式 + 双向对话 + KG 工具 + SSL 修复 + 流式卡片
- 飞书 bot KG 增强 SYSTEM_PROMPT + 上下文注入 + 快捷命令
- 微信 bot 双向对话 + KG 直查降级
- 选股页加自选按钮（AddToWatchlistButton + 3 页接入）
- 价格预警 executor——5 标的支撑/压力位 + 触及飞书推送 + AI 研判 fusion
- watchlist 缺口变盘飞书推送 executor（突破 cluster-robust survive Bonferroni）
- 通用技术指标评分 6 维（MA/MACD/RSI/量能/乖离/支撑）+ chat.TOOLS + router endpoint
- 定时任务页加"重跑今日选股"按钮——盘后 gate + 触发选股两 task
- turso_sync executor + seed cron（VR_TURSO_URL 未设纯本地降级，零侵入）
- daily_full_pull mootdx 分笔 subprocess 接线 + PE-PB + /api/valuation/market endpoint
- healthchecks.io 外部心跳防 cron 静默死
- weekly_brainstorm_remind cron（周一 9:00 飞书 + 待办）
- tenacity network_retry 装饰器（scheduler/retry.py）
- depends_on 依赖门控——盘后链防下游吃陈旧数据
- datalake 本地回放层 + daily_full_pull executor
- tencent _parse_gtimg 提取五档买卖盘（latent 免费优化）
- IC/IR Alphalens 因子筛选层互补 §44v2 策略验证层
- 打板纪律门禁工作流闭环（s231）——风控工具非 edge 基建
- T+1 涨停预测 watchlist 生成器（观察池非买入信号）+ T+1 hit 回填 cron
- 知识图谱建设批次——LLM 抽取 / 数据同步 / 图分析 / Obsidian-MCP 工具入库

### 修复
- kline 数据源稳定性：baostock 单源（彻底解决 baidu 403 + mootdx log）+ kline_resolver 多源 fallback（baostock→东财→hithink→cache）
- kline_refresh 超时 1200→2400s + reaper 1300→2500（修 5219 全 A 串行 fetch 超时致 cache 停）
- baostock_src 加限流 + 熔断防 IP 封禁
- candidate_funnel cron 17:15→17:25（晚 kline_refresh +10min 避免并发读 stale cache）
- 跨周末 0 picks bug 批修（scan_consecutive_relay / scan_pre_limitup / early_admission / bidding_monitor 用 prev_trading_date）
- §44 gap run 接 accounting.gap_net_return 真成本 → gap FALSIFIED
- §44 wire_verdict + verify 加月度参数透传，修 walk_forward OOS 月度失效
- §44 BH 单 p no-op bug + event drift fix 接线
- S201b 承重对抗审 7 CRITICAL——推翻 unfalsify premise（flat-vs-per-trade category error，佣金门是结构性杀手）
- baostock kline cache 482MB JSON 全量 load 2.19GB 常驻 × 7 处 → SQLite per-code 查 ~0 常驻
- sector_cycle aggregate_sectors N+1 → 批量 GROUP BY + 资源泄漏 try/finally
- forward_test INSERT-in-loop → executemany
- H7 批量修 46 处冷路径 + 15 处热路径静默吞错（加 logger.warning，保留降级 return）
- 飞书 bot 回复走 BOT app App Bot + LLM 主备 failover
- watchlist 自选股迁 backend DB 跨设备同步——修 LAN 设备看不到 mac 加的自选
- nav IA matchPrefix /stock/ /sectors/ 去尾/ 修详情页匹配失效 + ErrorBoundary 重试
- DB 统一到 .vibe-research/（scheduler db.py + notes_repo + workflow_state_repo + routers.common）
- 漏斗"今日没数据"——today 默认改 last_trading_date_str（7 处）
- r3_enforce event-edge 守卫——防 consecutive_relay lift=None→×1.0 静默升满仓
- S218 v2 #6 realizability-bias 修——D+1 一字跌停封死找限跌打开日 open 重算

### 重构
- S174 god-module 拆分：scheduled_tasks.py (3076 行) → scheduler/ 包 (17 文件) + first_board_filter.py (1702) → first_board/ 包 + strategy_funnel_registry.py (940) → funnel/ 包，均带 re-export shim
- S179 Workflow 容器解散——3 views 独立路由 + redirect /workflow→/review（-725 行）
- S179 FirstBoardPipeline 拆分——CandidateScoreTable + styles 抽独立模块（1126→719 <800 合规）
- S186 Phase 3 删 3 死组件（SectorDivergence/Sectors/StrategySignals）
- S194 R5 v2 ablation_runner 重设计为融合分消融
- 做减法：归档 57 已实现 spec → specs/_archive/ + triage 51 active → 31 archive + 12 abandon + 9 keep
- 删 16 dead 前端组件 + win_rate 孤儿组件树 + 5 孤儿死页 + 11 dead endpoint

---

## v0.3.1 — 2026-08-09

三个用户报告的 bug + 版本号治理。感谢 [@lihaoran0412](https://github.com/lihaoran0412)
一口气提了三份带根因和文件行号的报告，质量很高。

### 修复：`query_market scope=turnover` 字段全为 null（#28）

`tools.py` 按 `turnover` / `changePct` 取字段，而 `astock.market_turnover_rank()`
实际返回的是 `price` / `pct` / `amount` / `mcap` / `float_cap` / `industry`——键名对不上，
每条只剩 `name` 和 `code`，其余一片空白。已对齐字段名，实测 20 条全部有值。

### 修复：Windows 下 MCP server stdout GBK 编码崩溃（#27）

Windows 上 Python 的 stdio 默认编码是 GBK(cp936)。JSON-RPC 响应里带中文、RSS 正文里的
`\xa0`（不换行空格）等字符 GBK 编不出来，**整条响应写不出去**——客户端表现为工具调用
失败 + 反复重连；即便不崩，中文也会被按 UTF-8 解 GBK 字节，全是乱码。

`mcp_server.main()` 现在在读写任何协议内容之前把 stdio 钉死成 UTF-8。选择重配而不是
退让成 `ensure_ascii=True`：后者能防崩，但会把中文全变成转义序列、体积翻几倍，而 MCP
协议本身就要求 UTF-8。

### 改进：证券搜索加备用端点，并区分「接口不可用」与「查无此票」（#26）

报告者的环境下美股/港股/韩股查询全部失败，而产品只回一句「未找到对应代码」，
他只能自己逆向排查到底哪一步坏了。

⚠️ **该接口从我们这边实测是正常的**（AAPL / 00700 / TSLA 均能解析），所以更可能是
IP 风控或链路问题，而非接口下线。但暴露出的两个真问题已修：

- **`except Exception: return None` 把两种情况压成一个返回值**——"这只票不存在"和
  "接口请求失败"从此不可区分。现在后者抛 `SearchUnavailable`，带上真实的底层错误，
  并明说「这与查无此代码是两回事」。
- **单一端点故障会让整块功能瘫痪**——新增备用端点 `searchadapter.eastmoney.com`，
  主端点失败自动切换。**并且必须校验响应结构再收手**：主端点返回「合法 JSON 但没有
  `QuotationCodeTable`」（接口改版 / 风控页 / HTTP 错误页，`em_get` 不做
  `raise_for_status`）时会被误当成"查得到但没匹配"，备用端点根本轮不上——而这恰恰
  就是本 issue 描述的情形，不校验的话这次修复等于没修。

### 修复：MCP `serverInfo` 版本号仍写死 `0.2.2`（#20 补漏）

#20 只列了 3 处硬编码，照着改会漏掉第 4 处：MCP 客户端初始化拿到的还是旧版本。
现抽出 `backend/version.py` 作为唯一读取点，四处同源。

**刻意独立成模块而不是从 `app` 导入**：`app.py` 在导入时会 `pf.start_scheduler(1800)`
起后台线程，MCP 服务只想拿个版本号，不该承担那个副作用。读取失败的警告走 **stderr**——
MCP 的 stdout 专供 JSON-RPC，往那儿打一行警告会插在初始化响应之前，客户端可能拒收整条流。

### 测试

`backend/` 90 passed（新增 11 例），含三条反向边界：GBK stdout 下不修就必崩（先证明坑
真实存在）、接口正常但查无此票仍返回 None、读不到版本号时 stdout 必须为空。

---

## v0.3.0 及更早

本文件自 v0.3.1 起维护；更早的版本历史见
[Releases](https://github.com/simonlin1212/Vibe-Research/releases)。
