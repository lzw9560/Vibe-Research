import { cn } from "@/lib/utils";
import { GlassCard } from "@/components/ui/GlassCard";

interface SkeletonProps {
  className?: string;
  variant?: "text" | "circular" | "rectangular";
}

export function Skeleton({ className, variant = "text" }: SkeletonProps) {
  const variants = {
    text: "h-4 w-full rounded bg-muted/20 animate-pulse",
    circular: "h-10 w-10 rounded-full bg-muted/20 animate-pulse",
    rectangular: "h-20 w-full rounded-lg bg-muted/20 animate-pulse",
  };

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

export function SkeletonTable({ rows = 5 }: { rows?: number }) {
  return (
    <div className="w-full space-y-2">
      {/* Header */}
      <div className="flex gap-4 border-b border-border/50 bg-muted/20 px-4 py-2.5">
        <Skeleton variant="text" className="w-8" />
        <Skeleton variant="text" className="w-16" />
        <Skeleton variant="text" className="flex-1" />
        <Skeleton variant="text" className="w-20" />
      </div>
      {/* Rows */}
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex gap-4 border-b border-border/20 px-4 py-2.5">
          <Skeleton variant="text" className="w-8" />
          <Skeleton variant="text" className="w-16" />
          <Skeleton variant="text" className="flex-1" />
          <Skeleton variant="text" className="w-20" />
        </div>
      ))}
    </div>
  );
}
