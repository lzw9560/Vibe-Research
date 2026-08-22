# Spec: S035 — ai_proxy 删除（死代码清理）

> 状态：已完成（2026-08-09）
> 作者：Codex  日期：2026-08-08
> 关联：`../S025-补前端入口/spec.md`（S027 范围中 ai_proxy 项）、`backend/routers/chat.py`（功能超集）、`backend/routers/ai_proxy.py`（待删文件）
>
> 级别：**small**（删 1 文件 131 行，单层纯后端，无跨层影响）

## 1. 问题 / 目标

`backend/routers/ai_proxy.py`（131 行）实现了一个 LLM 请求透传端点（`POST /api/ai/proxy`），但：

- **未在 `app.py` 注册**——`include_router` 列表（`app.py:145-259`）无 `ai_proxy`，端点不可达。
- **零前端消费方**——前端代码库中无任何 `.ts`/`.tsx` 文件调用 `/api/ai/proxy`。
- **功能被 `/api/chat` 超集覆盖**——`/api/chat` 同样服务端持有 key、转发上游 LLM、支持流式，且额外支持 function-calling（工具调用）、CLI 订阅接入、上下文注入。ai_proxy 的纯透传能力是 chat 的子集。

131 行死代码维护成本 > 价值。删。

## 2. 背景

- ai_proxy 和 chat 路由都从 `chat.py` 模块层取环境变量配置（`VR_LLM_BASE_URL` / `VR_LLM_API_KEY` / `VR_LLM_MODEL`）。
- ai_proxy 流式用 SSE（`text/event-stream`），chat 流式用 NDJSON（`application/x-ndjson`）——格式不兼容，前端如要接 ai_proxy 需写第二套解析逻辑。
- ai_proxy `ProxyReq.provider` 字段注释写"前向兼容，当前不做路由分支"——预埋的多 provider 路由从未实现。
- S025 spec 明确将 ai_proxy 移到 S027 范围："后端 router 未在 app.py 注册＝双端死代码，功能被 live /api/chat 覆盖"。

## 3. 需求清单

- [x] R1 删除 `backend/routers/ai_proxy.py`
- [x] R2 确认无其他文件 import `ai_proxy`（grep 验证）
- [x] R3 `app.py` 无需改动（本来就没注册）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `backend/routers/ai_proxy.py` | 删除 |

## 5. 设计方案

直接删文件。不保留不注册——YAGNI。如将来确需"无工具、纯透传"的轻量 LLM 端点，重写 131 行成本远低于维护死代码。

## 6. 验收标准

- [x] A1 `backend/routers/ai_proxy.py` 不存在
- [x] A2 `rg "ai_proxy" backend/ --glob '*.py'` 零命中（排除 `.venv`）
- [x] A3 `pytest -m "not live"` 全过（817 passed, 8 deselected, 0 failed, 245.75s）
- [x] A4 `app.py` import 列表无 `ai_proxy` 残留

## 7. 合规与工程底线自查

- [ ] 不涉研判/数据输出/买卖时机——纯删死代码
- [ ] 不涉及用户私有数据
- [ ] 不涉及东财端点

## 8. 测试计划

- 离线：`cd backend && .venv/bin/python -m pytest -m "not live"`
- grep 确认零引用残留

## 9. 风险与回滚

- 零风险：删未注册的死代码文件，无运行时影响
- 回滚：`git revert`
