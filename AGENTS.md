# Vibe-Research · 跨工具项目约定（AGENTS.md）

> 本文件是**跨工具共守**的项目约定——Claude Code、opencode、及任何 AI 编码代理在本仓库工作时**强制遵守**。与 `CLAUDE.md` 互补：CLAUDE.md 是 Claude Code 专属约束，本文件是**所有 agent 通用**的底线。
>
> 2026-07-31 落地，起因：多会话/多 agent 同 `develop` 并行 commit 导致历史 interleaved + 工作树 entangle（两起 `git checkout` 回 HEAD 丢未提交改动事故）。

---

## Feature 分支工作流（强制）

**每个 spec 的实现走独立 feature 分支，完成后 squash 合并 develop。** 不在 `develop` 上直接写实现代码。

### 分支规则
- **命名**：`feature/S<NNN>-<slug>`（如 `feature/S020-worldmonitor`），slug 与 spec 标题一致。
- **base**：off `develop`（或依赖未合并时 off 依赖的 feature 分支——见"栈式依赖"）。
- **本地开发，不 push**：feature 分支只存本地，不 `git push`；远程 ecs 测试用 tarball 同步。
- **单一会话**：一个 feature 分支**同一时刻只一个会话/agent 写**。多会话并行请各开各的 feature 分支，不共写同一分支。

### 提交纪律
- feature 分支上**勤 commit、最小功能提交**（`wip:` 前缀可）。**不准留长生命未提交工作树**——`git checkout` 回退事故丢的就是未提交改动；commit 进 feature 分支即受保护。

### 栈式依赖（依赖未合并的 spec 怎么并行）
- 若 S020 依赖 S019 且 S019 未合并：`feature/S020` 基于 `feature/S019`（栈式）；S019 合并 develop 后，`feature/S020` rebase 到 develop。
- **共享基础设施**（validators / TTLCache / 模型等被多 spec 用的）**先合 develop**，再开依赖它的派生 feature。

### 合并准入门（grill 硬阻）
- 合并前必过 **grill / code review**。grill 标的 🔴（含"外部源 live 冒烟未通过"）= **硬阻**，不得合并。
- 接外部源的 spec（如 S020 worldmonitor）**live 冒烟通过前不合**；纯重构 / 数据层内部 spec，`pytest -m "not live"` 全绿 + grill 无 🔴 即可。
- "待 live 后定"的占位项（availability_offset / 握手协议等）：**不得以此状态合并**——拆出可合并部分，余下挂 feature 分支等 live。

### 合并
- `squash` 到 develop，一个 spec 一个 commit（`feat(S020): ...`）。丢失中间调试历史是已知代价——靠 grill 报告替代追溯。
- 合并后**删本地 feature 分支（留 90 天再清）**；分支未 push 故无远程可删。

### spec 文档归属
- `spec.md` / `plan.md` / `tasks.md` **先进 develop**（在写 feature 实现前），feature 分支只带实现代码。

### 适用范围
- 所有 AI 编码代理（Claude Code / opencode / 其他）与本仓库所有会话，自 2026-07-31 起执行。
- 历史遗留（当前 develop 上的未 push 提交 + 未提交工作树）不溯及；新 spec 实现一律走本流程。
