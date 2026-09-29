// lib/query/discipline_gate.ts — S231 打板纪律门禁 TanStack Query hooks。
// 风控工具非 edge 基建。cap=0 terminal BLOCK + C1-C7 7 条件。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Opts } from "./types";

export interface DisciplineCondition {
  id: string;
  name: string;
  value: unknown;
  threshold: unknown;
  pass: boolean;
  red_line?: boolean;
  missing?: boolean;
  notify_level?: boolean;
}

export interface DisciplineVerdict {
  date: string;
  status: "BLOCK" | "CAUTION" | "PASS";
  cap: number;
  terminal: boolean;
  conditions: DisciplineCondition[];
  merged_light: "red" | "yellow" | "green";
  reasons: string[];
}

export function useDisciplineGateVerdict(date?: string, options?: Opts<Awaited<ReturnType<typeof api.disciplineGateVerdict>>>) {
  return useQuery({
    queryKey: ["discipline-gate", "verdict", date ?? "latest"] as const,
    queryFn: () => api.disciplineGateVerdict(date),
    ...options,
  });
}
