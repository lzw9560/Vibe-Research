// S140 R4：pipeline 共享图元单一来源。
// NODE / ArrowDown / FunnelShrinkBar 原三文件（FirstBoardPipeline / SelectionPipeline /
// NonLimitupPlaceholder）各抄一遍，此处集中导出。NonLimitupPlaceholder 的 NODE 是不同
// class 的本地常量（命名碰撞），不在此导出——该文件仅引 ArrowDown。

/** 节点基础样式（实线）。虚线/颜色态由调用方 cn 叠加 NODE_DASHED/NODE_GREEN 等（各文件本地定义）。 */
export const NODE = "rounded-lg border border-border/40 bg-card/40 p-3";

/** 节点间向下箭头，可选 label。 */
export function ArrowDown({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center py-0.5">
      <div className="h-2 w-px bg-border/40" />
      <span className="text-[9px] text-border/50 leading-none">▼</span>
      {label && <span className="text-[10px] text-muted-foreground">{label}</span>}
    </div>
  );
}

/** 漏斗收缩条：input→output 收敛可视化。 */
export function FunnelShrinkBar({ input, output }: { input: number; output: number }) {
  const ratio = input > 0 ? Math.max(output / input, 0.12) : 0.12;
  return (
    <div className="flex items-center gap-1.5 px-1">
      <div className="h-1.5 flex-1 rounded bg-muted/30" />
      <div className="h-1.5 rounded bg-primary/40" style={{ width: `${ratio * 100}%` }} />
      <span className="text-[10px] text-muted-foreground">{input}→{output}</span>
    </div>
  );
}
