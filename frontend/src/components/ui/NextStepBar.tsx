// CTA 脊：每页底部"下一步"导航栏，串起 4 主入口闭环。
// 今日→盘面(盘前)→9:25切盘中→盘面(盘中)→记日志→/ledger→收盘复盘→/review→调漏斗参→/workspace ←LOOP
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface NextStep {
  label: string;
  to: string;
  reason?: string;
  primary?: boolean;
}

const PAGE_STEPS: Record<string, NextStep[]> = {
  today: [
    { label: "盘前选股", to: "/workspace?phase=premarket", reason: "盘前候选就绪，切盘面选股", primary: true },
    { label: "盘中盯盘", to: "/workspace?phase=intraday", reason: "9:25 竞价结束切盘中" },
  ],
  workspace: [
    { label: "记日志", to: "/ledger?tab=journal", reason: "信号触发，记日志待 §44 复验", primary: true },
    { label: "持仓日志", to: "/ledger", reason: "查看持仓+日志" },
  ],
  ledger: [
    { label: "收盘复盘", to: "/review", reason: "收盘查今日战绩+ §44 verdict", primary: true },
  ],
  review: [
    { label: "调漏斗参", to: "/workspace?phase=premarket", reason: "复盘出结论，回盘面调漏斗参数", primary: true },
    { label: "明日盘面", to: "/today", reason: "调参完毕，明日盘面见" },
  ],
};

export function NextStepBar({ pageCtx }: { pageCtx: keyof typeof PAGE_STEPS }) {
  const steps = PAGE_STEPS[pageCtx] ?? [];

  if (steps.length === 0) return null;

  return (
    <div className="mt-6 flex flex-wrap items-center gap-3 border-t border-border/50 pt-4">
      <span className="text-xs text-muted-foreground">下一步</span>
      {steps.map((step) => (
        <Link
          key={step.to + step.label}
          to={step.to}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors",
            step.primary
              ? "bg-primary text-primary-foreground hover:opacity-90"
              : "border border-border bg-muted/40 text-foreground hover:bg-muted/60",
          )}
        >
          {step.label}
          <ArrowRight className="h-3.5 w-3.5" />
          {step.reason && (
            <span className={cn("text-xs font-normal", step.primary ? "text-primary-foreground/80" : "text-muted-foreground")}>
              · {step.reason}
            </span>
          )}
        </Link>
      ))}
    </div>
  );
}
