# Tasks: S010 — AI 工具注册表 + SYSTEM_PROMPT 新边界

> 依赖 `../S008`（工具签名稳定）。
> **2026-07-30 刷新**：T10/T11/T15 按弱合规（§1.1）重写——可给方向性研判/买卖时机/收益预期/操作建议；免责墙降为轻量风险提醒；四池可露个股名；保留工程底线（可复现/隔离/防封）。
>
> **2026-07-31 进度**：T1-T7 + T10 + T11 + T12 + T15(chat 侧) 已完成。
> - `backend/ai/tools/registry.py`（T1-T6 基础设施：反射/导出/派发）+ `stock_tools.py`（T3：7 工具装饰）已建。
> - `chat.py` T7 锁定：`TOOLS=registry.get_openai_tools()`、`_exec_tool` 改薄壳委托 `registry.execute`，删全部硬分支；schema 与旧 TOOLS 逐字一致；`monkeypatch chat._exec_tool` 仍生效。
> - T12 `tests/test_registry.py`（17 项：反射/三出口一致性/派发/合规）全过。
> - T15 chat 侧合规：SYSTEM_PROMPT 允许方向性研判 + 守工程底线（不承诺确定性/可复算）+ SYSTEM_PROMPT_NO_TOOLS 单赋值回归。
> - `pytest -m "not live"`：835 passed / 2 failed（600722 fallback 数据文件，另一会话 in-progress，非 S010）。
> - **剩余**：T8（mcp_server 改读 registry，删 `import chat`）、T9（cli_runtime 接 registry）、T13/T14（live 冒烟，需网络）。

## 任务清单

| ID | 任务 | 依赖 | 验收 |
|---|---|---|---|
| T1 | 建 `backend/ai/tools/registry.py`（`ToolDef`+`register_tool`+反射+导出+派发） | — | 装饰器可用 |
| T2 | `_build_schema_from_signature`（inspect→JSON schema） | T1 | 5 类型映射正确 |
| T3 | 装饰 5 工具（query_quote/valuation/reports/news/global_stock） | S008 | registry 含 5 工具 |
| T4 | `get_openai_tools()` 导出 function-calling 格式 | T1 | 与旧 chat.TOOLS schema 一致 |
| T5 | `get_mcp_tools()` 导出 MCP inputSchema | T1 | MCP 协议字段正确 |
| T6 | `execute(name, args)` 派发 | T1 | 调对应函数返结果 |
| T7 | `chat.py` `TOOLS`/`_exec_tool` 改读 registry | T4,T6 | 删硬分支；grep 无 if name== |
| T8 | `mcp_server.py` 改读 registry，删 `import chat`/`_exec_tool` | T5,T6 | mcp 不依赖 chat 私有 |
| T9 | `cli_runtime.py` 接 registry（共享清单） | T4 | 订阅出口清单一致 |
| T10 | `SYSTEM_PROMPT` 放宽措辞（可给方向性研判/买卖时机/收益预期/操作建议 + 轻量风险提醒 + 不承诺确定性 + 可复现底线） | — | diff 含允许+提醒+底线三条款；删旧「不给买卖时机/不承诺收益/不打分排名」 |
| T11 | 研判输出挂轻量风险提醒（「历史统计特征，市场有风险」），不强制「不构成投资建议」墙 | T10 | 输出含提醒 |
| T12 | 单测 `test_registry`（反射/派发/三出口导出一致性） | T6,T7,T8 | 全过 |
| T13 | live：POST /api/chat（cli+api 两配置）流式 200 | T7,T10 | delta+done |
| T14 | live：MCP 5 工具实测（600519/000858） | T8 | 返回正确 |
| T15 | 合规：SYSTEM_PROMPT diff 审查 + test_compliance.py | T10,T11 | 按 §1 新边界通过 |

## 依赖图
```
T1 ─ T2 ─ T3(S008) ─ T4,T5,T6
T4 ─ T7; T5,T6 ─ T8; T4 ─ T9
T10 ─ T11 ─ T15
T7,T8 ─ T12,T13,T14
```

## 合规检查点（按 §1 弱合规 2026-07-30）
- T10 SYSTEM_PROMPT 可给方向性研判/买卖时机/收益预期/操作建议；不承诺确定性保证；判断须可复现（工程底线）
- T11 轻量风险提醒（非强制免责墙）
- T3 注册表只挂客观+研究性判断工具
- 涨停四池/连板股榜可如实呈现个股 code/name（不强制剥离）
- 私有数据隔离 + 东财端点走 em_get（工程底线，保留）
