// lib/query/workflow.ts — 工作流状态机 TanStack Query hooks（S033 R4）。
// 状态流转是客观状态记录（用户自填操作），hooks 只搬运数据，不附加方向语义。
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getFirstBoardCandidates,
  getWorkflowState,
  getWorkflowStateHistory,
  getWorkflowStates,
  transitionWorkflowState,
} from "@/lib/api";
import type { Opts } from "./types";
import type {
  FirstBoardCandidatesResponse,
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

// S075 首板流候选池——GET /api/workflow/first-board/candidates?date=
// run_first_board_filter 产出（首板过滤+三层剔除+9维度评分+落盘）。
// §44 诚实标注：9 维度评分未 validated 仅参考；阈值/权重待回测校准。
// date 不传时后端取最近交易日；候选池日内不变，staleTime 5min 防短时重复请求。
export function useFirstBoardCandidates(date?: string, options?: Opts<FirstBoardCandidatesResponse | null>) {
  return useQuery({
    queryKey: ["workflow", "first-board", "candidates", date ?? "latest"] as const,
    queryFn: () => getFirstBoardCandidates(date),
    staleTime: 5 * 60 * 1000,
    ...options,
  });
}
