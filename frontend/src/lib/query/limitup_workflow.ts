// lib/query/limitup_workflow.ts — S233 打板工作流 hook。
// 5 Stage 闭环：watchlist → 二次确认 → open 买 → -3% stop/close 卖 → 回填归因。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface WorkflowStage {
  stage: number;
  name: string;
  time: string;
  desc: string;
  status: "done" | "pending" | "manual" | "waiting_t1";
}

export interface ConfirmedStock {
  code: string;
  turn: number;
  vr5: number;
  pctChg: number | null;
  close: number | null;
  gap: number | null;
  confirmed: boolean;
  entry_price: number;
  stop_price: number;
  exit_rule: string;
}

export interface LimitupWorkflow {
  date: string;
  t1_date: string | null;
  signal: string;
  signal_lift: number;
  edge_status: string;
  honest_caveat: string;
  workflow_stages: WorkflowStage[];
  watchlist_count: number;
  confirmed_count: number;
  confirmed_stocks: ConfirmedStock[];
  exit_rules: {
    gap_range: string;
    stop: string;
    entry: string;
    exit: string;
    oos_ev: string;
  };
  operation_steps: string[];
}

export function useLimitupWorkflow(date?: string) {
  return useQuery({
    queryKey: ["limitup-workflow", date ?? "latest"],
    queryFn: () => api.limitupWorkflow(date) as unknown as Promise<LimitupWorkflow>,
    staleTime: 5 * 60 * 1000,
  });
}
