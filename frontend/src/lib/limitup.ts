// S029 涨停基因选股 — API client（/limitup/gene GeneScreener 页用）
// 后端端点（S028 后已就绪）：
//   GET  /api/limitup/screener?date=        → ScreenerResult
//   GET  /api/limitup/screener/params        → 阈值参数
//   POST /api/limitup/screener/params         → 持久化阈值
//   POST /api/limitup/screener/trigger        → 手动触发今日预计算（后台异步）
import { request } from "@/lib/api/client";
import type { ScreenerResult } from "@/lib/api";

/** 涨停基因阈值/参数（后端 LimitUpParamsBody）。 */
export interface GeneScreenerParams {
  gene_qualify_threshold: number;
  gene_high_threshold: number;
  lookback_days: number;
}

/** 取指定日期涨停基因得分（客观数据）。date 缺省取最近交易日。 */
export function getGeneScreener(date?: string): Promise<ScreenerResult> {
  const qs = date ? `?date=${encodeURIComponent(date)}` : "";
  return request<ScreenerResult>(`/limitup/screener${qs}`);
}

/** 取当前阈值参数。 */
export function getGeneParams(): Promise<GeneScreenerParams> {
  return request<GeneScreenerParams>("/limitup/screener/params");
}

/** 持久化阈值参数（同时更新后端模块常量，需 trigger 重跑才重算 qualify 标志）。 */
export function saveGeneParams(params: GeneScreenerParams): Promise<{ status: string }> {
  return request<{ status: string }>("/limitup/screener/params", "POST", params);
}

/** 手动触发今日基因得分预计算（后台异步，~90s 内懒算落库）。 */
export function triggerGenePrecompute(): Promise<{ status: string; date: string }> {
  return request<{ status: string; date: string }>("/limitup/screener/trigger", "POST");
}
