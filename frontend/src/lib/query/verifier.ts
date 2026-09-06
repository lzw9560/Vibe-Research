// S165: §44 verifier + evaluation dims TanStack Query hooks（仿 limitup.ts 范式）。
// contract-first：verifier-contract.ts 为 source-of-truth，后端按 schema 实现。
// 后端未就绪 → ApiError，组件降级 mock fixture + "mock" 徽标（honest transition）。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";
import type { RecorderRecord, DimensionValidationRecord } from "@/lib/verifier-contract";

// 实验记录（RecorderRecord[]）——验证实验追踪，变更不频繁，5min stale。
export function useVerifierRecords(options?: Opts<RecorderRecord[]>) {
  return useQuery({
    queryKey: ["verifier", "records"] as const,
    queryFn: () => api.verifierRecords(),
    staleTime: 5 * 60_000,
    ...options,
  });
}

// 评价层维度（DimensionValidationRecord[]）——§44 12 维 verdict，变更不频繁，5min stale。
export function useEvaluationDims(options?: Opts<DimensionValidationRecord[]>) {
  return useQuery({
    queryKey: ["evaluation", "dims"] as const,
    queryFn: () => api.evaluationDims(),
    staleTime: 5 * 60_000,
    ...options,
  });
}
