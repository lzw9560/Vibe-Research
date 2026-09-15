// 多维度 IA: 线闭环卡——展示"怎么走完一圈"（每线的步骤环）
// 5 线各自定义步骤环，当前步骤高亮，箭头串起闭环
import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { GlassCard } from "@/components/ui/GlassCard";

export interface LoopStep {
  label: string;
  link?: string;
  active?: boolean;
}

export interface LineLoopCardProps {
  title: string;
  subtitle?: string;
  steps: LoopStep[];
  /** 当前步骤序号（0-based），高亮该步 */
  currentStep?: number;
  icon?: ReactNode;
  className?: string;
}

export function LineLoopCard({
  title,
  subtitle,
  steps,
  currentStep,
  icon,
  className,
}: LineLoopCardProps) {
  return (
    <GlassCard tier="sub" className={className}>
      <div className="mb-2 flex items-center gap-2">
        {icon}
        <div>
          <h3 className="text-xs font-semibold">{title}</h3>
          {subtitle && <p className="text-[10px] text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {/* 步骤环——横向流，末尾箭头回指表闭环 */}
      <div className="flex flex-wrap items-center gap-1">
        {steps.map((step, i) => {
          const isActive = currentStep === i;
          const content = (
            <span
              className={cn(
                "inline-flex items-center gap-0.5 rounded px-2 py-1 text-[11px] transition-colors",
                isActive
                  ? "bg-primary/15 font-medium text-primary"
                  : "text-muted-foreground hover:bg-muted/30",
              )}
            >
              {step.label}
            </span>
          );
          return (
            <span key={i} className="inline-flex items-center gap-0.5">
              {step.link ? <Link to={step.link}>{content}</Link> : content}
              {i < steps.length - 1 && (
                <ArrowRight className="h-2.5 w-2.5 shrink-0 text-muted-foreground" />
              )}
              {i === steps.length - 1 && (
                <ArrowRight className="h-2.5 w-2.5 shrink-0 text-muted-foreground rotate-180" />
              )}
            </span>
          );
        })}
      </div>
    </GlassCard>
  );
}
