import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import type { AuctionMetric } from "@/lib/api";

interface AuctionMetricsCardProps {
  metrics: AuctionMetric[];
  phase: string;
}

export function AuctionMetricsCard({ metrics, phase }: AuctionMetricsCardProps) {
  const phaseLabel = phase === "competitive" ? "9:20-9:25 不可撤单阶段" : "9:15-9:20 可撤单阶段";

  return (
    <GlassCard glow className="p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">竞价阶段监控</h3>
        <Badge variant={phase === "competitive" ? "warning" : "default"}>
          {phaseLabel}
        </Badge>
      </div>

      <div className="space-y-4">
        {metrics.map((metric) => (
          <div key={metric.name} className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{metric.name}</span>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold tabular-nums w-20 text-right">
                  {metric.value.toLocaleString()} {metric.unit}
                </span>
                {metric.is_warning && (
                  <Badge variant="warning">阈值</Badge>
                )}
              </div>
            </div>
            <div className="h-2 rounded-full bg-white/10 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all duration-500 ${
                  metric.is_warning
                    ? "bg-gradient-to-r from-yellow-500 to-red-500"
                    : "bg-gradient-to-r from-blue-500 via-green-500 to-yellow-500"
                }`}
                style={{
                  width: `${Math.min(100, Math.max(0, (metric.value / metric.threshold_high) * 100))}%`,
                }}
              />
            </div>
            <div className="flex justify-between text-xs text-white/50">
              <span>低阈值: {metric.threshold_low.toLocaleString()}</span>
              <span>高阈值: {metric.threshold_high.toLocaleString()}</span>
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}
