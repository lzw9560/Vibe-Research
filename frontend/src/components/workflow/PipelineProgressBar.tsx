// S063 T25：PipelineProgressBar——盘前/盘中/盘后页顶部 5 节点进度条。
// 5 节点：T-1 → Ctx → 盘前 → 盘中 → 盘后；当前阶段脉冲高亮。
import { cn } from "@/lib/utils";

type Stage = "t1" | "ctx" | "pre" | "intraday" | "post";

const STAGES: { key: Stage; label: string }[] = [
  { key: "t1", label: "T-1 计算" },
  { key: "ctx", label: "情绪上下文" },
  { key: "pre", label: "盘前简报" },
  { key: "intraday", label: "盘中辅助" },
  { key: "post", label: "盘后结算" },
];

interface Props {
  current: Stage;
}

export function PipelineProgressBar({ current }: Props) {
  const currentIdx = STAGES.findIndex((s) => s.key === current);

  return (
    <div className="flex items-center gap-1">
      {STAGES.map((s, i) => {
        const isCurrent = s.key === current;
        const isDone = i < currentIdx;
        return (
          <div key={s.key} className="flex flex-1 items-center">
            <div className="flex flex-col items-center gap-1">
              <div
                className={cn(
                  "flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold",
                  isCurrent && "bg-primary text-primary-foreground animate-pulse",
                  isDone && "bg-primary/60 text-primary-foreground",
                  !isCurrent && !isDone && "bg-muted/40 text-muted-foreground",
                )}
              >
                {i + 1}
              </div>
              <span
                className={cn(
                  "text-[10px]",
                  isCurrent ? "font-semibold text-foreground" : "text-muted-foreground",
                )}
              >
                {s.label}
              </span>
            </div>
            {i < STAGES.length - 1 && (
              <div
                className={cn(
                  "mx-1 h-0.5 flex-1",
                  i < currentIdx ? "bg-primary/60" : "bg-muted/30",
                )}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

export type { Stage as PipelineStage };
