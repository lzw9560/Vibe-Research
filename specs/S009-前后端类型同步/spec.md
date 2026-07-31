# Spec: S009 — 前后端类型同步（openapi-codegen）

> 状态：phase 1 已实现 2026-07-31（toolchain: dump_openapi.py + openapi-typescript + gen:api + types.ts 就位，tsc 绿）；**phase 2（T5/T6 替手写类型+杀 any）经复核判定为非机械——手写接口严格必填、生成 schema 诚实但宽松，替换会级联 null-handling 错误，且 T13 引擎模型是有损投影——故 phase 2 移交 S013 前端数据层协同**
> 作者：Claude  日期：2026-07-29；续推 2026-07-31
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 3 步）、`../S008`（前置，需路由挂 response_model）、`../../ARCHITECTURE.md`

---

## 1. 问题 / 目标

前端 `lib/api.ts`(1239) 手写 ~60 个 TS 接口，注释多处标"对齐 backend/xxx/models.py"，无 codegen、漂移风险高；大量 `Record<string, any>`/`any`（metrics/winRate/riskDashboard 等几乎全 any）。S008 后路由挂 `response_model`，FastAPI OpenAPI schema 已准确，可用 codegen 自动同步。

**目标**：用 openapi-codegen 从 FastAPI OpenAPI 生成 `lib/api/types.ts`，替手写 60 接口；CI 校验漂移；根治类型漂移。**本 spec 必须排在 S008 之后**（解循环依赖：codegen 依赖后端先有 response_model）。

## 2. 背景

- S008 完成后，routers 挂 `response_model`，`/openapi.json` 输出准确 schema。
- 当前 `lib/api.ts:85-909` 60 接口手写；`:911-1075` 20 个绕过抽象的裸 fetch（在 S013 前端数据层一并清）。
- 无 codegen 管线，无 CI 校验。

## 3. 需求清单

- [ ] R1 选型并装 openapi-codegen（如 `@hey-api/openapi-ts` 或 `openapi-typescript`，轻量、CI 可跑）
- [ ] R2 跑 `openapi.json` → `frontend/src/lib/api/types.ts` 生成
- [ ] R3 删 `lib/api.ts` 内手写 60 接口，改为 import 生成的 types
- [ ] R4 `package.json` 加 `gen:api` 脚本 + `prebuild` 钩子校验 types.ts 与 openapi.json 一致
- [ ] R5 CI 加漂移校验：生成 types.ts 与仓内提交版本 diff 即失败
- [ ] R6 消除 `any`（生成类型替换 `Record<string, any>` 区段）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/package.json` | ✏️加 codegen devDep + gen:api 脚本 + prebuild |
| ➕`frontend/src/lib/api/types.ts` | ➕由生成产生（替手写） |
| `frontend/src/lib/api.ts` | ✏️删手写 60 接口，import 生成的 types |
| ➕`frontend/openapi-codegen.config.*` | ➕codegen 配置 |
| `.github/workflows/*` 或 CI | ✏️加 types.ts 漂移校验步骤 |

## 5. 设计方案

- **选型**：`openapi-typescript`（纯类型生成，零运行时，轻）或 `@hey-api/openapi-ts`（含 client）。推荐 `openapi-typescript`——只生类型，client 逻辑在 S013 单独建。
- **管线**：后端 `uvicorn` 启动 → dump `/openapi.json` → `openapi-typescript` 生 `types.ts` → prebuild 校验。
- **顺序约束**：本 spec 在 S008（路由 response_model）之后；否则 schema 不准。
- **取舍**：不生成 client 函数（保留 S013 的 `request<T>` 统一封装），只生类型，避免 codegen 覆盖业务封装。

## 6. 验收标准

- [ ] A1 `lib/api/types.ts` 由 `openapi.json` 生成，含全部端点的 request/response 类型
- [ ] A2 `lib/api.ts` 手写 60 接口删除，统一 import 生成的 types
- [ ] A3 `npm run gen:api` 能刷新 types.ts；`prebuild` 校验通过
- [ ] A4 CI 漂移校验：types.ts 与 openapi.json 不一致时失败
- [ ] A5 `npm run build`（tsc -b）通过，无类型错误
- [ ] A6 `lib/api.ts` 后半段 `any` 区段被生成类型替换

## 7. 合规自查（按新 CLAUDE.md §1）

- [ ] codegen 只生类型，不引入方向性字段
- [ ] 生成的类型来自后端客观数据模型（S007/S008），无主观判断字段
- [ ] 无私有数据泄露到类型

## 8. 测试计划

- `npm run build` 通过
- `npx vitest run`（S007 骨架）通过
- 手动：改一个后端 response_model 字段 → gen:api → types.ts diff → CI 失败（验证漂移检测）

## 9. 风险与回滚

- 🟡 生成类型与手写命名差异：消费者（pages）需适配字段名变更——缓解：S008 已统一字段名，codegen 反映统一后命名
- 🟡 openapi.json 生成需后端启动：CI 用 `uvicorn` 后台跑 dump，或直接 `app.openapi()` 导出
- 🟢 回滚：删 types.ts + 恢复手写接口
