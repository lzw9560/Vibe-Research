import { cn } from "@/lib/utils";
import { GlassCard } from "./GlassCard";

interface SkeletonProps {
  className?: string;
  variant?: "text" | "circular" | "rectangular" | "rounded";
  lines?: number;
}

export function Skeleton({ className, variant = "text", lines = 1 }: SkeletonProps) {
  const variants = {
    text: "h-4 w-full rounded bg-muted/20 animate-pulse",
    circular: "h-10 w-10 rounded-full bg-muted/20 animate-pulse",
    rectangular: "h-20 w-full rounded-lg bg-muted/20 animate-pulse",
    rounded: "h-24 w-full rounded-xl bg-muted/20 animate-pulse",
  };

  if (lines > 1) {
    return (
      <div className={cn("space-y-2", className)}>
        {Array.from({ length: lines }).map((_, i) => (
          <div key={i} className={cn(variants[variant], i === lines - 1 && "w-4/5")} />
        ))}
      </div>
    );
  }

  return <div className={cn(variants[variant], className)} />;
}

export function SkeletonCard() {
  return (
    <GlassCard className="mb-6">
      <div className="space-y-3">
        <Skeleton variant="text" className="w-1/3" />
        <Skeleton variant="rectangular" />
        <div className="flex gap-2">
          <Skeleton variant="text" className="w-1/4" />
          <Skeleton variant="text" className="w-1/4" />
        </div>
      </div>
    </GlassCard>
  );
}

export function SkeletonTable({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <GlassCard>
      <div className="w-full">
        {/* Header */}
        <div className="flex gap-4 border-b border-border/50 bg-muted/20 px-4 py-2.5">
          {Array.from({ length: columns }).map((_, i) => (
            <Skeleton key={i} variant="text" className="w-16" />
          ))}
        </div>
        {/* Rows */}
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex gap-4 border-b border-border/20 px-4 py-2.5 last:border-0">
            {Array.from({ length: columns }).map((_, j) => (
              <Skeleton key={j} variant="text" className="w-16" />
            ))}
          </div>
        ))}
      </div>
    </GlassCard>
  );
}

export function SkeletonMetrics({ count = 4 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {Array.from({ length: count }).map((_, i) => (
        <GlassCard key={i} className="p-3">
          <Skeleton variant="text" className="w-12 mb-2" />
          <Skeleton variant="text" className="w-16 h-6" />
        </GlassCard>
      ))}
    </div>
  );
}
