# Plan: S010 — AI 工具注册表 + SYSTEM_PROMPT 新边界技术方案

> 对应 `spec.md`。细化 registry 设计、三出口接入、SYSTEM_PROMPT 措辞放宽。
>
> **2026-07-30 刷新**：对齐 CLAUDE.md §1 弱合规（私人投研助理定位）。原 plan 按 07-29 旧边界「强制免责墙 / 禁代客决策 / 四池不露个股名」起草；§1.1 (07-30) 已将这些降为风险提醒级，并允许方向性研判/买卖时机/收益预期/操作建议。本刷新仅改 §3 措辞边界与合规护栏，registry 设计（§1-2）不受合规变更影响。

## 1. registry 设计

```python
# backend/ai/tools/registry.py
from typing import Callable
import inspect

_REGISTRY: dict[str, ToolDef] = {}

class ToolDef:
    name: str; description: str; func: Callable; schema: dict

def register_tool(name: str, description: str):
    def deco(func):
        schema = _build_schema_from_signature(func)  # inspect 签名→JSON schema
        _REGISTRY[name] = ToolDef(name, description, func, schema)
        return func
    return deco

def get_openai_tools() -> list[dict]: ...   # 导出 function-calling 格式
def get_mcp_tools() -> list[dict]: ...      # 导出 MCP inputSchema
def execute(name: str, args: dict): ...      # 派发
```

- 反射 `inspect.signature` 生成参数 schema（str/int/list/Optional 映射）
- 装饰 5 工具：`@register_tool("query_quote", "A股实时行情")` 标注 astock/gstock 函数

## 2. 三出口接入

- `chat.py`：`TOOLS = registry.get_openai_tools()`；`_exec_tool` → `registry.execute(name, args)`（删除硬分支）
- `mcp_server.py`：`MCP_TOOLS = registry.get_mcp_tools()`；`_handle` → `registry.execute`；**不再 `import chat`/调 `_exec_tool`**
- `cli_runtime.py`：共享工具清单（订阅出口不支持 function-calling，但清单一致）

## 3. SYSTEM_PROMPT 措辞放宽（2026-07-30 弱合规刷新，须 diff 审查）

旧（焊死，07-29 前边界）：「不得引入方向性建议、不预测涨跌、不给买卖时机、不承诺收益、不打分排名」

新（按 CLAUDE.md §1.1 弱合规，私人助理定位）：
- **允许**：方向性研判、买卖时机研判、收益预期（三情景测算）、模式识别、战法匹配、风险标注、明确操作建议（半自动化：可给建议，用户最终决策）
- **保留为轻量风险提醒**：「历史统计特征，市场有风险」——不再强制「不构成投资建议」墙（S017 预测端点同此简化）
- **工程底线（保留，非合规仪式）**：
  - 判断须基于公开数据 + 既定规则可复算（`~/tools/financial_rigor.py` 核对），禁止臆造、禁止心算
  - 收益预期是研究参考性测算，**不得承诺确定性保证**（可给三情景概率/分位区间，不得说「必涨 X%」）
- **涨停四池/连板股榜**：可如实呈现个股 code/name（公开榜单，用户自己的工具），不强制剥离
- **私有数据隔离**：持仓/研报/API key 只存 `VR_DATA_DIR`（项目内 `.vibe-research/`），不进 git/不上传
- **防封**：东财端点走 `em_get`，不裸调 requests

措辞放宽的护栏从旧「强制免责墙 + 禁代客决策」三重，改为「可复现（工程底线）+ 不承诺确定性 + 轻量风险提醒」三重——保护用户自己的钱与数据，而非合规仪式。

## 4. 实现步骤
1. 建 `ai/tools/registry.py`（装饰器+反射+导出+派发）
2. 装饰 5 工具函数
3. chat `_exec_tool` 改读 registry；删硬分支
4. mcp_server 改读 registry，删 `import chat`
5. cli_runtime 接 registry
6. SYSTEM_PROMPT 措辞放宽 + 轻量风险提醒（非强制免责墙）
7. 单测 test_registry（反射/派发/三出口导出一致性）
8. live：POST /api/chat（cli+api）+ MCP 5 工具实测
9. 合规：SYSTEM_PROMPT diff 审查 + test_compliance.py

## 5. 风险点
- SYSTEM_PROMPT 放宽过宽 → 可复现 + 不承诺确定性 + 轻量风险提醒 + diff 审查多重护栏
- 反射签名与手写 schema 边界类型差异 → 单测比对 5 工具 schema
- mcp 改读 registry 后 MCP 协议字段映射 → 保留 `inputSchema` 转换
