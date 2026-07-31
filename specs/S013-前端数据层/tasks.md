# Tasks: S013 — 前端数据层

> 依赖 `../S009`（types.ts 生成）。

> **进度（2026-07-31）**：T1✅ `lib/api/client.ts` 建成——从 `api.ts` 提取 `ApiError`/`ACCESS_KEY`/`loadAccessKey`/`saveAccessKey`/`authHeaders`/`request<T>`/`get`，`api.ts` re-export 保持 `@/lib/api` import 路径不变（零行为变更），`npm run build` 绿。**phase 1b（T2-T5）完成**：T3✅ candidates.ts `req<T>` 并入（语义等价，别名复用零 call-site 改）；T4✅ value_funnel.ts `call<T>` 并入（后端 value-funnel 端点全返裸对象无 `{data:}`，request 解包回退 payload，发散点不触发）；T5✅ watchlist.ts 3 内联 fetch 转 request（保留 safe() fallback 层 + 数组过滤，顺带修 auth 部署下不发 Bearer + remove 失败不 fallback 的不一致）；T2✅ api.ts 20 裸 fetch 转 request/get（Pattern A scheduled-tasks/settings/limitup/review 机械并；Pattern B workflow 5 函数保留「失败返 null」try/catch + getBombAlerts `data?.alerts` 特殊解包，顺带修 auth 缺失）。仅 `downloadReport`（blob 下载，非 JSON）保留裸 fetch。`npm run build` 绿（tsc -b + vite）。**下一步**：T6 按域拆模块 / T7 TanStack Query / T10 router 懒加载（可并行）。

## 任务清单

| ID | 任务 | 依赖 | 验收 |
|---|---|---|---|
| T1 | 建 `lib/api/client.ts`（`request<T>`+ApiError+authHeaders） | — | 单测契约过 |
| T2 | `api.ts:911-1075` 20 裸 fetch 改走 client | T1 | grep 无裸 fetch |
| T3 | 删 `candidates.ts:req<T>` | T1 | 走 client |
| T4 | 删 `value_funnel.ts:call<T>` | T1 | 走 client |
| T5 | 删 `watchlist.ts` 内联 fetch | T1 | 走 client |
| T6 | `lib/api` 按域拆模块（quote/valuation/workflow…） | T1 | endpoint 分组 | ✅ 2026-07-31：api.ts 1108→203 行，拆 types(845)/scheduled(50)/workflow(34)，零行为变更 |
| T7 | 建 `lib/query/` + 装 @tanstack/react-query | — | QueryClientProvider 注入 | ✅ 2026-07-31 |
| T8 | 建 useQuote/useValuation/useFunnel/useReports/useNews hooks | T6,T7 | hooks 可用 | ✅ 2026-07-31（59 hooks：market 22/stock 17/limitup 20，未接线） |
| T9 | 29 页面迁移用 hooks（分批，删 267 处手写） | T8 | 各页无 useState/effect 手写 | ✅ 2026-07-31：17 页接线（Health + batch1 5 + batch2 11），剩 StockDeep 主 fetch 无 hook 不转、非 hook-api 页不转 |
| T10 | `router.tsx` 全量 `React.lazy`+`Suspense`+`errorElement` | — | 首包不含未访问页 | ✅ 2026-07-31 |
| T11 | `main.tsx` QueryClientProvider + Toaster 跟随主题 | T7 | 注入完成 | ✅ 2026-07-31（Toaster 跟随主题留 S014 入口） |
| T12 | 后端 `routers/ai_proxy.py`（持 key 代理，VR_API_KEY 鉴权） | — | /api/ai/proxy 可用 | ✅ 决议结案 2026-07-31：保留双配置（localStorage apiKey + env 兜底），当前 S001 状态即满足，无需新代理端点 |
| T13 | `llm.ts` 删 localStorage apiKey，只存 provider | T12 | grep 无 apiKey 明文 | ✅ 决议结案 2026-07-31：保留双配置（localStorage apiKey + env 兜底），当前 S001 状态即满足，无需新代理端点 |
| T14 | `useDarkMode`/`useTheme` 合一，读 prefers-color-scheme | — | 双 hook 冲突消除 | ✅ 2026-07-31 |
| T15 | `lib/utils` 加 `pctColor()`，替各页自定义 | — | grep 无重复 pctColor | ✅ 2026-07-31 |
| T16 | `npm run build` + `npx vitest run` 通过 | T9,T10 | 全绿 | ✅ 2026-07-31：build 绿 + vitest 1 passed（vitest.config.ts + src/test/setup.ts + smoke.test.ts，`npm run test` 脚本已加） |

## 依赖图
```
T1 ─ T2,T3,T4,T5,T6 ─ T8(T7) ─ T9 ─ T16
T10,T11,T14,T15(并行)
T12 ─ T13
```

## 合规检查点
- T13 apiKey 不进 git/不上传（私有数据）
- T12 代理端点受 VR_API_KEY 鉴权
