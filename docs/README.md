# docs/ — 设计文档 / PRD / 参考

> 这里放**上游自由格式**文档：产品 PRD、模块设计、UI 设计、API 对照、代码审查报告。
> 正式 SDD spec 在 `../specs/`（按 `SNNN-短标题/` 子目录组织，流程见 `../CLAUDE.md` §0）。
> 两者关系：docs/ 是"为什么这么做 / 当初怎么想"的背景；specs/ 是"做到什么程度、怎么验收"的契约。冲突时以 specs/ 为准。

## 目录

| 文档 | 定位 | 与 specs/ 关系 |
|---|---|---|
| `limitup-sniper-prd.md` | 投研助手总 PRD V2.0 | 产品总纲，specs/ 各项的上游 |
| `limitup-trading-workflow-prd.md` | 打板工作流 PRD v1.0（设计阶段） | ⚠️ **已被 `../specs/S002-打板工作流重构/` supersede**，保留作历史背景 |
| `limitup-design.md` | 打板策略模块设计 V2.0 | S002 落地的前身设计；实现以 `../specs/S002-打板工作流重构/spec.md` 为准 |
| `sentiment-weather-station-ui-design.md` | 情绪气象站 UI 设计 V2.0.3 | UI 参考（情绪/STI 功能仍在） |
| `API.md` | 前后端 API 对照 v0.1.3（2026-07-24） | 参考；新增端点以代码 + specs/ 为准 |
| `CODE_REVIEW_REPORT.md` | 代码审查报告（2026-07-24 快照） | 时间点报告 |
| `screenshots/` | 截图 | — |

> docs/ 文档多为 2026-07 中旬快照，可能滞后于代码；动手前以 `../specs/` 的已实现 spec 与 `../ARCHITECTURE.md` 为准。
