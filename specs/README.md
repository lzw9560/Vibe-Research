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

`SNNN` 三位递增。下一个新 spec 用 S025。

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
| [S023](S023-漏斗可用性与因子解耦/spec.md) | 漏斗可用性与因子解耦（P1 打磨：盘前简报接因子+候选详情依据链+漏斗每层可观测可调参+真实数据不静默返空） | 🟡草案 2026-08-02 | spec · [plan](S023-漏斗可用性与因子解耦/plan.md) · [tasks](S023-漏斗可用性与因子解耦/tasks.md) | 选股因子与工作流解耦，两套标准可插拔并存 |
| [S024](S024-拓扑展示/spec.md) | 拓扑展示（关系网+漏斗流程+连板梯队树，EdgeProvider 扩展位） | 🟡草案 2026-08-02 | spec · [plan](S024-拓扑展示/plan.md) · [tasks](S024-拓扑展示/tasks.md) | 候选标的关系网+漏斗流向可视化+连板接力结构，先收敛核心边集 |

> S002 与 S005 为**短线 / 中长线并列**的两条主线；S001/S003 为支撑性修复；S004 为 S002 候选池的性能优化；S006 为系统级重写纲领（含 §1 合规边界调整后的 UI 重设计）；S017/S018 为 ML 涨跌预测栈（模型栈+特征工程解耦），在 §1 新边界内承担研究性预测职责。

> S021：无独立 spec（feat/fix/docs(S021) 三 commit 已落地 2026-08-02——误删恢复 + mootdx 空值崩溃修复 + workflow /api 前缀 + 体检报告 `reports/system-check-2026-08-02.md`；属修复/审计类，未走 SDD §0）。下一个新 spec 用 S025。
