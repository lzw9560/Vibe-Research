// lib/query/market.ts — TanStack Query hooks（市场/全球/组合/情绪气象/STI 只读端点）。
// S013 T8/T16：替页手写 loading/effect。写操作（POST/PUT/DELETE）不包。
// 类型收紧：Opts<Awaited<ReturnType<typeof api.X>>> 参数化，使 useQuery data 推断回具体类型而非 {}。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";

// ---- 无参 ----
export function useHealth(options?: Opts<Awaited<ReturnType<typeof api.health>>>) {
  return useQuery({ queryKey: ["market", "health"] as const, queryFn: () => api.health(), ...options });
}

export function useIndices(options?: Opts<Awaited<ReturnType<typeof api.indices>>>) {
  return useQuery({ queryKey: ["market", "indices"] as const, queryFn: () => api.indices(), ...options });
}

export function useMarketOverview(options?: Opts<Awaited<ReturnType<typeof api.marketOverview>>>) {
  return useQuery({ queryKey: ["market", "overview"] as const, queryFn: () => api.marketOverview(), ...options });
}

export function useEmotion(options?: Opts<Awaited<ReturnType<typeof api.emotion>>>) {
  return useQuery({ queryKey: ["market", "emotion"] as const, queryFn: () => api.emotion(), ...options });
}

export function useTurnoverTop(options?: Opts<Awaited<ReturnType<typeof api.turnoverTop>>>) {
  return useQuery({ queryKey: ["market", "turnoverTop"] as const, queryFn: () => api.turnoverTop(), ...options });
}

export function useGlobalIndices(options?: Opts<Awaited<ReturnType<typeof api.globalIndices>>>) {
  return useQuery({ queryKey: ["market", "globalIndices"] as const, queryFn: () => api.globalIndices(), ...options });
}

export function useRadar(options?: Opts<Awaited<ReturnType<typeof api.radar>>>) {
  return useQuery({ queryKey: ["market", "radar"] as const, queryFn: () => api.radar(), ...options });
}

export function usePortfolio(options?: Opts<Awaited<ReturnType<typeof api.portfolio>>>) {
  return useQuery({ queryKey: ["market", "portfolio"] as const, queryFn: () => api.portfolio(), ...options });
}

export function useMyReports(options?: Opts<Awaited<ReturnType<typeof api.myReports>>>) {
  return useQuery({ queryKey: ["market", "myReports"] as const, queryFn: () => api.myReports(), ...options });
}

// ---- 情绪气象站（多数返 { data: {...} } 信封，保持信封类型不解包）----
export function useSentimentWeatherLatest(options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherLatest>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherLatest"] as const, queryFn: () => api.sentimentWeatherLatest(), ...options });
}

export function useSentimentWeatherFactors(options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherFactors>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherFactors"] as const, queryFn: () => api.sentimentWeatherFactors(), ...options });
}

export function useSentimentWeatherStrategy(options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherStrategy>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherStrategy"] as const, queryFn: () => api.sentimentWeatherStrategy(), ...options });
}

export function useSentimentWeatherFuse(options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherFuse>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherFuse"] as const, queryFn: () => api.sentimentWeatherFuse(), ...options });
}

export function useSentimentWeatherAuction(options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherAuction>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherAuction"] as const, queryFn: () => api.sentimentWeatherAuction(), ...options });
}

export function useSentimentWeatherSealRisk(options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherSealRisk>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherSealRisk"] as const, queryFn: () => api.sentimentWeatherSealRisk(), ...options });
}

export function useSentimentWeatherPardon(options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherPardon>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherPardon"] as const, queryFn: () => api.sentimentWeatherPardon(), ...options });
}

// ---- 有参 ----
export function useGlobalStock(symbol: string, options?: Opts<Awaited<ReturnType<typeof api.globalStock>>>) {
  return useQuery({
    queryKey: ["market", "globalStock", symbol] as const,
    queryFn: () => api.globalStock(symbol),
    enabled: !!symbol,
    ...options,
  });
}

// ---- 可选参（不设 enabled，让 undefined 透传给后端处理）----
export function useIndustry(top = 20, options?: Opts<Awaited<ReturnType<typeof api.industry>>>) {
  return useQuery({ queryKey: ["market", "industry", top] as const, queryFn: () => api.industry(top), ...options });
}

export function useSentimentWeatherTimeline(days = 30, options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherTimeline>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherTimeline", days] as const, queryFn: () => api.sentimentWeatherTimeline(days), ...options });
}

export function useSentimentWeatherEvents(days = 30, options?: Opts<Awaited<ReturnType<typeof api.sentimentWeatherEvents>>>) {
  return useQuery({ queryKey: ["market", "sentimentWeatherEvents", days] as const, queryFn: () => api.sentimentWeatherEvents(days), ...options });
}

export function useStiLatest(date?: string, options?: Opts<Awaited<ReturnType<typeof api.stiLatest>>>) {
  return useQuery({ queryKey: ["market", "stiLatest", date] as const, queryFn: () => api.stiLatest(date), ...options });
}

export function useStiTimeline(days = 30, options?: Opts<Awaited<ReturnType<typeof api.stiTimeline>>>) {
  return useQuery({ queryKey: ["market", "stiTimeline", days] as const, queryFn: () => api.stiTimeline(days), ...options });
}
