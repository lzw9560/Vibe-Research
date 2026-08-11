// lib/query/workflow.ts — 工作流状态机 TanStack Query hooks（S033 R4）。
// 状态流转是客观状态记录（用户自填操作），hooks 只搬运数据，不附加方向语义。
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getWorkflowState,
  getWorkflowStateHistory,
  getWorkflowStates,
  transitionWorkflowState,
} from "@/lib/api";
import type { Opts } from "./types";
import type {
  TransitionRequest,
  WorkflowState,
  WorkflowStateHistoryItem,
  WorkflowStateList,
} from "@/lib/api";

/** 全日状态列表 + 按态计数。列表徽标用：一次取全量再前端 Map filter，不逐行调 hook。 */
export function useWorkflowStates(date?: string, options?: Opts<WorkflowStateList | null>) {
  return useQuery({
    queryKey: ["workflow", "state", date] as const,
    queryFn: () => getWorkflowStates(date),
    enabled: !!date,
    ...options,
  });
}

/** 单股状态 + allowed_targets（无记录返 null）。抽屉状态卡用。 */
export function useWorkflowState(code: string, date?: string, options?: Opts<WorkflowState | null>) {
  return useQuery({
    queryKey: ["workflow", "state", code, date] as const,
    queryFn: () => getWorkflowState(code, date),
    enabled: !!code,
    ...options,
  });
}

/** 手动流转 mutation。成功后 invalidate ["workflow","state"] + ["winrate"] 前缀——
 * 列表/单股/history 三类 query key 同前缀，一并刷新；winrate 前缀刷新三问区/影子对照。 */
export function useTransitionWorkflowState() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: TransitionRequest) => transitionWorkflowState(req),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["workflow", "state"] });
      void qc.invalidateQueries({ queryKey: ["winrate"] });
    },
  });
}

/** 流转历史（升序；渲染侧倒序呈现）。 */
export function useWorkflowStateHistory(
  code: string,
  date?: string,
  options?: Opts<WorkflowStateHistoryItem[] | null>,
) {
  return useQuery({
    queryKey: ["workflow", "state", code, "history", date] as const,
    queryFn: () => getWorkflowStateHistory(code, date),
    enabled: !!code,
    ...options,
  });
}
