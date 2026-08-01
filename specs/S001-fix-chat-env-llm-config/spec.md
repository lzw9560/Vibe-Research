# Spec: S001 — 修复 chat._get_env_llm_config 缺失导致 /api/chat 500

> 状态：已实现(2026-07-29)｜已验收(2026-07-29)
> 作者：Claude  日期：2026-07-28
> 关联：`ARCHITECTURE.md` §"已知问题"、`CLAUDE.md` §4

## 验收记录（2026-07-29）
- `chat.py:185` 已定义 `_get_env_llm_config()`，读 `VR_LLM_BASE_URL/VR_LLM_API_KEY/VR_LLM_MODEL` 返回 dict（与 §5 设计一致）。
- `.env.example` 已含三项注释。
- 重启后端实测：
  - `GET /api/settings/llm-env-status` → **HTTP 200** `{"has_env_base_url":false,"has_env_api_key":false,"has_env_model":false}`（原 500）。
  - `POST /api/chat`（deepseek+假key）→ **HTTP 200**，进入流式，假 key 触发 401 走流内 error 事件（原 500）。
- 结论：AC1-AC4 全部通过；S005 L4 AI 出口（`deep-ai` 端点）的前置阻塞已解除。

## 1. 问题 / 目标
`routers/chat.py` 第 32/59/64 行调用 `chat_layer._get_env_llm_config()`，但该函数在 `chat.py` 中未定义（`hasattr(chat,"_get_env_llm_config")==False`）。导致 `POST /api/chat` 与 `GET /api/settings/llm-env-status` 同步抛 `AttributeError` → FastAPI 返回 HTTP 500。develop 分支当前"问 AI（API 接入）"完全不可用。目标：补全函数使两条端点恢复 200。

## 2. 背景
- `routers/chat.py:61` 错误信息已暗示环境变量名为 `VR_LLM_BASE_URL` / `VR_LLM_API_KEY`。
- 第 64 行是"环境变量兜底"：前端未传的 baseURL/apiKey/model 用环境变量补全，**每次** /api/chat 都执行（在 StreamingResponse 之前，同步路径）。
- 订阅接入（provider=`cli-*`）在第 53 行 `is_cli` 分支提前走 cli_runtime，**不触此 bug**——故仅 API 接入受影响。
- 实测：`GET /api/settings/llm-env-status` → 500；`POST /api/chat`（deepseek+假key）→ 500。

## 3. 需求清单
- [x] R1 在 `chat.py` 实现 `_get_env_llm_config() -> dict`，读 `VR_LLM_BASE_URL`/`VR_LLM_API_KEY`/`VR_LLM_MODEL`，返回 `{"baseURL","apiKey","model"}`（缺省为空字符串）。
- [x] R2 `GET /api/settings/llm-env-status` 返回 200 + `{has_env_base_url, has_env_api_key, has_env_model}`。
- [x] R3 `POST /api/chat` 不再因缺函数 500；缺 key 时按第 61 行逻辑返回 400（而非 500）。
- [x] R4 不破坏订阅接入路径与 SSRF 防护。

## 4. 受影响文件
| 文件 | 改动 |
|---|---|
| `backend/chat.py` | 新增 `_get_env_llm_config()`（os.getenv 读三个变量，返回 dict） |
| `backend/.env.example` | 补 `VR_LLM_BASE_URL` / `VR_LLM_API_KEY` / `VR_LLM_MODEL` 注释项 |
| 可选 `backend/routers/chat.py` | 无需改（调用已就位） |

## 5. 设计方案
最小实现：
```python
import os
def _get_env_llm_config() -> dict:
    """从环境变量读 LLM 兜底配置（前端未传字段时补全）。不暴露敏感值给前端以外的接口。"""
    return {
        "baseURL": os.getenv("VR_LLM_BASE_URL", ""),
        "apiKey":  os.getenv("VR_LLM_API_KEY", ""),
        "model":   os.getenv("VR_LLM_MODEL", ""),
    }
```
- 不读 `fallback.py` 的 `VR_FREE_PROVIDER` 等（那是免费兜底另一套，不在本 spec 范围）。
- 备选：直接删掉 `routers/chat.py` 三处调用、不做环境变量兜底——**不选**，因为环境变量兜底是公网/无人值守部署的合理能力，且第 61 行已面向它设计。

## 6. 验收标准
- [x] A1 `python -c "import chat; chat._get_env_llm_config()"` 不报错，返回三键 dict。
- [x] A2 `curl http://127.0.0.1:8900/api/settings/llm-env-status` → HTTP 200。
- [x] A3 `POST /api/chat` 带 baseURL+apiKey+model → 不再 500（进入流式，key 无效时返回流内 error 事件或 400，而非 500）。
- [x] A4 `pytest -m "not live"` 全过。

## 7. 合规自查（口径按 CLAUDE.md §1.1，2026-07-30）
- [x] R1 只读环境变量、返回配置，不输出建议/标的/预测（实现时口径）。
- [x] 未改 `chat.SYSTEM_PROMPT`（实现时口径；措辞放宽见 S010）。
- [x] 不涉及涨停四池、用户私有数据。
- [x] 不新增东财端点。

## 8. 测试计划
- 单测：`backend/tests/test_chat_env_config.py`——mock env 验证返回结构与空值。
- 手动：A2/A3 的 curl。
- `pytest -m "not live"`。

## 9. 风险与回滚
- 影响：仅修两端点 500→正常，风险低。
- 回滚：删除新增函数即回到当前状态（不影响其他模块，因当前本就不可用）。
