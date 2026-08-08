# 任务拆分 · S035 ai_proxy 删除

> 级别：small，直接 develop 提交。

| ID | 任务 | 依赖 | 改动文件 | 验收方式 | AC |
|---|---|---|---|---|---|
| A1 | `rg "ai_proxy" backend/ --glob '*.py'` 确认引用清单（排除 .venv） | — | — | grep 输出确认只有 ai_proxy.py 自身 | A2 |
| A2 | 删除 `backend/routers/ai_proxy.py` | A1 | `backend/routers/ai_proxy.py`（删） | 文件不存在 | A1 |
| A3 | `rg "ai_proxy" backend/ --glob '*.py'` 确认零命中 | A2 | — | grep 无输出 | A2 |
| A4 | `pytest -m "not live"` 全过 | A2 | — | 全绿 | A3 |
| A5 | `app.py` import 列表确认无 ai_proxy 拋留 | — | — | grep app.py 无 ai_proxy | A4 |
