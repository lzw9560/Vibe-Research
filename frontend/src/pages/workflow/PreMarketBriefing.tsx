import { useEffect, useCallback } from "react";
import { TrendingUp } from "lucide-react";
import { WorkflowStage } from "./components/WorkflowStage";
import { usePreMarketBriefing, usePreMarketRefresh } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import type { FactorResult } from "@/lib/api";
import { useNavigate } from "react-router-dom";

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
  // S026: 异步化——running 时 5s 轮询，其余停轮询
  const { data: briefing, isLoading, refetch } = usePreMarketBriefing({
    refetchInterval: (query) => (query.state.data?.status === "running" ? 5_000 : false),
  });
  const refresh = usePreMarketRefresh();
  const navigate = useNavigate();

  // idle → 自动触发后台采集（refresh.isPending 防重入）
  useEffect(() => {
    if (briefing?.status === "idle" && !refresh.isPending) {
      refresh.mutate(undefined);
    }
  }, [briefing?.status, refresh]);

  const handleRefresh = useCallback(() => {
    if (briefing?.status !== "running") refresh.mutate(undefined);
    refetch();
  }, [refetch, refresh, briefing?.status]);

  if (!briefing) return null;

  const status = briefing.status ?? "idle";
  const factors: FactorResult[] = briefing.factors ?? [];
  const emotion = briefing.market_emotion;

  return (
    <WorkflowStage
      title="盘前简报"
      subtitle="Pre-Market Briefing"
      loading={isLoading}
      onRefresh={handleRefresh}
    >
      {/* 数据日期 */}
      {briefing.data_date && (
        <p className="mb-4 text-xs text-muted-foreground">数据日期：{briefing.data_date}</p>
      )}

      {/* 状态分支（S026 异步化） */}
      {status === "running" && (
        <GlassCard className="p-6">
          <div className="flex items-center gap-3">
            <Skeleton className="h-4 w-4 rounded-full" />
            <span className="text-sm text-muted-foreground">盘前因子采集中（并行两因子，约 1 分钟）…</span>
          </div>
        </GlassCard>
      )}

      {status === "idle" && (
        <GlassCard className="p-6">
          <p className="text-sm text-muted-foreground">未采集，正在触发后台采集…</p>
        </GlassCard>
      )}

      {status === "error" && (
        <GlassCard className="border border-warning/30 p-4">
          <p className="text-sm text-warning">采集失败：{briefing.error ?? "未知错误"}</p>
        </GlassCard>
      )}

      {/* done：情绪 + 因子分区 */}
      {status === "done" && (
        <>
          {(emotion?.sentiment_index != null || emotion?.phase) && (
            <div className="mb-6">
              <h3 className="mb-3 text-sm font-semibold">市场情绪</h3>
              <div className="grid gap-3 sm:grid-cols-2">
                <GlassCard className="p-4">
                  <p className="text-xs text-muted-foreground">综合评分</p>
                  <p className="mt-1 text-2xl font-bold">
                    {emotion?.sentiment_index != null ? Number(emotion.sentiment_index).toFixed(1) : "—"}
                  </p>
                </GlassCard>
                <GlassCard className="p-4">
                  <p className="text-xs text-muted-foreground">情绪阶段</p>
                  <p className="mt-1 text-2xl font-bold">
                    {emotion?.phase ? phaseLabel(emotion.phase) : "—"}
                  </p>
                </GlassCard>
              </div>
            </div>
          )}

          {factors.length > 0 ? (
            <div className="space-y-6">
              {factors.map((fr) => (
                <FactorSection key={fr.factor_id} factor={fr} onPick={(code) => navigate(`/workflow/candidates/${code}`)} />
              ))}
            </div>
          ) : (
            <GlassCard className="p-4">
              <p className="text-sm text-muted-foreground">采集完成但无候选标的（见各因子 data_status 区分采集失败 vs 真空池）。</p>
            </GlassCard>
          )}
        </>
      )}

      {briefing.as_of && status === "done" && (
        <p className="mt-4 text-xs text-muted-foreground/50">更新于 {formatRelativeTime(briefing.as_of)}</p>
      )}
    </WorkflowStage>
  );
}

/** 单因子分区：折叠区 + 候选列表（可点击进详情）。 */
function FactorSection({ factor, onPick }: { factor: FactorResult; onPick: (code: string) => void }) {
  const missing = factor.data_status === "未取得";
  const noQualified = factor.data_status === "无合格标的";
  const conditions = factor.layers[0]?.conditions ?? [];
  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          <span className="font-medium">{factor.factor_name}</span>
          <span className="text-xs text-muted-foreground">{factor.candidates.length} 只候选</span>
        </div>
        <span className="text-xs text-muted-foreground">{factor.data_date}</span>
      </div>

      {/* 筛选条件：让用户看清系统在干什么（S028 R4） */}
      {conditions.length > 0 && (
        <div className="mt-3">
          <div className="mb-1 text-xs text-muted-foreground">筛选条件</div>
          <div className="flex flex-wrap gap-1">
            {conditions.map((c, i) => (
              <span key={i} className="rounded bg-muted/40 px-2 py-0.5 text-xs">{c}</span>
            ))}
          </div>
        </div>
      )}

      {/* 数据未取得如实显示原因 */}
      {missing && (
        <p className="mt-2 text-sm text-warning">
          该因子数据未取得：{String(factor.config?.reason ?? "未知原因")}
        </p>
      )}

      {/* 无合格标的：扫描了但 0 达标，如实展示扫描摘要（非告警色，S028 R1/R4） */}
      {noQualified && (
        <p className="mt-2 text-sm text-muted-foreground">
          {String(factor.config?.reason ?? "无合格标的")}
        </p>
      )}

      {/* 候选列表 */}
      {!missing && !noQualified && factor.candidates.length > 0 && (
        <div className="mt-3 space-y-1">
          {factor.candidates.slice(0, 20).map((c) => (
            <button
              key={c.code}
 onClick={() => onPick(c.code)}
              className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left hover:bg-muted/50"
            >
              <span className="font-medium">{c.name} <span className="text-xs text-muted-foreground">{c.code}</span></span>
              <span className="text-xs text-muted-foreground">{c.source_layer}</span>
            </button>
          ))}
          {factor.candidates.length > 20 && (
            <p className="text-xs text-muted-foreground">…共 {factor.candidates.length} 只</p>
          )}
        </div>
      )}

      {/* 命中规则示例 */}
      {!missing && !noQualified && factor.candidates.length > 0 && factor.candidates[0]?.hit_rules?.length > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          示例规则：{factor.candidates[0].hit_rules.join("，")}
        </p>
      )}
    </GlassCard>
  );
}
