// lib/query/journal.ts — S149 P3 交易日志 + 个人风控 TanStack Query hooks。
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getJournalList, getJournalStats, addJournalTrade, updateJournalTrade,
  deleteJournalTrade, getJournalFees, saveJournalFees,
  getRiskReport, getAtRisk, getRiskRules, saveRiskRules,
  getEquityBase, setEquityBase, getExcursionSummary, getAttribution, getInbox,
} from "@/lib/journal";
import type { Opts } from "./types";

const QK = ["journal"] as const;

export function useJournalList(limit = 200, options?: Opts<Awaited<ReturnType<typeof getJournalList>>>) {
  return useQuery({
    queryKey: [...QK, "list", limit] as const,
    queryFn: () => getJournalList(limit),
    ...options,
  });
}
export function useJournalStats(options?: Opts<Awaited<ReturnType<typeof getJournalStats>>>) {
  return useQuery({ queryKey: [...QK, "stats"] as const, queryFn: () => getJournalStats(), ...options });
}
export function useJournalFees(options?: Opts<Awaited<ReturnType<typeof getJournalFees>>>) {
  return useQuery({ queryKey: [...QK, "fees"] as const, queryFn: () => getJournalFees(), ...options });
}

// 写 hook：成功后失效 journal 查询前缀
export function useAddTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof addJournalTrade>[0]) => addJournalTrade(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}
export function useUpdateTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ tradeId, body }: { tradeId: string; body: Parameters<typeof updateJournalTrade>[1] }) =>
      updateJournalTrade(tradeId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}
export function useDeleteTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tradeId: string) => deleteJournalTrade(tradeId),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK }),
  });
}
export function useSaveFees() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof saveJournalFees>[0]) => saveJournalFees(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...QK, "fees"] }),
  });
}

// ── 个人风控只读 ──
export function useRiskReport(options?: Opts<Awaited<ReturnType<typeof getRiskReport>>>) {
  return useQuery({ queryKey: [...QK, "risk", "report"] as const, queryFn: () => getRiskReport(), ...options });
}
export function useAtRisk(options?: Opts<Awaited<ReturnType<typeof getAtRisk>>>) {
  return useQuery({ queryKey: [...QK, "risk", "at-risk"] as const, queryFn: () => getAtRisk(), ...options });
}
export function useRiskRules(options?: Opts<Awaited<ReturnType<typeof getRiskRules>>>) {
  return useQuery({ queryKey: [...QK, "risk", "rules"] as const, queryFn: () => getRiskRules(), ...options });
}
export function useSaveRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof saveRiskRules>[0]) => saveRiskRules(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...QK, "risk", "rules"] }),
  });
}
export function useEquityBase(options?: Opts<Awaited<ReturnType<typeof getEquityBase>>>) {
  return useQuery({ queryKey: [...QK, "risk", "equity-base"] as const, queryFn: () => getEquityBase(), ...options });
}
export function useSetEquityBase() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (base: number) => setEquityBase(base),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...QK, "risk", "equity-base"] }),
  });
}
export function useExcursionSummary(limit = 300, options?: Opts<Awaited<ReturnType<typeof getExcursionSummary>>>) {
  return useQuery({
    queryKey: [...QK, "risk", "excursion", limit] as const,
    queryFn: () => getExcursionSummary(limit),
    ...options,
  });
}
export function useAttribution(limit = 500, options?: Opts<Awaited<ReturnType<typeof getAttribution>>>) {
  return useQuery({ queryKey: [...QK, "risk", "attribution", limit] as const, queryFn: () => getAttribution(limit), ...options });
}
export function useInbox(limit = 500, options?: Opts<Awaited<ReturnType<typeof getInbox>>>) {
  return useQuery({ queryKey: [...QK, "risk", "inbox", limit] as const, queryFn: () => getInbox(limit), ...options });
}
