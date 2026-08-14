# specs/ — 规范驱动开发（SDD）

> 任何非平凡改动**先写规范、后写代码**。流程见项目根 `CLAUDE.md` §0。
> 这里只放正式 SDD spec；上游自由格式的 PRD/设计文档在 `../docs/`（见其 README）。

## 目录结构

每个 spec 一个子目录，命名 `SNNN-短标题/`：

```
specs/
├── README.md            # 本索引
├── _template.md         # spec 起草模板
└── SNNN-短标题/
    ├── spec.md          # 规范正文（必有：问题/目标、需求、受影响文件、验收标准、合规自查）
    ├── plan.md          # 技术方案（可选；文件/函数级设计）
    ├── tasks.md         # 任务拆分（可选；原子 task + 依赖 + 验收方式）
    └── 验收报告.md      # 验收报告（实现后归档；逐条 AC + 合规自查 + 测试结果 + 修订记录）
```

- spec.md 必有；plan/tasks/验收报告 按规模取舍。
- 子目录内互相引用用同目录裸名（`spec.md`/`plan.md`/`tasks.md`/`验收报告.md`）；跨 spec 用相对路径（`../SNNN-短标题/spec.md`）。
- 正文里引用 spec 编号（如「S001」）作标识即可，路径以本索引为准。

## 状态

`草案` / `已通过` / `实现中` / `已实现(日期)` / `已废弃` — 实现完成后在 spec.md 顶部改状态并填日期；commit message 引用 spec 编号。

## 编号

`SNNN` 三位递增。下一个新 spec 用 S068。

## 已有规范

