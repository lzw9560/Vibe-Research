# Tasks: S009 — 前后端类型同步

> 依赖 `../S008`（路由已挂 response_model）。**必须排 S008 后**。

> **进度（2026-07-31）**：phase 1 完成（commit `eb4cec9`）——T1✅ 装 openapi-typescript、T2✅ dump_openapi.py（monkeypatch scheduler 免副作用）、T3✅ gen:api 脚本、T4✅ 生成 types.ts（140 paths/26 schemas，tsc 绿）。T7⏳ prebuild drift gate 暂缓（系统 python=3.7 无 fastapi 会破 build，待 venv-on-PATH/CI）。**phase 2 正式判定非机械（2026-07-31 续推复核）**：T5/T6（替手写类型+杀 any）即便对已浮出 OpenAPI 的 6 个全保真 schema（Quote/GlobalStock/GlobalMetrics/EmotionResponse/LianbanStock/Emotion）也会级联——手写 `Quote`（api.ts:88）字段**严格必填**（`name: string`/`price: number`），生成 schema **诚实但宽松**（`name?: string|null`/`price: number|null`）；且 `Quote` 被 `GlobalStock.quote` 引用，替任一处都把宽松性级联到所有 `stock.quote.name` 消费点，触发一片 null-handling 类型错误。另：T13 引擎面向模型（Financials/Announcement）是有损投影，挂 `/api/financials` 丢 5 字段+`_numf("547.03亿")→None` 把字符串值变 null，挂 `/api/announcements` 丢 `url`（已回滚两处破坏性挂载）。**结论**：phase 2 本质是前端数据层重构，应并入 S013 协同（统一 client + 消费点 null-handling 修订 + 全保真响应模型），不作 S009 独立机械任务推。**phase 1（toolchain 就位、tsc 绿）为本 spec 交付物；phase 2 移交 S013。**T8 CI 待 .github/workflows 建立。T9 build 绿（phase 1 未引用 types.ts）；T10 vitest 待装。

## 任务清单

| ID | 任务 | 依赖 | 验收 |
|---|---|---|---|
| T1 | 装 `openapi-typescript` devDep | — | package.json 有 |
| T2 | 写 `scripts/dump_openapi.py`（`app.openapi()` 导出） | S008 | 生成 openapi.json |
| T3 | `package.json` 加 `gen:api` 脚本（dump+生成） | T1,T2 | `npm run gen:api` 生成 types.ts |
| T4 | 跑 gen:api 生成 `lib/api/types.ts` | T3 | types.ts 含全部端点类型 |
| T5 | 删 `lib/api.ts:85-909` 手写 60 接口，import 生成类型 | T4 | 无手写接口；build 过 |
| T6 | 替换 `lib/api.ts:1175-1228` 的 `any` 区段 | T4 | 无 any 残留 |
| T7 | 加 `prebuild` 钩子（gen:api + git diff --exit-code） | T3 | types.ts 漂移则 build 失败 |
| T8 | CI 加漂移校验步骤 | T7 | CI 跑 gen:api + diff |
| T9 | `npm run build`（tsc -b）通过 | T5,T6 | 无类型错误 |
| T10 | `npx vitest run` 通过 | T9 | 全绿 |

## 依赖图
```
S008 ── T2
T1,T2 ── T3 ── T4 ── T5,T6 ── T9 ── T10
T3 ── T7 ── T8
```

## 风险检查点
- T2 `app.openapi()` 依赖 app 可 import（lifespan 在 S011 可能阻塞）→ dump 脚本需 app 能无副作用启动
- CI 需 Python+Node 双环境
