// lib/query/scheduledTasks.ts — S092 T7：盘后任务状态 TanStack Query hook。
// 过渡窗（stage === "post_transition"）启用 + 60s 轮询；其他时段不查询不轮询。
// 后端 GET /api/scheduled-tasks 每项返回 today_status（done|error|running|pending），R18 后端算不前端算。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export interface ScheduledTaskStatus {
  id: number;
  name: string;
  cron_expr: string;
  last_run_at: string | null;
  last_run_status: string | null;
  today_status: "done" | "error" | "running" | "pending";
  task_type: string;
  enabled: boolean;
}

/**
 * 盘后任务状态查询。
 * @param enabled 是否启用查询——仅过渡窗（stage === "post_transition"）传 true
 * 过渡窗 60s 轮询；enabled=false 时不查询不轮询（react-query enabled 门控）。
 * api.scheduledTasks() 返 any[]（api.ts 未加类型），在此 cast 为 ScheduledTaskStatus[]。
 */
export function useScheduledTasksStatus(enabled: boolean) {
  return useQuery({
    queryKey: ["scheduled-tasks", "status"] as const,
    queryFn: async () => {
      const data = await api.scheduledTasks();
      return (data ?? []) as ScheduledTaskStatus[];
    },
    refetchInterval: enabled ? 60_000 : false,
    enabled,
  });
}