| 编号 | 标题 | 状态 | 子文档 | 一句话 |
|---|---|---|---|---|
| [S001](S001-fix-chat-env-llm-config/spec.md) | 修复 chat._get_env_llm_config 缺失 → /api/chat 500 | ✅已实现 2026-07-29 | spec | 补全环境变量兜底函数，打通问 AI |
| [S002](S002-打板工作流重构/spec.md) | 打板工作流重构 · P1 候选池诊断统一 | ✅P1 已实现 2026-07-28（live 闭环 07-29） | spec · [plan](S002-打板工作流重构/plan.md) · [tasks](S002-打板工作流重构/tasks.md) · [验收报告](S002-打板工作流重构/验收报告.md) | 短线候选池漏斗 + 诊断卡，六类指标口径统一 |
| [S003](S003-api-bugfix-batch/spec.md) | 后端 API 冒烟测试缺陷修复批次 | ✅已实现 2026-07-29 | spec · [tasks](S003-api-bugfix-batch/tasks.md) | API 缺陷批量修复（含 value_funnel 等） |
| [S004](S004-candidates-funnel-performance/spec.md) | 候选池漏斗 run_funnel 性能优化 | 🟡草案 2026-07-29 | spec · [plan](S004-candidates-funnel-performance/plan.md) · [tasks](S004-candidates-funnel-performance/tasks.md) | 缓存+预计算+top-N 限界+独立 source 并行 |
| [S005](S005-中长线价值选股漏斗/spec.md) | 中长线价值选股漏斗（与短线 S002 并列） | ✅已实现 2026-07-29 | spec · [plan](S005-中长线价值选股漏斗/plan.md) · [tasks](S005-中长线价值选股漏斗/tasks.md) · [验收报告](S005-中长线价值选股漏斗/验收报告.md) | 价值四层漏斗 + 去劣 7 条 |
| [S006](S006-系统重写纲领/spec.md) | 系统重写纲领（渐进式长分支） | 🟡草案 2026-07-29 | spec | 数据契约统一+调度收口+前端 UI 重设计+测试网，分 S006b–S014 子 spec |
| [S007](S007-契约层/spec.md) | 契约层（数据模型+回归基线+契约测试骨架） | ✅已实现 2026-08-01 | spec · [plan](S007-契约层/plan.md) · [tasks](S007-契约层/tasks.md) | Pydantic v2 7 模型 + 10 只 code 基线夹具 + 前后端契约骨架，不动 astock |
| [S008](S008-后端数据层迁移/spec.md) | 后端数据层迁移（astock/gstock/market→模型） | ✅已实现 2026-07-31 | spec · [plan](S008-后端数据层迁移/plan.md) · [plan-stage1](S008-后端数据层迁移/plan-stage1.md) · [tasks](S008-后端数据层迁移/tasks.md) · [验收报告](S008-后端数据层迁移/验收报告.md) | 返模型+response_model+T13 全批次迁 C 组 engines（11 新 S007 模型）+删 data_provider |
| [S009](S009-前后端类型同步/spec.md) | 前后端类型同步（openapi-codegen） | ✅phase 1 已实现 2026-07-31（phase 2 移交 S013） | spec · [plan](S009-前后端类型同步/plan.md) · [tasks](S009-前后端类型同步/tasks.md) | dump_openapi.py+openapi-typescript+types.ts 就位；phase 2 非机械（手写严格/生成宽松级联+T13 有损），移交 S013 协同 |
| [S010](S010-工具注册表与SYSTEM_PROMPT/spec.md) | AI 工具注册表 + SYSTEM_PROMPT 新边界 | ✅已实现 2026-08-01 | spec · [plan](S010-工具注册表与SYSTEM_PROMPT/plan.md) · [tasks](S010-工具注册表与SYSTEM_PROMPT/tasks.md) | registry 声明式+chat/mcp/cli 解耦+SYSTEM_PROMPT 按新边界放宽 |
| [S011](S011-调度收口/spec.md) | 调度收口（删 scheduler.py+重写 scheduled_tasks+状态机接线） | ✅已实现 2026-08-01 | spec · [plan](S011-调度收口/plan.md) · [tasks](S011-调度收口/tasks.md) | 扩展 cron+ lifespan+WAL+去重+状态机落库（不引 APScheduler） |
| [S012](S012-工作流标灰/spec.md) | 工作流标灰（realtime/post 桩+pre 清理） | 🟡草案 2026-07-29 | spec · [plan](S012-工作流标灰/plan.md) · [tasks](S012-工作流标灰/tasks.md) | 桩→NotImplementedError+UI 标灰，不补功能 |
| [S013](S013-前端数据层/spec.md) | 前端数据层（统一 client+TanStack Query+懒加载+apiKey 代理） | ✅已实现 2026-08-01（T6 可选余项） | spec · [plan](S013-前端数据层/plan.md) · [tasks](S013-前端数据层/tasks.md) | client 统一(T1-T5)+router 懒加载(T10)+QueryProvider(T7,T11)+pctColor/主题(T14,T15)+59 hooks(T8)+17 页接线(T9，含轮询/交易时段门控)+hook 类型收紧+vitest(T16)+T12/T13 决议保留双配置；仅 T6 按域拆 api.ts 可选未做 |
| [S014](S014-前端UI重设计/spec.md) | 前端 UI 重设计（信息架构+交互统一+视觉+AI 对话） | ✅已实现 2026-08-02 | spec · [plan](S014-前端UI重设计/plan.md) · [tasks](S014-前端UI重设计/tasks.md) · [RECOVERY](S014-前端UI重设计/RECOVERY.md) | 22项→5组+首页下沉+巨型page拆分+三态统一+移动端+echarts 跟主题 |
| [S015](S015-配置与基础设施/spec.md) | 配置与基础设施（config 拆分+infra 收口+路由自动发现） | ✅已实现 2026-08-01 | spec · [plan](S015-配置与基础设施/plan.md) · [tasks](S015-配置与基础设施/tasks.md) | 收口 4+套缓存/限流/熔断+修 cache_response key+metrics 配置化 |
| [S016](S016-测试网/spec.md) | 测试网（后端覆盖率+IO 录制回放+前端 vitest+CI） | 🟡草案 2026-07-29 | spec · [plan](S016-测试网/plan.md) · [tasks](S016-测试网/tasks.md) | 纯函数 ≥80%+IO 录制回放+前端快照+CI 门槛 |
| [S017](S017-A股涨跌预测模型栈/spec.md) | A股涨跌预测模型栈（四头解耦） | ✅已实现 2026-08-01 | spec · [plan](S017-A股涨跌预测模型栈/plan.md) · [tasks](S017-A股涨跌预测模型栈/tasks.md) | 短线×板块起步，LGB+CatBoost+HMM+Conformal，输出概率+分位区间 |
| [S018](S018-多源特征工程/spec.md) | 多源特征工程（预测模型特征供给） | ✅已实现 2026-08-01 | spec · [plan](S018-多源特征工程/plan.md) · [tasks](S018-多源特征工程/tasks.md) · [验收报告](S018-多源特征工程/验收报告.md) | 特征注册表+可得时间对齐表+北向分段+SHAP/Boruta 选 ≤25 特征 |
| [S019](S019-macro-Fred-API/spec.md) | 宏观特征 Fred API 接入（macro.py 第二批） | ✅已实现 2026-07-31 | spec · [plan](S019-macro-Fred-API/plan.md) · [tasks](S019-macro-Fred-API/tasks.md) | 美债10Y/DXY 走 Fred 独立通道+key 隔离 VR_DATA_DIR+补登 S2 |
| [S020](S020-worldmonitor决策因子接入/spec.md) | worldmonitor 决策因子接入（全球宏观/地缘/另类数据） | ✅已实现 2026-08-01（P0–P6；P7 live 冒烟待联网） | spec · [plan](S020-worldmonitor决策因子接入/plan.md) · [tasks](S020-worldmonitor决策因子接入/tasks.md) · [验收报告](../reports/acceptance/S020-2026-08-01-offline-pass.md) | 远程 MCP 互补另类数据层接 newsradar/market/特征栈，Fred 仍主源 |
| [S022](S022-熔断器health读路径修复/spec.md) | 熔断器 health 读路径修复（尊重 recovery_timeout） | ✅已实现 2026-08-02 | spec | peek_state 只读探测 + health 读路径自愈，修体检 🔴 circuit_breaker_open |
| [S023](S023-漏斗可用性与因子解耦/spec.md) | 漏斗可用性与因子解耦（P1 打磨：盘前简报接因子+候选详情依据链+漏斗每层可观测可调参+真实数据不静默返空） | ✅已实现 2026-08-04（`ed0a0fe`，含 S026 异步化并入） | spec · [plan](S023-漏斗可用性与因子解耦/plan.md) · [tasks](S023-漏斗可用性与因子解耦/tasks.md) | 选股因子与工作流解耦，两套标准可插拔并存 |
| [S024](S024-拓扑展示/spec.md) | 拓扑展示（关系网+漏斗流程+连板梯队树，EdgeProvider 扩展位） | ✅已实现 2026-08-04（`e2f79ed`） | spec · [plan](S024-拓扑展示/plan.md) · [tasks](S024-拓扑展示/tasks.md) | 候选标的关系网+漏斗流向可视化+连板接力结构，先收敛核心边集 |
| [S025](S025-补前端入口/spec.md) | 补前端入口 | ✅已实现 2026-08-04（主 `fc87a65` + review fix） | spec | code review 14/14 闭环，tsc 0 + vitest 98 绿 |
| [S026](S026-pre-market-async/spec.md) | pre-market 异步化 | ✅已实现 2026-08-03（并入 S023 `ed0a0fe`，非独立分支） | spec | 盘前简报异步采集缓存 + 并发守卫 |
| [S028](S028-limitup-screener-fix/spec.md) | limitup-screener 修复（文案三态/trigger/因子层 conditions） | ✅已实现 2026-08-06（`9bddc92` + 连带 `b279b31`） | spec | 9 测试 + 778 passed |
| [S029](S029-gene-screener-wireup/spec.md) | GeneScreener 接通（阈值可配+执行检索+多层明细） | ✅已实现 2026-08-06（`6f6b2d5`） | spec | 149 前端测试 + build 绿 |
| [S030](S030-pre-market-multilayer/spec.md) | 盘前简报多层化 + UX 收敛 | 🗑️已废弃 2026-08-07（并入 S031 重写实现，留档作决策记录） | spec | 三层漏斗+抽屉+布局重整的最初设计，经 grill 后与调度收口合并为 S031 |
| [S031](S031-调度收口盘前多层按战法回测/spec.md) | 调度收口 + 盘前简报多层 + 交互式战法 + 按战法回测 | ✅已实现 2026-08-07（`409a31f` squash） | spec · [plan](S031-调度收口盘前多层按战法回测/plan.md) · [tasks](S031-调度收口盘前多层按战法回测/tasks.md) | 30/30 tasks；WAL/lifespan/BEIJING_TZ/预计算收口/seed/删 scheduler.py + 因子三层漏斗+战法反筛+真实回测 WinRatePanel |
| [S032](S032-调度收口第二轮/spec.md) | 调度收口第二轮（S011b）：主循环收口 + portfolio 日志重试 + 状态机接线落库 | ✅已实现 2026-08-07 | spec · [tasks](S032-调度收口第二轮/tasks.md) | R6 ticker/持仓刷新挂主循环（废线程桥接+修跨循环锁）+ R8 日志重试 + R10 workflow_state 落库（盘前自动 candidate/filtered + 手动流转端点）+ 顺手修 timedelta NameError |
| [S033](S033-状态机前端呈现/spec.md) | 状态机前端呈现（状态徽标+流转按钮+holding 价格采集） | ✅已实现 2026-08-07 | spec · [plan](S033-状态机前端呈现/plan.md) · [tasks](S033-状态机前端呈现/tasks.md) | workflow_state 扩列 entry_price/exit_price/strategy（COALESCE）+ 单股端点 + 列表徽标/抽屉状态卡/流转交互（watching 直连、holding/settled 表单），为 S034 SettlementEngine 铺路 |
| [S034](S034-结算接线/spec.md) | SettlementEngine 接线（settled 流转即结算写 winrate.db） | ✅已实现 2026-08-07 | spec · [tasks](S034-结算接线/tasks.md) | settled 流转触发结算（engine settle + gene_score 基因 DB 回查）写 winrate_records 喂既有胜率页；settled_at 幂等锚点 + 重入清零；entry_date=trade_date 诚实近似 |
| [S035](S035-ai-proxy-删除/spec.md) | ai_proxy 删除（死代码清理） | ✅已实现 2026-08-09 | spec · [plan](S035-ai-proxy-删除/plan.md) · [tasks](S035-ai-proxy-删除/tasks.md) | 删 ai_proxy 路由 + 死代码清理 |
| [S036](S036-工作流标灰/spec.md) | 工作流标灰（S012 修订版：适配 S033/S034 后的前端结构） | ✅已实现 2026-08-09 | spec · [plan](S036-工作流标灰/plan.md) · [tasks](S036-工作流标灰/tasks.md) | 适配状态机/结算后的前端标灰，桩→NotImplementedError |
| [S037](S037-gene-db-迁移/spec.md) | gene DB 路径迁移（三库 + winrate 统一到 .vibe-research/） | ✅已实现 | spec · [plan](S037-gene-db-迁移/plan.md) · [tasks](S037-gene-db-迁移/tasks.md) | gene_scores/winrate/market_data 三库统一 VR_DATA_DIR，迁移完整 |
| [S038](S038-持仓市价自动结算/spec.md) | 持仓市价自动结算（holding 流转 settled 时自动拉价填 exit_price） | ✅已实现（`0681061`） | spec · [plan](S038-持仓市价自动结算/plan.md) · [tasks](S038-持仓市价自动结算/tasks.md) | settled 流转拉 tencent_quote 市价预填 exit_price；exit_price_source 标注 market/manual |
| [S039](S039-StockDeep接线/spec.md) | StockDeep 个股深度页面接线（消费已有端点，第一批核心四块） | ✅已实现 2026-08-09 | spec · [plan](S039-StockDeep接线/plan.md) · [tasks](S039-StockDeep接线/tasks.md) | 个股深度页接已有端点，第一批核心四块 |
| [S040](S040-历史数据回填90天/spec.md) | 历史涨停池数据 K 线重建 + 双轨累积（v2） | ✅已实现（90天回填完成） | spec · [plan](S040-历史数据回填90天/plan.md) · [tasks](S040-历史数据回填90天/tasks.md) | K 线重建 122 天 + eastmoney_live 27 天，DB 覆盖 149 交易日/5715 条 |
| [S041](S041-回测定时任务与趋势看板/spec.md) | 回测定时任务 + 趋势看板 | ✅已实现（`26e7cb7`） | spec · [plan](S041-回测定时任务与趋势看板/plan.md) · [tasks](S041-回测定时任务与趋势看板/tasks.md) | daily_backtest_run task_type + backtest_daily_snapshots 表 + 趋势端点 + Backtest.tsx |
| [S042](S042-统一持仓建议引擎/spec.md) | 统一持仓建议引擎（推荐标的 + 自选 + 持仓，三场景） | ✅已实现 2026-08-09 | spec · [plan](S042-统一持仓建议引擎/plan.md) · [tasks](S042-统一持仓建议引擎/tasks.md) | position_advisor_v2 + advisory 路由 + Advisory.tsx 三场景页 |
| [S043](S043-次日溢价率单因子分析/spec.md) | 次日溢价率单因子分位分析 | ✅已实现 2026-08-10 | spec · [plan](S043-次日溢价率单因子分析/plan.md) · [tasks](S043-次日溢价率单因子分析/tasks.md) | 因子分位端点 + 前端因子分位 Tab |
| [S044](S044-候选池漏斗数据源补全/spec.md) | 候选池漏斗数据源补全（北向 + 板块联动 + 龙虎榜游资频次 + 公告类型化） | ✅已实现（R2 live 收尾 2026-08-10） | spec · [plan](S044-候选池漏斗数据源补全/plan.md) · [tasks](S044-候选池漏斗数据源补全/tasks.md) · [验收说明](S044-候选池漏斗数据源补全/验收说明.md) | 四源补全 + 板块源 live 修复（push2delay+ut/分页 496/级别归一/TTL 防封） |
| [S045](S045-漏斗层得分排序筛选/spec.md) | 漏斗层得分显示 + 得分排序 + 多选筛选 | ✅已实现 2026-08-10 | spec | FunnelLayerCard 得分显示 + 降序排序 + 战法/R3 触发类型多选筛选 |
| [S046](S046-fallback空写防护/spec.md) | fallback 空写防护（限流返空不覆盖好缓存） | ✅已实现 2026-08-10 | spec | _is_empty + save_cache 空不写 + load_cache 损坏自愈删除 + 空 fetch 降级好缓存 |
| [S047](S047-基因分权重回测校准/spec.md) | 基因分权重口径回测校准 | ✅已实现 2026-08-10 | spec · [证据报告](S047-基因分权重回测校准/证据报告.md) | full 权重改 40/25/25/0/10 + 历史 2023 行复算 |
| [S048](S048-工作流打磨/spec.md) | 工作流打磨（固定阶段位 + 历史视角 + 缓存 + 拓扑精简） | ✅已实现 2026-08-10 | spec | 固定阶段位 + 历史视角 + 缓存 + 拓扑精简 |
| [S049](S049-盘前简报漏斗重构与诊断修正/spec.md) | 盘前简报漏斗重构与诊断修正 | ✅已实现（离线全测绿） | spec · [HANDOFF-PROMPT](S049-盘前简报漏斗重构与诊断修正/HANDOFF-PROMPT.md) · [plan](S049-盘前简报漏斗重构与诊断修正/plan.md) · [task](S049-盘前简报漏斗重构与诊断修正/task.md) | 漏斗重构与诊断修正，子项 A/B/C/D 全落地 |
| [S050](S050-W0-行动闭环/spec.md) | W0 行为闭环（票根 + 影子对照 + 独立性基线） | ✅已实现（离线全测绿） | spec · [HANDOFF-PROMPT](S050-W0-行动闭环/HANDOFF-PROMPT.md) · [plan](S050-W0-行动闭环/plan.md) · [task](S050-W0-行动闭环/task.md) | 票根 + 影子对照 + 独立性基线 |
| [S051](S051-基因筛选体验批/spec.md) | 基因筛选体验批 | ✅已实现 2026-08-12 | spec · [HANDOFF-PROMPT](S051-基因筛选体验批/HANDOFF-PROMPT.md) · [plan](S051-基因筛选体验批/plan.md) · [task](S051-基因筛选体验批/task.md) | 阈值复位 50/60 + sanity 警告 + 分段视图 + 动态文案 + 零样本注记 |
| [S052](S052-回测快照回填与缺口补跑/spec.md) | 回测快照回填与缺口补跑 | ✅已实现 2026-08-12 | spec · [HANDOFF-PROMPT](S052-回测快照回填与缺口补跑/HANDOFF-PROMPT.md) · [plan](S052-回测快照回填与缺口补跑/plan.md) · [task](S052-回测快照回填与缺口补跑/task.md) | as_of_date 参数化 + 60 交易日回填 + 启动缺口补跑（零 em_get） |
| [S053](S053-炸板后溢价因子修复/spec.md) | 炸板后溢价因子修复 + match 条件解耦 | ✅已实现 2026-08-12 | spec | 数据源+计算重定义+match 解耦，pytest 1102 passed |
| [S054](S054-W0-工作流闭环呈现/spec.md) | W0 工作流闭环呈现（盘后三问 + 简报行为卡） | ✅已实现 | spec · [HANDOFF-PROMPT](S054-W0-工作流闭环呈现/HANDOFF-PROMPT.md) · [plan](S054-W0-工作流闭环呈现/plan.md) · [task](S054-W0-工作流闭环呈现/task.md) | 盘后三问 + 简报行为卡，T1-T9 全落地 |
| [S055](S055-盘中封单时序采集与炸板预警/spec.md) | 盘中封单时序采集与炸板预警规则引擎 | ✅已实现 | spec · [task](S055-盘中封单时序采集与炸板预警/task.md) · [tasks](S055-盘中封单时序采集与炸板预警/tasks.md) | 封单时序采集 + 炸板预警规则引擎，live 冒烟通过 |
| [S056](S056-天气熔断三铁律补全/spec.md) | 天气熔断三铁律规则补全（软 gate） | ✅已实现 | spec · [task](S056-天气熔断三铁律补全/task.md) · [tasks](S056-天气熔断三铁律补全/tasks.md) | 三铁律软 gate（只提醒不锁死） |
| [S057](S057-漏斗八项标准硬约束封顶/spec.md) | 漏斗八项标准硬约束封顶 | ✅已实现 | spec · [task](S057-漏斗八项标准硬约束封顶/task.md) · [tasks](S057-漏斗八项标准硬约束封顶/tasks.md) | 八项硬约束封顶，三态判定 missing 不臆造 |
| [S058](S058-战法双层卡片层与天气适配过滤/spec.md) | 战法双层卡片层与天气适配软过滤 | ✅已实现 | spec · [task](S058-战法双层卡片层与天气适配过滤/task.md) · [tasks](S058-战法双层卡片层与天气适配过滤/tasks.md) | 战法双层卡片 + 天气适配软过滤 + query_strategy_card 三出口 |
| [S059](S059-因子IC评估/spec.md) | 因子 IC 评估（backtest_lite 扩展） | ✅已实现 | spec · [task](S059-因子IC评估/task.md) · [tasks](S059-因子IC评估/tasks.md) | IC 评估扩展，样本<20 返 None 诚实标注 |
| [S060](S060-明日验证条件对账卡/spec.md) | 明日验证条件对账卡 | ✅已实现 | spec · [tasks](S060-明日验证条件对账卡/tasks.md) | 纯规则模板客观可测，后端 19 + 前端 4 测试 |
| [S061](S061-预测跟踪与自动验证/spec.md) | 预测跟踪与自动验证（预测账本） | ✅已实现 2026-08-12 | spec · [tasks](S061-预测跟踪与自动验证/tasks.md) | 预测账本——判断跟踪 + 到期自动验证 + 命中率统计 |
| [S062](S062-战法卡内容填充-反包与龙头/spec.md) | 战法卡内容填充：反包/龙头实盘参数 | ✅已实现 2026-08-12 | spec · [tasks](S062-战法卡内容填充-反包与龙头/tasks.md) | 反包/龙头战法卡实盘参数填充 |
| [S063](S063-情绪管线贯通与盘中辅助决策/spec.md) | 情绪管线贯通与盘中辅助决策 | ✅已实现 2026-08-13 | spec · [HANDOFF-PROMPT](S063-情绪管线贯通与盘中辅助决策/HANDOFF-PROMPT.md) · [plan](S063-情绪管线贯通与盘中辅助决策/plan.md) · [tasks](S063-情绪管线贯通与盘中辅助决策/tasks.md) | SentimentContext T-1 贯通 + 盘中 4 维评分 + T+1 投影 + 前端多页 |
| [S064](S064-盯盘教练MVP/spec.md) | W-C 盯盘教练 MVP | ✅已实现 2026-08-13 | spec | 盘中时刻表 10 槽位 + 条件状态清单 + attention_mode A/B/C + 教学点 |
| [S065](S065-weather-history持久化/spec.md) | weather_history 持久化 | ✅已实现 2026-08-13 | spec | 盘后落 weather_state 快照 + 五因子明细（W1 证据层前置，零 em_get） |
| [S066](S066-策略特定漏斗架构重构/spec.md) | 策略特定漏斗架构重构 | 🟡Phase 0-3 主体完成 2026-08-14 | spec · [plan](S066-策略特定漏斗架构重构/plan.md) · [tasks](S066-策略特定漏斗架构重构/tasks.md) · [HANDOFF-PROMPT](S066-策略特定漏斗架构重构/HANDOFF-PROMPT.md) | 3 套权重漏斗 + 天气硬开关 + 板块周期 + 日历因子 + 前端三页统一（后端 9 模块 201 测试 + 5 API + 前端组件/hooks/因子子页 331 测试） |
| [S067](S067-advisory-perf/spec.md) | advisory 端点性能优化 | ✅已实现 2026-08-14 | spec | advisory P0-P3 全落地（缓存+预热+并发+批量+超时降级），>40s→0.34s |

> S002 与 S005 为**短线 / 中长线并列**的两条主线；S001/S003 为支撑性修复；S004 为 S002 候选池的性能优化；S006 为系统级重写纲领（含 §1 合规边界调整后的 UI 重设计）；S017/S018 为 ML 涨跌预测栈（模型栈+特征工程解耦），在 §1 新边界内承担研究性预测职责。

> S021：无独立 spec（feat/fix/docs(S021) 三 commit 已落地 2026-08-02——误删恢复 + mootdx 空值崩溃修复 + workflow /api 前缀 + 体检报告 `reports/system-check-2026-08-02.md`；属修复/审计类，未走 SDD §0）。

> S027：跳过（编号预留未使用）。
