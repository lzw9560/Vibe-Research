# Plan: S013 — 前端数据层技术方案

> 对应 `spec.md`。细化 client、Query hooks、懒加载、apiKey 代理、主题合一。

## 1. client.ts（单一 request<T>）

```typescript
// lib/api/client.ts
export class ApiError extends Error { status: number; detail: string }
export function authHeaders(): Record<string,string> { /* 读 vr-access-key */ }
export async function request<T>(url, method?, body?): Promise<T> {
  const r = await fetch(`/api${url}`, { headers: { ...authHeaders(), "Content-Type":"application/json" }, method, body: JSON.stringify(body) });
  if (!r.ok) throw new ApiError(r.status, await r.json().then(d=>d.detail).catch(()=>r.statusText));
  const payload = await r.json();
  return payload?.data ?? payload;  // 解包 {"data":...} 信封
}
```
- 删 `api.ts:911-1075` 20 个裸 fetch，改走 client
- 按域拆 endpoint 模块：`api/quote.ts`/`valuation.ts`/`workflow.ts`… 各 import client

## 2. TanStack Query hooks

```typescript
export const useQuote = (codes: string[]) =>
  useQuery({ queryKey: ["quote", codes], queryFn: () => api.quote(codes), staleTime: 30_000 });
```
- 每域一 hook（useQuote/useValuation/useFunnel/useReports/useNews/useWatchlist/usePortfolio…）
- 29 页面改 `const {data, isLoading, error} = useQuote(...)`，删手写 useState/useEffect（267 处）
- stale-while-revalidate + 自动去重 + 后台刷新

## 3. 懒加载

```typescript
const DailyReview = lazy(() => import("./pages/DailyReview"));
<Suspense fallback={<PageSkeleton/>}><DailyReview/></Suspense>
```
- 26+ 页面全量 lazy；`errorElement` 路由级错误边界

## 4. apiKey 代理

- 后端 `routers/ai_proxy.py`：`POST /api/ai/proxy` 持 key（环境变量 `VR_LLM_API_KEY`），转发到 LLM；受 `VR_API_KEY` 鉴权保护
- 前端 `llm.ts`：删 localStorage 存 apiKey；只存 provider 选择；请求只发 provider+messages
- `chatStream` 流式逻辑保留（后端代理流式透传）

## 5. 主题合一

- `useDarkMode`/`useTheme` 合一为 `useTheme`；读 `prefers-color-scheme` 初值
- 三主题 dark/light/warm-orange；暖橙入口在 Settings（S014 落地）
- `main.tsx` `<Toaster theme={theme}/>` 跟随；`QueryClientProvider` 注入

## 6. 实现步骤
1. 建 `client.ts`，迁 20 裸 fetch
2. 删 candidates/value_funnel/watchlist 复制封装
3. 建 `lib/query/` hooks，29 页面迁移（分批）
4. router 全量 lazy + errorElement
5. 后端 ai_proxy 端点 + 前端 llm.ts 改代理
6. useTheme 合一 + Toaster 跟随
7. `pctColor` 迁 lib/utils
8. `npm run build` + vitest 通过

## 7. 风险点
- 29 页面迁移量大 → 分批，每批 vitest
- ai_proxy 需鉴权防滥用 → VR_API_KEY 保护
- TanStack Query staleTime 须按域调（行情 30s，研报 5min）
