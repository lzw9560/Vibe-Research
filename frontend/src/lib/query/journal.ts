// S166: 交易日志 + 风险账本 TanStack Query hooks（仿 verifier.ts 范式）。
// contract-first：journal-contract.ts 为 source-of-truth。
// 后端未就绪 → ApiError，组件降级"后端未就绪"诚实横幅（不臆造 mock 数据——
// 交易日志是个人真实数据，showing 假交易比"后端没起"更坏，§44 诚实 + journal 不臆造）。
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";
import type {
  TradeListResponse, StatsResponse, RiskReportResponse, AtRiskReport,
  ExcursionSummary, AttributionResponse, InboxResponse, RiskRules, Fees,
  EquityBaseResponse, AddTradeInput, AddTradeResponse, UpdateTradeInput,
  UpdateTradeResponse, DeleteTradeResponse, SaveFeesInput, SaveFeesResponse,
  SaveRulesInput, SaveRulesResponse, SaveEquityBaseInput, SaveEquityBaseResponse,
} from "@/lib/journal-contract";

// 5min staleTime——journal 数据变更不频繁；改 rules/equity_base 会显式 invalidate 依赖 query。
const JOURNAL_STALE_MS = 5 * 60 * 1000;

// ─── 查询（变更不频繁，5min stale；excursion 首次慢逐笔拉行情缓存） ───
export function useJournalTrades(limit = 200, options?: Opts<TradeListResponse>) {
  return useQuery({
    queryKey: ["journal", "trades", limit] as const,
    queryFn: () => api.journalList(limit),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useJournalStats(options?: Opts<StatsResponse>) {
  return useQuery({
    queryKey: ["journal", "stats"] as const,
    queryFn: () => api.journalStats(),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useJournalFees(options?: Opts<Fees>) {
  return useQuery({
    queryKey: ["journal", "fees"] as const,
    queryFn: () => api.journalFees(),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useRiskReport(options?: Opts<RiskReportResponse>) {
  return useQuery({
    queryKey: ["journal", "risk-report"] as const,
    queryFn: () => api.riskReport(),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useAtRisk(options?: Opts<AtRiskReport>) {
  return useQuery({
    queryKey: ["journal", "at-risk"] as const,
    queryFn: () => api.riskAtRisk(),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useExcursion(limit = 300, options?: Opts<ExcursionSummary>) {
  return useQuery({
    queryKey: ["journal", "excursion", limit] as const,
    queryFn: () => api.riskExcursion(limit),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useAttribution(limit = 500, options?: Opts<AttributionResponse>) {
  return useQuery({
    queryKey: ["journal", "attribution", limit] as const,
    queryFn: () => api.riskAttribution(limit),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useInbox(limit = 500, options?: Opts<InboxResponse>) {
  return useQuery({
    queryKey: ["journal", "inbox", limit] as const,
    queryFn: () => api.riskInbox(limit),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useRiskRules(options?: Opts<RiskRules>) {
  return useQuery({
    queryKey: ["journal", "rules"] as const,
    queryFn: () => api.riskRules(),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}
export function useEquityBase(options?: Opts<EquityBaseResponse>) {
  return useQuery({
    queryKey: ["journal", "equity-base"] as const,
    queryFn: () => api.riskEquityBase(),
    staleTime: JOURNAL_STALE_MS,
    ...options,
  });
}

// ─── 变更（成功后 invalidate 相关 query；写 trade 影响 stats/risk/at-risk/inbox 全链） ───
export function useAddTrade() {
  const qc = useQueryClient();
  return useMutation<AddTradeResponse, Error, AddTradeInput>({
    mutationFn: (body) => api.journalAdd(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }),
  });
}
export function useUpdateTrade() {
  const qc = useQueryClient();
  return useMutation<UpdateTradeResponse, Error, { tradeId: string; body: UpdateTradeInput }>({
    mutationFn: ({ tradeId, body }) => api.journalUpdate(tradeId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }),
  });
}
export function useDeleteTrade() {
  const qc = useQueryClient();
  return useMutation<DeleteTradeResponse, Error, string>({
    mutationFn: (tradeId) => api.journalDelete(tradeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }),
  });
}
export function useSaveFees() {
  const qc = useQueryClient();
  return useMutation<SaveFeesResponse, Error, SaveFeesInput>({
    mutationFn: (body) => api.journalSaveFees(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal", "fees"] }),
  });
}
export function useSaveRules() {
  const qc = useQueryClient();
  return useMutation<SaveRulesResponse, Error, SaveRulesInput>({
    mutationFn: (body) => api.riskSaveRules(body),
    // rules 影响 at-risk（load_rules 算超限）+ risk-report（violations）+ inbox（load_rules）——全 invalidate
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }),
  });
}
export function useSaveEquityBase() {
  const qc = useQueryClient();
  return useMutation<SaveEquityBaseResponse, Error, SaveEquityBaseInput>({
    mutationFn: (body) => api.riskSaveEquityBase(body.base),
    // equity_base 影响 at-risk（占比分母）+ risk-report（violations 单日亏损占比）——全 invalidate
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journal"] }),
  });
}
