// CTA 脊：每页底部"下一步"导航栏，串起 5 线闭环。
// 今日(时间)→盘面(选股)→记日志→/ledger→收盘复盘→/review→调参→/workspace ←LOOP
// 认知→反哺策略→验证; 数据→任务健康→今日
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
    { label: "认知图谱", to: "/graph", reason: "M7 公告→新信号，反哺策略" },
    { label: "明日盘面", to: "/today", reason: "调参完毕，明日盘面见" },
  ],
  cognition: [
    { label: "反哺策略", to: "/review?tab=strategy", reason: "M7 新认知→反哺策略调战法", primary: true },
    { label: "验证新信号", to: "/review?tab=validation", reason: "新信号→§44 验证" },
  ],
  data: [
    { label: "任务健康", to: "/pipeline", reason: "数据采集任务状态详情", primary: true },
    { label: "今日盘面", to: "/today", reason: "数据就绪，回今日看动作" },
  ],
  "quant-models": [
    { label: "OFI 看板", to: "/workflow/intraday/ofi", reason: "M1 已实现的盘中 OFI 只读看板", primary: true },
    { label: "认知图谱", to: "/graph", reason: "M7 LLM 图谱 home（注入流 spec-only）" },
    { label: "回今日", to: "/today", reason: "回今日盘面动作队列" },
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
