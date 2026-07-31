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

`SNNN` 三位递增。下一个新 spec 用 S006。

## 已有规范

| 编号 | 标题 | 状态 | 子文档 | 一句话 |
|---|---|---|---|---|
| [S001](S001-fix-chat-env-llm-config/spec.md) | 修复 chat._get_env_llm_config 缺失 → /api/chat 500 | ✅已实现 2026-07-29 | spec | 补全环境变量兜底函数，打通问 AI |
| [S002](S002-打板工作流重构/spec.md) | 打板工作流重构 · P1 候选池诊断统一 | ✅P1 已实现 2026-07-28（live 闭环 07-29） | spec · [plan](S002-打板工作流重构/plan.md) · [tasks](S002-打板工作流重构/tasks.md) · [验收报告](S002-打板工作流重构/验收报告.md) | 短线候选池漏斗 + 诊断卡，六类指标口径统一 |
| [S003](S003-api-bugfix-batch/spec.md) | 后端 API 冒烟测试缺陷修复批次 | ✅已实现 2026-07-29 | spec · [tasks](S003-api-bugfix-batch/tasks.md) | API 缺陷批量修复（含 value_funnel 等） |
| [S004](S004-candidates-funnel-performance/spec.md) | 候选池漏斗 run_funnel 性能优化 | 🟡草案 2026-07-29 | spec · [plan](S004-candidates-funnel-performance/plan.md) · [tasks](S004-candidates-funnel-performance/tasks.md) | 缓存+预计算+top-N 限界+独立 source 并行 |
| [S005](S005-中长线价值选股漏斗/spec.md) | 中长线价值选股漏斗（与短线 S002 并列） | ✅已实现 2026-07-29 | spec · [plan](S005-中长线价值选股漏斗/plan.md) · [tasks](S005-中长线价值选股漏斗/tasks.md) · [验收报告](S005-中长线价值选股漏斗/验收报告.md) | 价值四层漏斗 + 去劣 7 条 |

> S002 与 S005 为**短线 / 中长线并列**的两条主线；S001/S003 为支撑性修复；S004 为 S002 候选池的性能优化。
