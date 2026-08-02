import { useEffect, useCallback } from "react";
import { TrendingUp } from "lucide-react";
import { WorkflowStage } from "./components/WorkflowStage";
import { usePreMarketBriefing } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import type { PreMarketCandidate } from "@/lib/api";

function formatRelativeTime(generatedAt: string): string {
  try {
    const gen = new Date(generatedAt).getTime();
    const now = Date.now();
    const diffMin = Math.floor((now - gen) / 60000);
    if (diffMin < 1) return "刚刚";
    if (diffMin < 60) return `${diffMin} 分钟前`;
    return `${Math.floor(diffMin / 60)} 小时前`;
  } catch {
    return generatedAt;
  }
}

function phaseLabel(phase: string): string {
  const map: Record<string, string> = {
    bullish: "强势", bearish: "弱势", neutral: "中性",
    turning: "转折", accumulation: "蓄势", distribution: "派发",
  };
  return map[phase.toLowerCase()] ?? phase;
}

export default function PreMarketBriefing() {
  const inTradingHours = () => {
    const h = new Date().getHours();
    return h >= 9 && h < 15;
  };
  const { data: report, isLoading, refetch } = usePreMarketBriefing({
    refetchInterval: inTradingHours() ? 60_000 : false,
  });

  useEffect(() => {
    if (report?.generated_at) {
      // update timestamp handled by query
    }
  }, [report?.generated_at]);

  const handleRefresh = useCallback(() => refetch(), [refetch]);

  if (!report) return null;

  const candidates: PreMarketCandidate[] = report.candidates ?? [];
  const strongCandidates: PreMarketCandidate[] = report.strong_candidates ?? [];

  return (
    <WorkflowStage 
      title="盘前简报" 
      subtitle="Pre-Market Briefing"
      loading={isLoading}
      onRefresh={handleRefresh}
    >
      {/* 情绪指数 */}
      {(report.sentiment_index != null || report.sentiment_phase) && (
        <div className="mb-6">
          <h3 className="mb-3 text-sm font-semibold">市场情绪</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            <GlassCard className="p-4">
              <p className="text-xs text-muted-foreground">综合评分</p>
              <p className="mt-1 text-2xl font-bold">
                {report.sentiment_index?.toFixed(1) ?? "—"}
              </p>
            </GlassCard>
            <GlassCard className="p-4">
              <p className="text-xs text-muted-foreground">情绪阶段</p>
              <p className="mt-1 text-2xl font-bold">
                {report.sentiment_phase ? phaseLabel(report.sentiment_phase) : "—"}
              </p>
            </GlassCard>
          </div>
        </div>
      )}

      {/* 强势候选 */}
      {strongCandidates.length > 0 && (
        <div className="mb-6">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
            <TrendingUp className="h-4 w-4" /> 强势候选
          </h3>
          <div className="space-y-2">
            {strongCandidates.slice(0, 5).map((c) => (
              <GlassCard key={c.code} className="flex items-center gap-3 p-3">
                <div className="flex-1">
                  <p className="font-medium">{c.name ?? c.code}</p>
                  {c.score != null && (
                    <p className="text-xs text-muted-foreground">评分: {c.score}</p>
                  )}
                </div>
                {c.change_pct != null && (
                  <span className={`font-mono ${c.change_pct > 0 ? "text-danger" : "text-success"}`}>
                    {c.change_pct > 0 ? "+" : ""}{c.change_pct}%
                  </span>
                )}
              </GlassCard>
            ))}
          </div>
        </div>
      )}

      {/* 全部候选 */}
      {candidates.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold">候选池</h3>
          <div className="space-y-2">
            {candidates.map((c) => (
              <GlassCard key={c.code} className="flex items-center gap-3 p-3">
                <div className="flex-1">
                  <p className="font-medium">{c.name ?? c.code}</p>
                </div>
                {c.score != null && (
                  <span className="font-mono text-sm">{c.score}</span>
                )}
              </GlassCard>
            ))}
          </div>
        </div>
      )}

      <p className="mt-4 text-xs text-muted-foreground/50">
        更新于 {formatRelativeTime(report.generated_at ?? "")}
      </p>
    </WorkflowStage>
  );
}
