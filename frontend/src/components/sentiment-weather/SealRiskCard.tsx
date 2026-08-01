import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import type { SealRiskMetric } from "@/lib/api";

interface SealRiskCardProps {
  metrics: SealRiskMetric[];
}

export function SealRiskCard({ metrics }: SealRiskCardProps) {
  return (
    <GlassCard glow className="p-6">
      <h3 className="text-lg font-semibold mb-4">封单风险监控</h3>

      <div className="space-y-4">
        {metrics.map((metric) => (
          <div key={metric.stock_code} className="p-4 rounded-lg bg-white/5 border border-white/10">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm">{metric.stock_code}</span>
                <Badge
                  variant={
                    metric.risk_level === "low"
                      ? "success"
                      : metric.risk_level === "medium"
                      ? "warning"
                      : "danger"
                  }
                >
                  {metric.risk_level === "low" ? "低风险" : metric.risk_level === "medium" ? "中风险" : "高风险"}
                </Badge>
              </div>
              <Badge variant="default">{metric.cap_category}</Badge>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <p className="text-white/60">封单额</p>
                <p className="font-medium tabular-nums">{(metric.seal_amount / 10000).toFixed(0)}万</p>
              </div>
              <div>
                <p className="text-white/60">流通盘</p>
                <p className="font-medium tabular-nums">{(metric.float_shares / 100000000).toFixed(2)}亿股</p>
              </div>
              <div>
                <p className="text-white/60">封单比例</p>
                <p className="font-medium tabular-nums">{(metric.seal_ratio * 100).toFixed(2)}%</p>
              </div>
              <div>
                <p className="text-white/60">最低要求</p>
                <p className="font-medium tabular-nums">{(metric.min_ratio_required * 100).toFixed(2)}%</p>
              </div>
            </div>

            <div className="mt-3 p-2 rounded bg-black/20">
              <p className="text-xs text-white/70">
                <span className="text-white/50">执行动作:</span> {metric.enforcement_action}
              </p>
              <p className="text-xs text-white/50 mt-1">{metric.reason}</p>
            </div>
          </div>
        ))}
      </div>
    </GlassCard>
  );
}
