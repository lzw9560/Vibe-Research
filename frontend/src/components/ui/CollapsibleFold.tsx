// S092：可折叠容器——内嵌补全 S087 丢失内容（T-1/语境/战法匹配/战法战绩/盘后入口）。
// 参照 S087 StepSection 风格，但无 index 序号，更轻量。
import { useState, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { GlassCard } from "./GlassCard";
import { cn } from "@/lib/utils";

interface Props {
  title: string;
  subtitle?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}

export function CollapsibleFold({ title, subtitle, children, defaultOpen = false }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <GlassCard className="mb-3 p-3">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 text-left">
        <h3 className="text-sm font-semibold">{title}</h3>
        {subtitle && <span className="text-xs text-muted-foreground/60">{subtitle}</span>}
        <ChevronRight className={cn("ml-auto h-4 w-4 transition-transform", open && "rotate-90")} />
      </button>
      {open && <div className="mt-3 space-y-3">{children}</div>}
    </GlassCard>
  );
}
