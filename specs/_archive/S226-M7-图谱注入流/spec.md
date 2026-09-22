# S226 · M7 图谱注入流

> 状态：已实现（2026-09-21，commit 51515b6 + 3de9eb6 + fde0eb2）｜分级：medium（issue 层单轮 review）
> 关联：S216 P1 kg.py、ai.tools.kg_tools、chat._call_llm、§1.2 工程底线
> 解冻：专家讨论 + 用户同意——kg.py 框架在 + chat LLM 复用，注入流是延伸非新基建，认知层价值中

## 1. 问题 / 目标

kg.py inbox 端点（GET /api/kg/inbox）读 vault/investing/inbox/ markdown，但**写入流未实现**——M7 LLM 注入缺。公告数据有（astock.announcements 走 em_get），LLM 有（chat._call_llm VR_LLM env），但没调起来写 inbox/。

**目标**：公告→DeepSeek JSON→inbox/ markdown 写入 + /graph 审核界面（审过移 reference/）。

## 2. 需求

1. 注入函数：调 astock.announcements(code) + chat._call_llm 提取实体 JSON + 写 inbox/ markdown 待审
2. 审过函数：inbox/{file} → reference/{file}（移到正式区）
3. endpoint：POST /api/kg/inject?code= + POST /api/kg/approve?filename=
4. scheduler executor + seed cron（盘后扫涨停股公告注入）
5. 前端 /graph 审核界面（读 inbox 列表 + 审过按钮）

## 3. 受影响文件

- `tools/kg_inject.py`（新）：inject_announcements_to_inbox + approve_inbox_to_reference
- `routers/kg.py`：加 POST /api/kg/inject + POST /api/kg/approve
- `scheduler/executors/kg.py`：加 kg_inject executor
- `scheduler/seed.py`：注册 kg_inject cron
- `frontend/src/pages/cognition/CognitionPage.tsx`：审核界面（读 inbox + 审过按钮）

## 4. 验收

- POST /api/kg/inject?code=600519 → 拉 announcements + LLM 提取 → 写 inbox/ markdown
- GET /api/kg/inbox 返注入的待审 markdown
- POST /api/kg/approve?filename=X → 移到 reference/
- 前端 /graph 审核（如果做）
- tsc 0 错 + pytest 相关 test green

## 5. 合规自查

- 不臆造：LLM 输出进 inbox 待审，非直接进正式区 ✅
- 私有数据隔离：公告公开数据（em_get），不读持仓/研报/API key ✅
- §1.2 认知层非交易信号——不碰选股分/§44v2 ✅
- 秘密走 env：VR_LLM_API_KEY 走 os.environ，不贴 key 值 ✅
