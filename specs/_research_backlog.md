# 调研定论追踪表（Research Backlog）

> 所有"跑过调研 workflow 有定论、但没落地实现"的清单。每周头脑风暴过一遍推进。
> 防止调研结论飘在对话里丢失（流程缺口：调研→定论→但没"定论转 spec"那步）。

## 流程要求（SDD §0 补强）
调研 workflow 跑完有定论的 → **立刻**落 spec 草案（哪怕只问题/目标 + 定论摘要）+ 进本表 + MILESTONES，不留在对话里。spec→plan→tasks→实现闭环不断在"定论→spec"这步。

---

## 待落地（有定论，未 spec/未实现）

| 编号 | 调研 | 定论 | 状态 | 下一步 |
|---|---|---|---|---|
| S192 | 实盘交易通道评估（QMT/miniQMT + 替代） | 当前不开户（breakout net-1.14%/T+0 无 edge/选股证否）；先用同花顺 SuperMind 免费回测验证；有 edge 后国金 10 万开户 + miniQMT + Windows 网关 + xqshare 代理 | ✅ spec 落定论 + memory | 第一步：SuperMind 回测验证策略（当前）；第二步：有 edge 后启动开户+对接 |
| S193 | 缺口理论集成 | 缺口作 regime/变盘判断信号（不直接触发买卖，grill Q10-Q11 定）；classify_gap 纯函数 + chat.TOOLS 注入 AI 研判 + 关注推送 + 候选池注入；不验单信号 §44，验 S194 融合消融 | ✅ spec 草案落 | Phase 2：纯函数 + chat.TOOLS + 分类准确率 sanity |
| S194 | 信号融合基线 | 方法论修正（单信号§44不过≠融合无edge，Q13-Q14 grill）；few-shot检索+贝叶斯权重融合；F1消融验增量+F3融合整体§44；先 few-shot 后期数据够上 ML | ✅ spec 草案落 | Phase 3：信号对齐+few-shot引擎+贝叶斯权重+消融验证（依赖 S193） |
| S195 | 缺口理论入知识图谱 | 缺口四类+regime映射+判定规则入 Obsidian 投研图谱（认知层先于代码） | ✅ spec 草案落 | Phase 1：纯文档图谱实体（最快） |
| S196 | 技术分析信号源扩展（MACD背离+RSI超买超卖） | P0双子作regime信号不买卖+强互补缺口+数据够(baostock日K)+A股有据；岛形反转进S193扩展不独立 | ✅ 调研落 memory | S193 之后候选：classify_macd_divergence/classify_rsi 进 chat.TOOLS（类比 classify_gap） |
| RB-1 | scheduler-research（换框架/服务解耦） | **保持自实现+补强**（进程死非框架问题→healthchecks.io 解；Redis 对个人 Mac 过重 YAGNI；APScheduler 唯一增量 misfire 不痛；3 痛点自建~150 行零依赖） | ✅ S190 spec 落定论 + R3-R5 全落地 | R3 healthcheck seed ✅/R4 retry 接线 ✅/R5 depends_on ✅ 全 done |
| RB-2 | cloud-resources healthchecks.io | 免费外部心跳防 cron 静默死 | ✅ 全落地（executor+seed cron id=32 `0 * * * *` + URL 写 backend/.env + 后端重启 + ping 200 OK 验证） | done；hourly cron 自动 ping，进程死→healthchecks.io 邮件告警 |
| RB-3 | data-infrastructure 全量拉取 | 每日盘后全量拉各源当日数据（stoke 研报/新闻/归因 + mootdx 分笔）沉淀 datalake + 回放引擎 | ✅ 已实现（`data/datalake/replay.py` 75行 + `daily_full_pull` executor 拉 stoke+ticks + cron id=34） | datalake 已有 9-12 stoke 数据；回放引擎可调 `replay_day(date, codes)` |
| RB-4 | w8e2forp7 任务级重试接线 | tenacity network_retry 装饰器零调用方→接线 tencent | ✅ tencent _fetch_gtimg 接 @network_retry（commit c0b89ce） | baostock fetch_* except Exception 吞异常接不上（价值有限），tencent 首个接通 |
| RB-5 | 盘后链依赖门控 | depends_on + 门控治静默陈旧数据 | ✅ 完全收尾（字段+迁移+_should_run 门控+dependency_satisfied+seed 声明） | kline_refresh(根)→funnel→journal 硬门控，cron 时序+门控双保险 |
| RB-6 | gap 250 天跨 regime 复验 | 172 天 net≈0 全 regime 负，250 增量价值小 | ✅ 172 够主线结论 | 250 不值得全量重拉（refresh 增量不回溯历史） |
| RB-7 | breakout 1.72x 标记清理 | 6 处已改 naive 1.36x | ✅ 已清理（残留是诚实注释非误用） | done |
| RB-8 | r3-enforce 接线 | 等 forward_test 到 30 天（~9-25）触发评估 | ⏳ 等 30 天 | forward_test 监控 endpoint 已落（S188 P0 #3），到 30 天评估 |
| RB-9 | 每周全局优化头脑风暴 cron 触发器 | 每周一次自动触发 | ✅ executor+seed cron 周一9:00 飞书+待办（commit fc836e0） | backend 跑不了 workflow，用户手动触发 |
| RB-10a | daily_full_pull news 源容错（cls_telegraph 404 不炸） | akshare stock_info_global_cls 接口 404 废弃（重试10次515s）；修 180s+2retry+容错（commit aa605dd）让 cls_telegraph 返空list 不阻塞 daily_full_pull | ✅ 容错 done | 不再炸，news 表仍空（接口404） |
| RB-10b | daily_full_pull news 源换源 | akshare 财联社电报接口 404 废弃，换数据源（同花顺电报/东财快讯/stoke 替代接口）或等 akshare 修 | ✅ done（7515391）| cls_telegraph 换东财快讯 stock_info_global_em（200 条），归一化列名匹配原 shape，news 表不再空 |
| RB-11 | daily_full_pull ticks raw 沉淀修复 | mootdx_tick_ofi_proxy 只输聚合 n_ticks 不输 raw ticks，save_ticks 从未被调→ticks_YYYYMM.db 从不存在 | ✅ done（701059a，backlog 之前 stale）| proxy 加 --save-datalake 模式（fetch_tick_ofi return_raw=True + save_ticks 落 datalake）+ daily_full_pull subprocess 调 --save-datalake；ticks_202609.db 实测 4181 ticks |
| FE-1 | risk 风险看板路由挂载 | RiskDashboard.tsx 组件已写但 router.tsx 无 /risk 路由（S179 清理漏挂） | ✅ done（033a7b7）| router.tsx 加 /risk + navigation 加'风险看板'tab |
| FE-2 | S193/S196 chat.TOOLS 接线 | classify_gap + ta_signals(MACD/RSI) 已实现但没进 chat.TOOLS（AI 研判查不了缺口/MACD/RSI regime） | ✅ done（110e543）| ai/tools/ta_tools.py 3 工具 @register_tool（query_gap_regime/query_macd_divergence/query_rsi），自动同步 chat.TOOLS+MCP，TOOLS 16→19 |
| FE-3 | chat 网页对话入口 | /api/chat 后端有但前端无 chat 页（当前走飞书 bot） | ⏳ 待建 | 前端加 ChatPage（不依赖飞书也能对话） |
| FE-4 | bidding 集合竞价监控页 | bidding router（/api/auction/monitor+watchlist）有，前端无独立页 | ⏳ 待建 | 前端加 BiddingPage（盘前竞价监控） |
| FE-5 | topology 拓扑图独立页 | topology router + GraphView 组件有，无独立页路由 | ✅ done（e1cbceb）| router.tsx 加 /topology → Topology 页（named export，date? 可选）+ nav'拓扑图'tab |
| FE-6 | S194 fusion_layer 前端 | 辅助层未实现（按升级路径前向测试） | ⏳ 待实现 | S194 实现后接 chat SYSTEM_PROMPT + 前端融合研判展示 |

## 已落地（参考）

| 调研 | 落地 | commit/spec |
|---|---|---|
| 涨停首板 60 日回补多源调研 | baostock/ths/hithink fallback | `data-source-capabilities` memory + 多处 |
| 世纪大辩论 w2j5srlf 10 视角 | S159-S166 部分（S162/163/164 done） | spec |
| w8e2forp7 retry 装饰器 | `scheduler/retry.py` | 2282503（但零调用方见 RB-4） |
| S185 turso 数据湖 | `turso_sync.py` sync 4 表 | d2b25f4 |
| S184 kline_refresh 性能 | 数据就绪预检 + cron 17:15 | 91fd5fd |

## 弃置（有定论不做）

| 调研 | 定论 | 原因 |
|---|---|---|
| r3-enforce + ash-mcp B 臂 | 搁置 | 用户 2026-09-10 决策（`deferred-specs-shelved` memory） |
