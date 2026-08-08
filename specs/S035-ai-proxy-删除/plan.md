# 技术方案 · S035 ai_proxy 删除

> 对应：`spec.md`（需求/验收）、`tasks.md`（原子任务）
> 级别：small，直接 develop 提交。

## 1. 改动

删 1 个文件 `backend/routers/ai_proxy.py`（131 行）。

## 2. 验证

- `rg "ai_proxy" backend/ --glob '*.py'` 确认零引用残留
- `app.py` import 列表本来就无 ai_proxy，无需改动
- pytest -m "not live" 确认不破
