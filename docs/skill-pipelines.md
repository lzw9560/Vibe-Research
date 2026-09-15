# Skill 工作流速查（Vibe-Research）

> 2026-09-15 三专家审计固化（Multi-Agent Systems Architect + Reality Checker + Minimal Change Engineer + grep 复核）。codify ad-hoc skill 成可复用 pipeline（实践⑤）。详细行为见各 skill `SKILL.md`。融合 §0/§7 不重述。

## 会话开头（不跳过，§7 提效习惯）
1. `handoff` — 恢复上次未答问题
2. `recall` — 查相关历史决策（非平凡任务前）
3. `codegraph explore "X"` — 结构查询（63MB 图在 repo 根；1 次顶 10 次 grep+read；MCP 断则 fallback grep+read）
4. `vr-healthcheck` — 三查根基（venv/RAM/会话数）

## spec→实现流（= §0 SDD，引用不重述）
`brainstorming`（澄清）→ 写 spec → `writing-plans` → 拆 tasks → `test-driven-development`（RED→GREEN）→ ≥6-lens `grilling`（§44/方法论承重）→ `verification-before-completion`（evidence before assertions）

## edge 研究流
`edge-pipeline-orchestrator`（编排）→ `residual-edge-analyzer`（拆 α vs β）→ `edge-strategy-reviewer`（过拟合/样本/执行审）→ `signal-postmortem`（事后复盘）

## 承重墙白名单（提效时绝不砍，Reality Checker 2026-09-15）
- **编码纪律**：`systematic-debugging` / `test-driven-development` / `verification-before-completion` / `using-superpowers` / `receiving-code-review` + `requesting-code-review`
- **§44v2 链**：`skill-backtest-overfit`（DSR/PBO/haircut）/ `residual-edge-analyzer` / `edge-strategy-reviewer` / `edge-pipeline-orchestrator` / `signal-postmortem` / `trade-hypothesis-ideator` / `skill-factor-orthogonalize` / `drawdown-circuit-breaker` / `pre-trade-discipline-gate`
- **工程底线（§1.2）**：三查根基 / `em_get` 防封 / 私有数据隔离（.vibe-research/）/ `~/tools/financial_rigor.py` + `report_audit.py` 验算
- **自进化**：`lesson` + `self-improving-agent`（corrections.jsonl → learned-rules.md → CLAUDE.md 升级链，今日 19:14 仍活）

## 提效铁律（learned-rules.md 2026-09-15，用户自定）
**提效只优化"怎么跑"，不优化"跑多少"**——砍 grep→codegraph ✓ / 砍手写→recall ✓ / 砍顺序→并行 ✓；**绝不砍** MAX_ROUNDS / 视角数 / effort / grill / verify / TDD / financial_rigor。

## 安全 DROP（已验，需用户 OK）
`agent-memory`（≡memory-discipline 逐字节）/ `proactive-agent`（零引用）/ `data-quality-checker`（域不符，§5 financial_rigor 覆盖）。
conditional（默认留）：`hithink-*` 10 子（CLI 未装，保父 `hithink-finance`）/ `grill-me`（`grilling` 指针，保 grilling）/ `skill-quant-factor-skill-factory` + `openclaw-healthcheck-cron`（NEEDS_PROOF 留）。

## 否掉（over-engineering）
新编排框架（LangGraph/CrewAI/AutoGen）/ YAML pipeline runner / 统一 skill dispatcher / CLAUDE.md §7 重构成状态机 / memory 迁 DB。
