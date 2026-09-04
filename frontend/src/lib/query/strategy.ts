// lib/query/strategy.ts — 按战法回测 TanStack Query hook（S031 R22）。
// 合规 §0：仅搬运客观回测数据，不附加方向；胜率属历史统计特征。
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import type { Opts } from "./types";

export interface StrategyBacktestItem {
  strategy: string;
  strategy_code: string;
  win_rate: number;
  avg_return: number;
  sample_size: number;
  available_days: number;
  note?: string;  // S051 D5：零样本战法诚实注记（60日无信号原因）
}

/** S031 R22：按战法回测——GET /api/strategy/backtest?lookback_days。
 * request 解包 .data → 返 8 战法真实回测胜率数组（每项含 available_days）。结果 12h 后端缓存。 */
export function useStrategyBacktest(lookback_days = 60, options?: Opts<StrategyBacktestItem[]>) {
  return useQuery({
    queryKey: ["strategy", "backtest", lookback_days] as const,
    queryFn: () => request<StrategyBacktestItem[]>(`/strategy/backtest?lookback_days=${lookback_days}`),
    ...options,
  });
}

/** 合成 confidence_mapped_winrate 公式（strategy_base.py dispatch_match）：min(confidence*0.8+0.2, 0.95)。
 * 供 WinRateComparePanel 右列重算（标注"估算"），与真实回测对比。 */
export function syntheticWinRate(confidence: number): number {
  return Math.min(confidence * 0.8 + 0.2, 0.95);
}

// ===========================================================================
// S066 §3 策略特定漏斗前端 hooks
// ===========================================================================

export interface WeatherStrategyMap {
  weather_strategy_map: Record<string, string[]>;
  weather_recommendation: Record<string, string[]>;
  fallback_strategies: Record<string, string[]>;
}

export interface FunnelStrategyConfig {
  code: string;
  name: string;
  funnel_type: "limitup" | "market_scan";
  weight_set: "limitup" | "non_limitup" | "storm_reversal";
  weather_regimes: string[];
  is_primary: boolean;
  fallback: boolean;
  position_params: {
    stop_loss_pct: number;
    take_profit_pct: number;
    max_hold_days: number;
    position_scale: number;
  };
  quality_standards: { name: string; required: boolean; description: string }[];
  note: string;
  activation_note?: string;  // 激活状态注记，非空表示该战法当前不可用（如"待 S055 激活"）
}

export interface CalendarFactorResult {
  date: string;
  position_multiplier: number;
  reason: string;
}

export interface SectorCycleResult {
  industry: string;
  count_today: number;
  count_avg_3d: number;
  momentum: number;
  phase: string;  // 启动/发酵/高潮/退潮/冷门/无历史
  modifier: number;
  phase_note: string;
}

export interface MarketKillSwitchResult {
  triggered: boolean;
  reason: string;
  sh_change_pct: number | null;
  gem_change_pct: number | null;
}

/** S066 §3.3 天气-策略硬开关映射表。 */
export function useWeatherStrategyMap(options?: Opts<WeatherStrategyMap>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "weather-map"] as const,
    queryFn: () => request<WeatherStrategyMap>("/strategy/funnel/weather-map"),
    staleTime: 300_000,  // 5min（映射表静态）
    ...options,
  });
}

/** S066 §3.2 策略特定漏斗注册表（10 策略）。 */
export function useFunnelStrategies(options?: Opts<FunnelStrategyConfig[]>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "strategies"] as const,
    queryFn: () => request<FunnelStrategyConfig[]>("/strategy/funnel/strategies"),
    staleTime: 300_000,
    ...options,
  });
}

/** S066 §6 日历因子仓位乘数。 */
export function useCalendarFactor(date: string, options?: Opts<CalendarFactorResult>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "calendar-factor", date] as const,
    queryFn: () => request<CalendarFactorResult>(`/strategy/funnel/calendar-factor?date=${date}`),
    staleTime: 600_000,  // 10min（日历因子日内不变）
    ...options,
  });
}

/** S066 §5.4 板块周期分析。 */
export function useSectorCycle(date: string, industry: string, options?: Opts<SectorCycleResult | null>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "sector-cycle", date, industry] as const,
    queryFn: () => request<SectorCycleResult | null>(`/strategy/funnel/sector-cycle?date=${date}&industry=${encodeURIComponent(industry)}`),
    staleTime: 300_000,
    ...options,
  });
}

/** S066 §5.4.1 板块强度排名 TOP10 + §5.4.3 跨板块轮动检测（纯 label）。 */
export interface SectorRotationResult {
  date: string;
  strength_rank: { industry: string; zt_count_today: number; zt_momentum: number; fund_flow: number; rank: number; strength: number; modifier: number }[];
  rotation: { industry: string; prev_rank: number | null; curr_rank: number | null; change: number; signal: string }[];
  fund_flow_blocked: boolean;
  note: string;
}

