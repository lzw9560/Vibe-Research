// S063 T25：状态机看板——盘中页 6 态计数 + 今日流转记录。
// 读 workflow_state_repo（通过 useWorkflowStates）。
import { useWorkflowStates } from "@/lib/query";
import { cn } from "@/lib/utils";
import { STATUS_COLORS, STATUS_LABELS } from "@/components/workflow/statusMeta";

const ORDER = ["pending", "candidate", "watching", "monitoring", "holding", "settled", "filtered"] as const;

export function StateMachineDashboard({ date }: { date?: string }) {
  const { data } = useWorkflowStates(date);
  const counts = data?.counts ?? {};

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">状态机看板</p>
      <div className="grid grid-cols-4 gap-2 lg:grid-cols-7">
        {ORDER.map((status) => {
          const count = (counts as Record<string, number>)[status] ?? 0;
          return (
            <div
              key={status}
              className="rounded-lg border border-border/40 p-2 text-center"
            >
              <div className={cn("mx-auto mb-1 h-2 w-2 rounded-full", STATUS_COLORS[status])} />
              <p className="text-[10px] text-muted-foreground">{STATUS_LABELS[status]}</p>
              <p className="text-lg font-bold">{count}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
