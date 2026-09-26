import { useState, useEffect } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { AlertCircle } from "lucide-react";
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
  const [breakdown] = useState<BreakdownResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // metrics router 已删（2026-09-25 commit 23056de）——4 端点全死 fetch（v5 H1 漏修，本会话补）
  // 改 honest empty：页面保留但无数据源，未来恢复 metrics router 再接线
  useEffect(() => {
    setLoading(false);
    setError("metrics 端点已下线（router 删 commit 23056de）");
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
        icon={<AlertCircle className="h-8 w-8 text-muted-foreground" />}
        title="metrics 端点已下线"
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
              <div className="mt-2 text-xs text-muted-foreground">{data.note}</div>
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
          <div className="text-muted-foreground">{breakdown.note}</div>
        </div>
      </GlassCard>
    </div>
  );
}
