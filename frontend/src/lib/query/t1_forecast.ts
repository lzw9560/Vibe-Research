// lib/query/t1_forecast.ts — S232 T+1 涨停预测 watchlist hook。
// 观察池非买入信号。5.28x lift 真但 EV -0.87% 负。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface T1WatchlistStock {
  code: string;
  name: string;
  turn: number;
  vr5: number;
  pctChg: number | null;
  close: number | null;
  high: number | null;
  low: number | null;
  amount: number | null;
  // 二次确认字段（累积 60 天验证，初始 null）
  t1_zt: boolean | null; // T+1 是否涨停（T+1 收盘后回填）
  t1_auction: string | null; // 二次确认：竞价状态（低开/高开/平开）
  t1_seal_time: string | null; // 二次确认：封单时间
  confirmed: boolean | null;
}

export interface T1Watchlist {
  date: string;
  signal: string;
  signal_lift: number;
  signal_lift_ci: string;
  base_rate: number;
  hit_rate: number;
  edge_status: string; // "weak-signal-EV-negative"
  honest_caveat: string;
  count: number;
  stocks: T1WatchlistStock[];
}

export function useT1Watchlist(date?: string) {
  return useQuery({
    queryKey: ["t1-forecast", "watchlist", date ?? "latest"],
    // client.ts request 自动解包 payload.data（返 watchlist 非 {status,data} 包装），勿二次取 .data
    queryFn: () => api.t1ForecastWatchlist(date) as Promise<T1Watchlist>,
    staleTime: 5 * 60 * 1000,
  });
}
