# Vibe-Research · 跨工具项目约定（AGENTS.md）

> 本文件是**跨工具共守**的项目约定——Claude Code、opencode、及任何 AI 编码代理在本仓库工作时**强制遵守**。与 `CLAUDE.md` 互补：CLAUDE.md 是 Claude Code 专属约束，本文件是**所有 agent 通用**的底线。
>
> 2026-07-31 落地，起因：多会话/多 agent 同 `develop` 并行 commit 导致历史 interleaved + 工作树 entangle（两起 `git checkout` 回 HEAD 丢未提交改动事故）。
> 2026-08-04 精简：原 feature 分支强制工作流过于冗长导致单一功能实现周期过长，经评估改为分级工作流——按改动规模分级匹配流程门。

---

## 会话开始协议（跨工具共守，最高优先级）

**所有 AI 编码代理（Claude Code / opencode / 其他）在本仓库工作时，每次会话开始先读知识图谱投研子区**：

1. 读 `/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/investing/MOC.md` — 投研知识图谱入口
2. 读 `/Users/lizhiwei/Documents/Obsidian Vault/10_Reference/index/MASTER_INDEX.md` — 跨项目全局索引
3. 按需读 `10_Reference/investing/` 下与本次任务相关的实体文件夹

**知识图谱是认知层，代码是执行层**——代码改了实体/关系/决策，同步更新图谱。图谱位置：`/Users/lizhiwei/Documents/Obsidian Vault/`（GitHub `lzw9560/knowledge`，私有）。四构件方法论详见 skill `ontology-knowledge-graph`。

---

## 分级工作流（2026-08-04 落地，替代原 Feature 分支工作流）

**改动按规模分级，匹配不同的流程门。** 不再对所有改动一刀切走 feature 分支 + 完整验收。

### 分级判据（组合规则）

| 级别 | 判据 |
|---|---|
| **small** | ≤50 行 + 单层（纯前端或纯后端） |
| **medium** | 跨层 或 >50 行 |
| **large** | 碰外部数据源 / 新增 AI 工具 / 涉及财务验算——自动 large，不管行数 |

### 流程门分级

| 门 | small | medium | large |
|---|---|---|---|
| spec.md | 免（commit message 记摘要） | 免（同） | 必写（`specs/SNNN-*/spec.md`） |
| plan/tasks | 免 | 免（需要时并入 spec） | 必写（可合并为 spec 内一节） |
| feature 分支 | 免（直接 develop 提交） | 免（直接 develop） | 保留（`feature/SNNN-slug`，off develop） |
| code review / grill | 免 | issue 层（`.scratch/` 单轮） | 完整 grill |
| review 轮数 | — | 单轮，仅 HIGH 阻断，MEDIUM 进 backlog | 单轮，仅 HIGH 阻断，MEDIUM 进 backlog |
| playwright 验收 | 免 | 简化单表（后端冒烟 or 关键路由） | playwright-pro 完整 |
| 归档 | 免 | 并入 squash commit message | 批量归档，不每 spec 单独 docs commit |

### 通用规则（所有级别）

