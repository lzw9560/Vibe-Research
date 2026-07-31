# Spec: S013 — 前端数据层（统一 client + TanStack Query + 懒加载 + apiKey 代理）

> 状态：草案
> 作者：Claude  日期：2026-07-29
> 关联：`../S006-系统重写纲领/spec.md`（§5 第 7 步）、`../S009`（types.ts 已生成）、`../S014`（UI 拆分用本 spec 的 hooks）、`../../ARCHITECTURE.md`（前端）

---

## 1. 问题 / 目标

前端 4 套并行 fetch 封装（`api.ts:request<T>`、`candidates.ts:req<T>`、`value_funnel.ts:call<T>`、`watchlist.ts` 内联）行为微异（解包与否）；`lib/api.ts`(1239) 内 20 个绕过自身抽象的裸 fetch（`:911-1075`）；29 页面 267 处手写 loading/setError，无缓存/去重/后台刷新；router 0 懒加载（26+ 页面全量进首包）；`lib/llm.ts` apiKey 明文存 localStorage 且随请求 body 发后端。

**目标**：统一 `lib/api/client.ts` 单一 `request<T>`；删 3 套复制封装 + 20 裸 fetch；TanStack Query hooks 替 267 处手写；router 全量懒加载；apiKey 移后端代理，前端只存 provider 选择。

## 2. 背景

- S009 已用 codegen 生成 `lib/api/types.ts`，本 spec 用之。
- `request<T>`（`api.ts:54-81`）抽象本身够用（鉴权头/JSON/ApiError/解包），但被绕过。
- `chatStream`（`llm.ts:59-113`）NDJSON 流式解析合理，保留但抽 `useChatStream` hook（在 S014 AI 对话重做）。
- localStorage 散落 8 处；本 spec 只处理 apiKey 那处。

## 3. 需求清单

- [ ] R1 建 `lib/api/client.ts`：单一 `request<T>`（鉴权头/JSON/ApiError/`payload?.data ?? payload` 解包）；删 `api.ts` 内 20 裸 fetch 改走 client
- [ ] R2 删 `candidates.ts:req<T>`/`value_funnel.ts:call<T>`/`watchlist.ts` 内联 fetch，全走 client
- [ ] R3 建 `lib/query/` TanStack Query hooks（useQuote/useValuation/useFunnel/useReports/useNews…）替 29 页 267 处手写 loading/setError
- [ ] R4 `router.tsx` 全量 `React.lazy`+`Suspense`+`errorElement`（26+ 页面懒加载）
- [ ] R5 `main.tsx` 注入 `QueryClientProvider`；`Toaster theme` 跟随主题
- [ ] R6 `lib/llm.ts` apiKey 移后端代理：后端加 `/api/ai/proxy` 端点持 key，前端只存 provider 选择（不存 apiKey）
- [ ] R7 `hooks/useDarkMode.ts` 与 `useTheme` 合一；读 `prefers-color-scheme`；暖橙主题保留+加切换入口（S014 落地入口）
- [ ] R8 `lib/utils` 加统一 `pctColor()` 涨跌色（替各页自定义）

## 4. 受影响文件

| 文件 | 改动 |
|---|---|
| `frontend/src/lib/api.ts` | 🔥拆为 `api/client.ts`+按域 endpoint 模块（types 由 S009 生成） |
| ➕`frontend/src/lib/api/client.ts` | ➕单一 request<T> |
| ➕`frontend/src/lib/query/` | ➕TanStack Query hooks |
| `frontend/src/lib/candidates.ts`/`value_funnel.ts`/`watchlist.ts` | 🩹删复制封装 |
| `frontend/src/lib/llm.ts` | 🩹apiKey 移后端代理 |
| ➕`backend/routers/ai_proxy.py` 或扩展 chat | ➕后端持 key 代理端点 |
| `frontend/src/router.tsx` | ✏️全量 lazy+errorElement |
| `frontend/src/main.tsx` | ✏️QueryClientProvider+Toaster 跟随 |
| `frontend/src/hooks/useDarkMode.ts` | 🩹合一+读系统偏好 |
| 29 页面 | ✏️改用 query hooks（267 处手写删） |
| `frontend/package.json` | ✏️加 @tanstack/react-query；🩹删 zustand 或落地 |

## 5. 设计方案

- **client.ts**：保留现有 `request<T>` 逻辑（已够用），把它独立成 `api/client.ts`；所有 endpoint 按域拆模块（quote/valuation/workflow/…）import client。
- **TanStack Query**：每域一个 hook（`useQuote(codes)`/`useValuation(code)`…），stale-while-revalidate + 自动去重 + 后台刷新；page 改 `const {data, isLoading, error} = useQuote(...)`，删手写 useState/effect。
- **apiKey 代理**：后端 `/api/ai/proxy` 持 key（从环境变量读，不存前端），前端只发 provider+messages；key 不进 localStorage/不上传。
- **取舍**：zustand 列依赖未用——删（减负）；client state 暂不需要 store（TanStack Query 管 server state，client state 用 React state）。

## 6. 验收标准

- [ ] A1 `lib/api/client.ts` 单一 `request<T>`；4 套复制封装删；20 裸 fetch 改走 client
- [ ] A2 29 页面改用 query hooks；267 处手写 loading/setError 删
- [ ] A3 router 全量 lazy；首包不含未访问页面代码（build 产出 chunk 分割）
- [ ] A4 `QueryClientProvider` 注入；`Toaster` 跟随主题
- [ ] A5 apiKey 不进 localStorage；`/api/ai/proxy` 持 key；前端只存 provider
- [ ] A6 `useDarkMode`/`useTheme` 合一；读 `prefers-color-scheme`
- [ ] A7 `npm run build` + `npx vitest run` 通过
- [ ] A8 `chatStream` 流式行为不变（AI 对话重做在 S014）

## 7. 合规自查（按新 CLAUDE.md §1）

- [ ] apiKey 移后端，不进 git/不上传（私有数据保护）
- [ ] client/query 不引入方向性判断字段
- [ ] 暖橙主题入口不涉及合规
- [ ] 东财端点仍走 em_get（前端无关）

## 8. 测试计划

- vitest：client `request<T>` 契约（鉴权/JSON/解包/错误）；query hooks 基础行为
- `npm run build` chunk 分割验证
- live：逐页加载、切换主题、AI 对话流式
- 安全：grep 前端无 apiKey 明文残留

## 9. 风险与回滚

- 🟡 29 页面迁移工作量大：分批迁移，每批验证
- 🟡 apiKey 代理改变后端职责：需鉴权（VR_API_KEY 保护代理端点）
- 🟢 回滚：恢复 api.ts + 各封装
