// lib/query/types.ts — TanStack Query hook 选项类型（T9/T16）。
// Opts<T> 参数化：每 hook 用 Opts<Awaited<ReturnType<typeof api.X>>>，使 useQuery 的 data
// 推断回具体类型而非 {}（消除 spread 放宽根因），页面无需 as unknown as Iface cast。
import type { UseQueryOptions } from "@tanstack/react-query";

export type Opts<T> = Omit<UseQueryOptions<T>, "queryKey" | "queryFn" | "select" | "initialData">;
