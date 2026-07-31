# Plan: S009 — 前后端类型同步技术方案

> 对应 `spec.md`。本 plan 细化 codegen 选型、管线脚本、CI 漂移校验、types.ts 替换路径。

## 1. 选型：`openapi-typescript`

- 纯类型生成（`.d.ts`），零运行时依赖，轻量
- 不生成 client 函数（保留 S013 的 `request<T>` 统一封装，避免 codegen 覆盖业务封装）
- 备选 `@hey-api/openapi-ts`（含 client）——不选，因 client 逻辑要在 S013 统一

## 2. 管线脚本

### 2.1 dump openapi.json（不需 uvicorn 运行）
```python
# scripts/dump_openapi.py
from app import app
import json
with open("frontend/openapi.json", "w", encoding="utf-8") as f:
    json.dump(app.openapi(), f, ensure_ascii=False, indent=2)
```
用 `app.openapi()` 直接导出，免起服务（CI 友好）。

### 2.2 生成 types.ts
```jsonc
// frontend/package.json
"scripts": {
  "gen:api": "python ../scripts/dump_openapi.py && openapi-typescript openapi.json -o src/lib/api/types.ts",
  "prebuild": "npm run gen:api && git diff --exit-code src/lib/api/types.ts"
}
```
- `gen:api`：dump + 生成
- `prebuild`：生成后 `git diff --exit-code`——types.ts 与仓内版本不一致则失败（漂移检测）

## 3. CI 漂移校验

`.github/workflows/ci.yml`（或等效）加：
```yaml
- run: cd frontend && npm run gen:api
- run: git diff --exit-code src/lib/api/types.ts  # 漂移即 CI 失败
- run: npm run build
```
- 后端 response_model 改了但未 regen types.ts → CI 失败 → 强制同步

## 4. types.ts 替换手写路径

### 4.1 删 `lib/api.ts:85-909` 手写 60 接口
- 改为 `import type { paths, components } from "./types"`
- endpoint 函数返回类型用 `components["schemas"]["Quote"]` 等

### 4.2 消除 `any`
- `lib/api.ts:1175-1228` 的 `metricsDataFetch`/`winRateAdjustments`/`riskDashboard`/`sectorDivergence` 等全 `any` → 用生成类型
- 生成类型来自 S007/S008 的 Pydantic response_model

## 5. 配置文件

`frontend/openapi-codegen.config.ts`（如选 openapi-typescript 则只需 package.json 脚本，无独立配置）。

## 6. 实现步骤
1. 装 `openapi-typescript` devDep
2. 写 `scripts/dump_openapi.py`（依赖 S008 已挂 response_model）
3. 跑 `gen:api` 生成 `types.ts`
4. `lib/api.ts` 删 60 手写接口，import 生成类型
5. 替换 `any` 区段
6. 加 `prebuild` + CI 漂移校验
7. `npm run build` + `npx vitest run` 通过

## 7. 风险点
- 生成类型命名与手写差异 → S008 已统一字段名（change_pct/market_cap 等），codegen 反映统一后命名，消费者适配在 S013
- `app.openapi()` 依赖 app 能 import（lifespan 调度器在 S011 可能阻塞 import） → dump 脚本用独立最小 app 或 mock 调度器
- CI 需 Python + Node 双环境 → 用 GitHub Actions matrix 或分步 job
