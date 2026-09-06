// lib/query/stock.ts — TanStack Query hooks（个股只读端点）。S013 T8/T16。
// 写操作不包。所有 hook 以 code 为键，空 code 不发请求。
// 类型收紧：Opts<Awaited<ReturnType<typeof api.X>>> 参数化，消 {} 放宽。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";

// quote 的入参是逗号分隔的 codes 字符串（多股行情），非单 code。
export function useQuote(codes: string, options?: Opts<Awaited<ReturnType<typeof api.quote>>>) {
  return useQuery({
    queryKey: ["stock", "quote", codes] as const,
    queryFn: () => api.quote(codes),
    enabled: !!codes,
    ...options,
  });
}

export function useValuation(code: string, options?: Opts<Awaited<ReturnType<typeof api.valuation>>>) {
  return useQuery({
    queryKey: ["stock", "valuation", code] as const,
    queryFn: () => api.valuation(code),
    enabled: !!code,
    ...options,
  });
}

export function useValuationPercentile(code: string, options?: Opts<Awaited<ReturnType<typeof api.percentile>>>) {
  return useQuery({
    queryKey: ["stock", "valuationPercentile", code] as const,
    queryFn: () => api.percentile(code),
    enabled: !!code,
    ...options,
  });
}

export function useFinancials(code: string, options?: Opts<Awaited<ReturnType<typeof api.financials>>>) {
  return useQuery({
    queryKey: ["stock", "financials", code] as const,
    queryFn: () => api.financials(code),
    enabled: !!code,
    ...options,
  });
}

export function useAnnouncements(code: string, options?: Opts<Awaited<ReturnType<typeof api.announcements>>>) {
  return useQuery({
    queryKey: ["stock", "announcements", code] as const,
    queryFn: () => api.announcements(code),
    enabled: !!code,
    ...options,
  });
}

export function useReports(code: string, options?: Opts<Awaited<ReturnType<typeof api.reports>>>) {
  return useQuery({
    queryKey: ["stock", "reports", code] as const,
    queryFn: () => api.reports(code),
    enabled: !!code,
    ...options,
  });
}

export function useNews(code: string, options?: Opts<Awaited<ReturnType<typeof api.news>>>) {
  return useQuery({
    queryKey: ["stock", "news", code] as const,
    queryFn: () => api.news(code),
    enabled: !!code,
    ...options,
  });
}

export function useMargin(code: string, options?: Opts<Awaited<ReturnType<typeof api.margin>>>) {
  return useQuery({
    queryKey: ["stock", "margin", code] as const,
    queryFn: () => api.margin(code),
    enabled: !!code,
    ...options,
  });
}

export function useBlockTrade(code: string, options?: Opts<Awaited<ReturnType<typeof api.blockTrade>>>) {
  return useQuery({
    queryKey: ["stock", "blockTrade", code] as const,
    queryFn: () => api.blockTrade(code),
    enabled: !!code,
    ...options,
  });
}

export function useHolders(code: string, options?: Opts<Awaited<ReturnType<typeof api.holders>>>) {
  return useQuery({
    queryKey: ["stock", "holders", code] as const,
    queryFn: () => api.holders(code),
    enabled: !!code,
    ...options,
  });
}

export function useDividend(code: string, options?: Opts<Awaited<ReturnType<typeof api.dividend>>>) {
  return useQuery({
    queryKey: ["stock", "dividend", code] as const,
    queryFn: () => api.dividend(code),
    enabled: !!code,
    ...options,
  });
}

export function useFundFlow(code: string, options?: Opts<Awaited<ReturnType<typeof api.fundFlow>>>) {
  return useQuery({
    queryKey: ["stock", "fundFlow", code] as const,
    queryFn: () => api.fundFlow(code),
    enabled: !!code,
    ...options,
  });
}

export function useDragonTiger(code: string, options?: Opts<Awaited<ReturnType<typeof api.dragonTiger>>>) {
  return useQuery({
    queryKey: ["stock", "dragonTiger", code] as const,
    queryFn: () => api.dragonTiger(code),
    enabled: !!code,
    ...options,
  });
}

export function useLockup(code: string, options?: Opts<Awaited<ReturnType<typeof api.lockup>>>) {
  return useQuery({
    queryKey: ["stock", "lockup", code] as const,
    queryFn: () => api.lockup(code),
    enabled: !!code,
    ...options,
  });
}

export function useBlocks(code: string, options?: Opts<Awaited<ReturnType<typeof api.blocks>>>) {
  return useQuery({
    queryKey: ["stock", "blocks", code] as const,
    queryFn: () => api.blocks(code),
    enabled: !!code,
    ...options,
  });
}

export function useHotConcepts(code: string, options?: Opts<Awaited<ReturnType<typeof api.hotConcepts>>>) {
  return useQuery({
    queryKey: ["stock", "hotConcepts", code] as const,
    queryFn: () => api.hotConcepts(code),
    enabled: !!code,
    ...options,
  });
}

export function useInvestorQa(code: string, options?: Opts<Awaited<ReturnType<typeof api.investorQa>>>) {
  return useQuery({
    queryKey: ["stock", "investorQa", code] as const,
    queryFn: () => api.investorQa(code),
    enabled: !!code,
    ...options,
  });
}

// S039: 个股深度聚合（GET /stock/{code}/deep，12 源 _safe_call 聚合）。
// 整体返 StockDeep（端点 200）；字段级 null 是后端单源失败的正常降级。
// get<T> 会 throw ApiError（连不上后端/HTTP 错），useQuery 的 error 据此走错误态。
export function useStockDeep(code: string, options?: Opts<Awaited<ReturnType<typeof api.stockDeep>>>) {
  return useQuery({
    queryKey: ["stock", "deep", code] as const,
    queryFn: () => api.stockDeep(code),
    enabled: !!code,
    ...options,
  });
}

// ora-3 §1.5：个股知识图谱关联摘要（GET /stock/{code}/kg-summary）。
// 前端用此数据渲染「在知识图谱中查看」外链 + 关联数，不做节点数徽标。
export function useStockKgSummary(code: string, options?: Opts<Awaited<ReturnType<typeof api.stockKgSummary>>>) {
  return useQuery({
    queryKey: ["stock", "kg-summary", code] as const,
    queryFn: () => api.stockKgSummary(code),
    enabled: !!code,
    staleTime: 5 * 60 * 1000, // 图谱结构低频变，缓存 5 分钟
    ...options,
  });
}