export function useSectorRotation(date: string | undefined, options?: Opts<SectorRotationResult>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "sector-rotation", date ?? ""] as const,
    queryFn: () => request<SectorRotationResult>(`/strategy/funnel/sector-rotation?date=${date}`),
    enabled: !!date,
    staleTime: 300_000,
    ...options,
  });
}

/** S066 §5.4 概念题材板块强度（纯 label，聚合跨 f100 行业）。 */
export interface ConceptRotationResult {
  date: string;
  concept_rank: { concept: string; zt_count_today: number }[];
  count: number;
  note: string;
}

export function useConceptRotation(date: string | undefined, options?: Opts<ConceptRotationResult>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "concept-rotation", date ?? ""] as const,
    queryFn: () => request<ConceptRotationResult>(`/strategy/funnel/concept-rotation?date=${date}`),
    enabled: !!date,
    staleTime: 300_000,
    ...options,
  });
}

/** S066 §5.4 多维度融合板块强度（行业+题材+概念，纯 label）。 */
export interface MultiRotationResult {
  date: string;
  multi_rank: { label: string; zt_count_today: number; dims: string[]; codes: { code: string; name: string }[] }[];
  multi_dim_rank: { label: string; zt_count_today: number; dims: string[]; codes: { code: string; name: string }[] }[];
  pool_size: number;
  count: number;
  note: string;
}

export function useMultiRotation(date: string | undefined, options?: Opts<MultiRotationResult>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "multi-rotation", date ?? ""] as const,
    queryFn: () => request<MultiRotationResult>(`/strategy/funnel/multi-rotation?date=${date}`),
    enabled: !!date,
    staleTime: 300_000,
    ...options,
  });
}

export function useNonLimitupFunnel(date: string | undefined, options?: Opts<NonLimitupFunnelResult>) {
  return useQuery({
    queryKey: ["strategy", "non-limitup-funnel", date ?? ""] as const,
    queryFn: () => request<NonLimitupFunnelResult>(`/strategy/non-limitup-funnel?date=${date}`),
    enabled: !!date,
    staleTime: 300_000,
    ...options,
  });
}

export interface NonLimitupFunnelResult {
  candidates: { code: string; name?: string; strategy_code?: string; strategy_score?: number; sector?: string }[];
  count: number;
  sectors_scanned: number;
  candidates_input: number;
  note: string;
}

/** S066 §16.4 市场级熔断检查。 */
export function useMarketKillSwitch(options?: Opts<MarketKillSwitchResult>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "market-kill-switch"] as const,
    queryFn: () => request<MarketKillSwitchResult>("/strategy/funnel/market-kill-switch"),
    refetchInterval: 300_000,  // 5min 轮询（盘中同步情绪采样）
    ...options,
  });
}

// ===========================================================================
// S066 Phase 0e 前向测试（paper trading）
// ===========================================================================

export interface ForwardTestSummary {
  total_days: number;
  total_recommendations: number;
  settled_count: number;
  win_count: number;
  win_rate: number;
  avg_return: number;
  benchmark_win_rate: number;
  pass_threshold: number;
  passed: boolean;
  consecutive_loss: number;
  random_baseline_win_rate: number;
  random_settled: number;
  lift: number;
  is_exploratory: boolean;
  note: string;
  validation_status?: string;  // §44 60日复验窗口三态：validated | 未 validated | 探索性
}

export interface ForwardTestRecord {
  signal_date: string;
  code: string;
  name: string;
  strategy_code: string;
  strategy_score: number;
  weather_state: string | null;
  position_multiplier: number;
  recommended_position: number;
  return_open2close: number | null;
  return_close2close: number | null;
  next_pctChg: number | null;
  is_win: number;
}

/** S066 §0e 前向测试汇总（通过/不通过判定）。 */
export function useForwardTestSummary(options?: Opts<ForwardTestSummary>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "forward-test", "summary"] as const,
    queryFn: () => request<ForwardTestSummary>("/strategy/funnel/forward-test"),
    staleTime: 300_000,  // 5min（日级数据，无需高频刷新）
    ...options,
  });
}

/** S066 §0e 某信号日前向测试推荐明细。 */
export function useForwardTestDaily(signalDate: string, options?: Opts<ForwardTestRecord[]>) {
  return useQuery({
    queryKey: ["strategy", "funnel", "forward-test", "daily", signalDate] as const,
    queryFn: () => request<ForwardTestRecord[]>(`/strategy/funnel/forward-test/${signalDate}`),
    staleTime: 300_000,
    ...options,
  });
}