- **语言**：与用户交流一律使用中文（含中间更新与最终回复）；commit message、spec/issue 文档默认中文，代码标识符保持英文。
- **提交纪律**：勤 commit、最小功能提交（`wip:` 前缀可）。**不准留长生命未提交工作树**——`git checkout` 回退事故丢的就是未提交改动。
- **合并**：large 用 `git merge --squash` 到 develop，一 spec 一 commit（`feat(SNNN): ...`）。medium/small 直接 develop commit。
- **分支清洁**：large 的 feature 分支合并后**立即删**（`git branch -d`），不留残留。无用分支是工程洁癖的对立面。
- **栈式依赖**：若 S020 依赖 S019 且 S019 未合并，`feature/S020` 基于 `feature/S019`（栈式）；S019 合并 develop 后 rebase。共享基础设施先合 develop。
- **外部源 live 冒烟**：接外部源的 spec live 冒烟通过前不合；"待 live 后定"占位项不得合并，拆出可合并部分。
- **工程底线不降级**（所有级别）：不臆造数据 / 私有数据隔离 / em_get 防封。涉及数据输出/AI 提示词/交易信号的改动，无论级别都过合规自查（弱合规，CLAUDE.md §1）。
- **spec 逻辑冲突审查**（所有级别）：新 spec 动笔前必须检索相关历史 spec（`specs/SNNN-*/spec.md`），逐条比对新设计与已有 spec 的产出契约/数据流/数据格式是否存在冲突。发现的冲突必须在 spec 中显式记录并给出处置预案（替换/共存/废弃三选一，写明迁移路径）。不留"实现时再说"的暗债。典型场景：新管线替代旧管线时旧产出的消费方（前端/快照/测试）的迁移路径；新数据格式与历史快照格式的兼容降级。
- **spec 多轮审查与冲突追溯**（所有级别）：large spec 落盘后必须经过多轮审查（至少 1 轮 Oracle 独立审查 + 1 轮 grill 自查），审查发现的冲突/缺陷修正后才进 plan。冲突审查表（§9）格式强制为：`| 旧 spec R-item | 旧决策 | 新决策 | 处置(替换/共存/废弃) | 迁移路径 |`，逐条列出被替换的 R-item + 迁移路径。冲突审查表是实现时的权威参考——实现时不需要翻旧 spec，只看新 spec 的冲突审查表。旧 spec 不回溯修改，保留作历史决策记录。
- **数据支撑优先**（所有级别）：所有架构决议、策略映射、参数选择必须有数据支撑，不得凭直觉拍脑袋。具体要求：(1) 引用统计结论时必须报告样本量、置信区间或提升倍数（lift），样本量 <30 的结论标注"探索性"不得作为定稿依据；(2) 跨数据源的比较必须先验证数据口径一致性，口径不一致时严禁跨源统计；(3) 随机基准（baseline）必须显式计算，"实际值 vs 随机期望"的提升不足 2x 的关联视为噪声，不得作为设计依据。违反此条的 spec 在 grill 阶段直接打回。
- **spec 落地后自动收拢**（所有级别）：每个 spec 验收通过后必须执行收拢流程（不可跳过）：(1) **task.md 勾选验收状态**——逐条 AC 勾 `[x]` + G 门标通过；(2) **spec.md 顶部状态改"✅已实现(日期)"**；(3) **归档到对应里程碑目录** `specs/archive/mN-xxx/SNNN-*/`（当前里程碑未归档的 spec 留 `specs/` 根目录，里程碑完成时批量归档）；(4) **更新 `specs/MILESTONES.md`**——该 spec 行状态改 ✅ + 状态栏标日期；(5) **同步项目文档**——若 spec 改了架构/数据流/路由/组件结构，更新 `CONTEXT.md`（根域模型，或等价的 ARCHITECTURE.md）+ `docs/premarket-workflow-logic.md`（工作流逻辑）+ `specs/README.md`（spec 索引表）中受影响的段落。以上 5 步在验收 commit 中一次性完成（`docs(SNNN): 验收 + 归档`）。**未收拢的 spec 视为未完成——禁止"实现完了但文档没更新"的暗债。**

### 适用范围

- 所有 AI 编码代理（Claude Code / opencode / 其他）与本仓库所有会话，自 2026-08-04 起执行。
- 2026-07-31 至 2026-08-03 期间按原 Feature 分支工作流执行的 spec（S022–S026）不溯及。

### 历史对照

08-01 前（无流程门）：12 spec/天。08-02 后（原 feature 分支全量门）：2 spec/天。本分级方案目标：small 回归直接提交节奏，medium 轻量过审，large 保留完整门。

---

## Agent skills

### Issue tracker

本地 markdown 工单层：`.scratch/<effort-slug>/` 存放 issue 工单（`issues/NN-<slug>.md` + `map.md`）+ triage 标签，承担研究问题/原型/AFK 领取队列、medium 级 code review。**正式 spec 不在此**——仍在 `specs/SNNN-*/`（CLAUDE.md §0）；`.scratch/` effort 成熟到要正式实现则毕业迁移为 `specs/SNNN-*/spec.md`。详见 `docs/agents/issue-tracker.md`。

### Triage labels

默认五角色标签（`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`），标签名即角色名。详见 `docs/agents/triage-labels.md`。

### Domain docs

单上下文：根 `CONTEXT.md`（或等价的 ARCHITECTURE.md） + `docs/adr/`（或 specs/decision-log.md）；缺失时静默跳过，由 `/domain-modeling` 懒创建。详见 `docs/agents/domain.md`。
