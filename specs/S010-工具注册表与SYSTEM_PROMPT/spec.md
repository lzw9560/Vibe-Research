# Spec: S010 — AI 工具注册表 + SYSTEM_PROMPT 新边界

> 状态：已实现 2026-08-01
> 作者：Claude  日期：2026-07-29
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 4 步）、`../S008`（数据层迁移后，工具签名稳定）、`../../ARCHITECTURE.md`（AI 三出口）、`../../CLAUDE.md` §1（新合规边界）

---

## 1. 问题 / 目标

`chat.py`(454) 的 `TOOLS` 是 OpenAI function-calling 格式的硬编码 list，`_exec_tool` 是 `if name=="query_quote": return astock.tencent_quote(...)` 式硬分支，任何 astock 签名变更需手改 `TOOLS`+`_exec_tool` 两处。`mcp_server.py` 完全寄生 `chat._exec_tool`（`_` 前缀私有）。`SYSTEM_PROMPT` 中立规则按旧边界"焊死、不得引入方向性建议"，需按新合规边界放宽为"可给教育研究性研判，但不承诺收益/不代客决策"。

**目标**：建 `ai/tools/registry.py` 声明式工具注册表（反射签名生成 schema），chat/mcp/cli 三出口共读；mcp 不再调 `chat._exec_tool` 私有；`SYSTEM_PROMPT` 按新边界放宽措辞。

## 2. 背景

- AI 三出口：订阅接入（cli_runtime）、API 接入（chat）、MCP（mcp_server），共用 `chat.TOOLS` + `SYSTEM_PROMPT`。
- MCP 暴露 5 工具：query_quote/valuation/reports/news/global_stock，执行映射到 astock/gstock。
- 新合规边界（2026-07-30 弱合规，私人助理定位）：允许方向性研判/买卖时机/收益预期/操作建议；免责墙降为轻量风险提醒；保留工程底线（可复现/私有数据隔离/防封）。详见 `../../CLAUDE.md` §1.1/§1.2。

## 3. 需求清单

- [ ] R1 建 `backend/ai/tools/registry.py`：装饰器 `@register_tool` 注册工具名+入参 schema+执行函数；反射 astock 签名生成 schema，消除手写 `chat.TOOLS`
- [ ] R2 `chat.py` 的 `TOOLS`/`_exec_tool` 改为读 registry（保留 OpenAI function-calling 格式导出，供 API 出口）
- [ ] R3 `mcp_server.py` 改读 registry，不再 `import chat`+调 `chat._exec_tool`
- [ ] R4 `cli_runtime.py` 接 registry（订阅出口不支持 function-calling，但工具清单共享）
- [ ] R5 `SYSTEM_PROMPT` 按新边界（§1.1 2026-07-30）放宽：允许方向性研判/买卖时机/收益预期/明确操作建议（半自动化，用户最终决策）；保留轻量风险提醒；保留工程底线（判断可复现、不臆造、不承诺确定性保证）
- [ ] R6 研判输出挂轻量风险提醒「历史统计特征，市场有风险」，不强制「不构成投资建议」墙
- [ ] R7 注册表只挂"返回客观数据 + 研究性判断"的工具，不挂越权工具；涨停四池/连板股榜可如实呈现个股 code/name

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| ➕`backend/ai/tools/registry.py` | ➕声明式注册表 |
| ➕`backend/ai/tools/__init__.py` | ➕ |
| `backend/chat.py` | 🔥`TOOLS`/`_exec_tool` 改读 registry；`SYSTEM_PROMPT` 放宽措辞 |
| `backend/mcp_server.py` | 🔥改读 registry，不调 `chat._exec_tool` |
| `backend/cli_runtime.py` | ✏️接 registry |
| `backend/routers/chat.py` | ✏️适配（若引用 chat.TOOLS） |

## 5. 设计方案

- **registry**：`@register_tool(name, description)` 装饰器，反射函数签名（inspect）生成 JSON schema 参数表；执行时 `registry.execute(name, args)` 派发。
- **三出口**：chat 用 registry 导出 OpenAI function-calling list；mcp 用 registry 转 MCP inputSchema + execute；cli_runtime 共享工具清单（订阅出口数据须已在 context，不调工具，但清单一致）。
- **SYSTEM_PROMPT 放宽**：从"不得引入方向性建议"改为"可给方向性研判/买卖时机/收益预期/操作建议"，挂轻量风险提醒（非强制免责墙），不承诺确定性收益。具体措辞在 plan.md 细化，须 diff 审查。
- **取舍**：不重构流式/SSRF 防护逻辑（保留 chat 现有 SSRF 校验、流式 NDJSON），只解耦工具表与 SYSTEM_PROMPT 措辞。

## 6. 验收标准

- [ ] A1 `ai/tools/registry.py` 装饰器注册 5 工具；反射签名生成 schema 与手写一致
- [ ] A2 chat/mcp/cli 三出口共读 registry；mcp 不再 `import chat`/调 `_exec_tool`
- [ ] A3 MCP 5 工具实测（query_quote 600519/000858）返回正确
- [ ] A4 `POST /api/chat`（cli + api 两种配置）流式 200，含 delta+done
- [ ] A5 `SYSTEM_PROMPT` 含方向性研判允许条款 + 轻量风险提醒（非强制免责墙）+ 确定性收益承诺禁止
- [ ] A6 研判输出挂轻量风险提醒「历史统计特征，市场有风险」（非强制免责墙）
- [ ] A7 `pytest -m "not live"` 全过（含 test_chat）
- [ ] A8 合规审查：SYSTEM_PROMPT diff 按 CLAUDE.md §1 新边界通过

## 7. 合规自查（按 CLAUDE.md §1 弱合规 2026-07-30）

- [ ] 注册表只挂客观+研究性判断工具
- [ ] SYSTEM_PROMPT 可给方向性研判/买卖时机/收益预期/操作建议；不承诺确定性保证；判断须可复现（工程底线）
- [ ] 研判输出挂轻量风险提醒（非强制免责墙）
- [ ] 涨停四池/连板股榜可如实呈现个股 code/name
- [ ] 东财端点仍走 em_get（工程底线）
- [ ] 私有数据隔离（VR_DATA_DIR，不进 git/不上传）

## 8. 测试计划

- 单测：test_registry（注册/反射/派发）、test_chat（SSRF/边界/流式）
- live：POST /api/chat（cli-claude + api 两种配置）、MCP 5 工具实测
- 合规：SYSTEM_PROMPT diff 人工审查 + test_compliance.py

## 9. 风险与回滚

- 🟡 SYSTEM_PROMPT 放宽尺度：措辞过宽会越界（如变荐股）——缓解：轻量风险提醒 + 确定性收益承诺禁止 + 不臆造（工程底线）+ diff 审查
- 🟡 反射签名与手写 schema 差异：边界类型（Optional/list）映射——单测比对
- 🟢 回滚：恢复硬编码 TOOLS + 旧 SYSTEM_PROMPT
