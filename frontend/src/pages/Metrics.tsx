import { useState, useEffect } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import { AskAiButton } from "@/components/ui/AskAiButton";

interface TierMetrics {
  tier: string;
  target: number;
  components: Record<string, string>;
  note: string;
  status: string;
}

interface BreakdownResponse {
  tiers: {
    data_fetch: TierMetrics;
    compute: TierMetrics;
    api_response: TierMetrics;
  };
  summary: {
    total_target: number;
    unit: string;
  };
  note: string;
  status: string;
}

export function Metrics() {
  const [breakdown, setBreakdown] = useState<BreakdownResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      api.metricsDataFetch(),
      api.metricsCompute(),
      api.metricsApiResponse(),
      api.metricsBreakdown(),
    ])
      .then(([, , , breakdownData]) => {
        if (cancelled) return;
        setBreakdown(breakdownData);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "加载失败");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <Skeleton className="h-4 w-32" />
      </div>
    );
  }

  if (error || !breakdown) {
    return (
      <EmptyState
        icon={<AlertCircle className="h-8 w-8 text-muted-foreground/40" />}
        title="加载失败"
        description={error ?? "未知错误"}
      />
    );
  }

  const tiers = [
    { key: "data_fetch", label: "数据获取层", icon: "📥", color: "text-blue-400" },
    { key: "compute", label: "计算层", icon: "⚙️", color: "text-primary" },
    { key: "api_response", label: "API 响应层", icon: "📤", color: "text-green-400" },
  ] as const;

  // S066 AskAi：注入性能拆分
  const askAiContext = [
    `当前页面：性能监控（Metrics）`,
    breakdown ? `总目标 ${breakdown.summary.total_target}${breakdown.summary.unit} · 状态${breakdown.status}` : `性能：未取得`,
    breakdown ? `数据获取层：${breakdown.tiers.data_fetch.status}（目标${breakdown.tiers.data_fetch.target}${breakdown.summary.unit}）` : ``,
    breakdown ? `计算层：${breakdown.tiers.compute.status}（目标${breakdown.tiers.compute.target}${breakdown.summary.unit}）` : ``,
    breakdown ? `API响应层：${breakdown.tiers.api_response.status}（目标${breakdown.tiers.api_response.target}${breakdown.summary.unit}）` : ``,
  ].filter(Boolean).join("\n");

  return (
    <div className="space-y-4">
      <PageHeader
        title="性能监控"
        subtitle="系统三层性能拆分指标（目标值参考）"
        actions={<AskAiButton context={askAiContext} />}
      />

      <div className="grid gap-4 md:grid-cols-3">
        {tiers.map((tier) => {
          const data = breakdown.tiers[tier.key];
          return (
            <GlassCard key={tier.key} className="p-4">
              <SectionHeader title={tier.label} subtitle={tier.color} />
              <div className="mb-2 text-2xl font-bold">
                {data.target}
                <span className="ml-1 text-xs text-muted-foreground">{breakdown.summary.unit}</span>
              </div>
              <div className="space-y-1">
                {Object.entries(data.components).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{k}</span>
                    <span className="text-foreground/80">{v}</span>
                  </div>
                ))}
              </div>
              <div className="mt-2 text-[10px] text-muted-foreground/60">{data.note}</div>
            </GlassCard>
          );
        })}
      </div>

      <GlassCard className="p-4">
        <SectionHeader title="汇总" />
        <div className="flex items-center gap-4 text-xs">
          <div>
            总目标耗时：<b>{breakdown.summary.total_target}</b> {breakdown.summary.unit}
          </div>
          <div className="text-muted-foreground/60">{breakdown.note}</div>
        </div>
      </GlassCard>
    </div>
  );
}
