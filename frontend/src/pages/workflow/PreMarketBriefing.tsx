import { useEffect, useCallback, useState } from "react";
import { TrendingUp } from "lucide-react";
import { WorkflowStage } from "./components/WorkflowStage";
import { usePreMarketBriefing, usePreMarketRefresh } from "@/lib/query";
import { useFunnelLayers } from "@/lib/query/topology";
import { useStrategyBacktest } from "@/lib/query/strategy";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { FunnelLayerCard } from "@/components/ui/FunnelLayerCard";
import { StrategyFilter } from "@/components/ui/StrategyFilter";
import { WinRateComparePanel } from "@/components/ui/WinRateComparePanel";
import { FunnelLayers } from "@/components/candidate/FunnelLayers";
import { CandidateDetailPanel } from "./CandidateDetail";
import type { FactorResult, FunnelLayer } from "@/lib/api";
import { Link, useSearchParams } from "react-router-dom";

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
  // S048 R2：date 来自 URL query（Workflow 首页日期选择器写入；无参数=今日实时）
  const [searchParams] = useSearchParams();
  const date = searchParams.get("date") ?? undefined;
  const isHistorical = !!date;

  // S026: running 5s 轮询；S048 R8: staleTime 由 hook 按 date/status 动态处理
  const { data: briefing, isLoading, refetch } = usePreMarketBriefing(date, {
    refetchInterval: (query) => (query.state.data?.status === "running" ? 5_000 : false),
  });
  const refresh = usePreMarketRefresh();
  // S031 R18：候选诊断抽屉（点候选不整页跳，弹侧边抽屉）
  const [drawerCode, setDrawerCode] = useState<string | null>(null);

  // idle → 自动触发后台采集（仅今日实时链路；历史日期 idle 由用户显式操作，防误触外部源）
  useEffect(() => {
    if (briefing?.status === "idle" && !isHistorical && !refresh.isPending) {
      refresh.mutate(undefined);
    }
  }, [briefing?.status, isHistorical, refresh]);

  const status = briefing?.status ?? "idle";
  // S048 R7：历史日期 done 后不可变——刷新入口整体移除（UI + staleTime Infinity 双保险）
  const isHistoryDone = isHistorical && status === "done";
  const canRefresh = !isHistoryDone;

  const handleRefresh = useCallback(() => {
    if (!canRefresh) return;
    if (status !== "running") refresh.mutate(date);
    refetch();
  }, [canRefresh, status, refresh, refetch, date]);

  if (!briefing) return null;

  const factors: FactorResult[] = briefing.factors ?? [];
  const emotion = briefing.market_emotion;

  return (
    <WorkflowStage
      title="盘前简报"
      subtitle="Pre-Market Briefing"
      loading={isLoading}
      onRefresh={canRefresh ? handleRefresh : undefined}
    >
      {/* 数据日期 */}
      {briefing.data_date && (
        <p className="mb-4 text-xs text-muted-foreground">数据日期：{briefing.data_date}</p>
      )}

      {/* S048 R7/R9：历史快照不可变提示（from_snapshot/is_backfill 徽标） */}
      {isHistoryDone && (
        <p className="mb-4 text-xs text-muted-foreground">
          历史快照（不可变）{briefing.from_snapshot ? " · 读盘数据" : ""}{briefing.is_backfill ? " · 补采" : ""}
        </p>
      )}

      {/* S031 R24：去涨停基因阈值配置 / 全市场得分表 */}
      <div className="mb-4">
        <Link to="/limitup/gene" className="text-sm text-primary hover:underline">涨停基因阈值配置 / 全市场得分表 →</Link>
      </div>

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
          <p className="text-sm text-muted-foreground">
            {isHistorical ? "该日未采集，可点右上方刷新触发采集。" : "未采集，正在触发后台采集…"}
          </p>
        </GlassCard>
      )}

      {status === "error" && (
        <GlassCard className="border border-warning/30 p-4">
          <p className="text-sm text-warning">采集失败：{briefing.error ?? "未知错误"}</p>
        </GlassCard>
      )}

      {/* S048 R7：历史无快照 → 显式补采入口（不自动触发；外部源历史数据会变，标注出入） */}
      {status === "no_snapshot" && (
        <GlassCard className="space-y-3 p-6">
          <p className="text-sm text-muted-foreground">{date} 无采集快照。</p>
          <p className="text-xs text-warning">补采数据可能与当日实盘所见有出入（外部源历史数据会变动）。</p>
          <Button
            variant="primary"
            size="sm"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate(date)}
          >
            {refresh.isPending ? "补采中…" : "补采该日数据"}
          </Button>
        </GlassCard>
      )}

      {/* S031 R23：done 纵向流——情绪 → 因子漏斗 → 候选池漏斗 → 战法胜率对比 → 抽屉 */}
      {status === "done" && (
        <>
          {/* ① 市场情绪 */}
          {(emotion?.sentiment_index != null || emotion?.phase) && (
            <div className="mb-6">
              <SectionHeader title="市场情绪" />
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

          {/* ② 涨停基因因子漏斗（打分→战法→仓位 三步） */}
          {factors.length > 0 ? (
            <div className="mb-6 space-y-4">
              <SectionHeader title="涨停基因因子漏斗" subtitle="L1 打分 → L2 战法 → L3 仓位（逐层可验证）" />
              {factors.map((fr) => (
                <FactorSection key={fr.factor_id} factor={fr} onPick={setDrawerCode} />
              ))}
            </div>
          ) : (
            <GlassCard className="mb-6 p-4">
              <p className="text-sm text-muted-foreground">采集完成但无候选标的（见各因子 data_status 区分采集失败 vs 真空池）。</p>
            </GlassCard>
          )}

          {/* ③ 候选池 R1/R2/R3 漏斗（from_snapshot 时用快照层，历史零外部请求） */}
          <CandidateFunnelEmbed
            date={briefing.data_date}
            onPick={setDrawerCode}
            snapshotLayers={briefing.from_snapshot ? briefing.funnel_layers ?? [] : undefined}
          />

          {/* ④ 战法胜率对比（真实回测 vs 合成估算） */}
          <WinRateCompareSection factors={factors} />
        </>
      )}

      {briefing.as_of && status === "done" && (
        <p className="mt-4 text-xs text-muted-foreground/50">更新于 {formatRelativeTime(briefing.as_of)}</p>
      )}

      {/* ⑤ 候选诊断抽屉——点候选弹侧边卡，不整页跳；Esc/点遮罩关（S033：传 date 供状态卡/徽标） */}
      <Sheet open={!!drawerCode} onClose={() => setDrawerCode(null)}>
        {drawerCode && <CandidateDetailPanel code={drawerCode} date={briefing.data_date} />}
      </Sheet>
    </WorkflowStage>
  );
}

/** S031 R17 候选池漏斗嵌入；S048 R9：snapshotLayers 存在（from_snapshot）时直渲快照、
 * 禁用 live 查询（enabled:false + date undefined，历史零外部请求）。 */
function CandidateFunnelEmbed({
  date,
  onPick,
  snapshotLayers,
}: {
  date?: string;
  onPick: (code: string) => void;
  snapshotLayers?: FunnelLayer[];
}) {
  const useLive = snapshotLayers === undefined;
  const { data: liveLayers, isLoading } = useFunnelLayers(useLive ? date : undefined, { enabled: useLive });
  const layers = snapshotLayers ?? liveLayers;
  if (!layers || layers.length === 0) return null;
  return (
    <div className="mb-6 space-y-3">
      <SectionHeader title="候选池漏斗" subtitle="R1/R2/R3 逐层可验证" />
      {useLive && isLoading ? (
        <Skeleton variant="rectangular" className="h-32" />
      ) : (
        <FunnelLayers layers={layers} date={date} onPick={onPick} />
      )}
    </div>
  );
}

/** S031 R22：战法胜率对比——useStrategyBacktest 真实回测 + 各因子 L2 passed 合成估算。 */
function WinRateCompareSection({ factors }: { factors: FactorResult[] }) {
  const { data: backtest, isLoading } = useStrategyBacktest(60);
  // 取所有因子 L2 战法层 passed（携 best_strategy + confidence_value）
  const l2Passed = factors
    .flatMap((f) => f.layers ?? [])
    .filter((l) => l.layer_id === "LS-2")
    .flatMap((l) => l.passed ?? []);
  if (!factors.length) return null;
  return (
    <div className="mb-6">
      <WinRateComparePanel backtest={backtest} l2Passed={l2Passed} loading={isLoading} />
    </div>
  );
}

/** S031 R14/R19：单因子多层漏斗（L1 打分 / L2 战法 / L3 仓位）——L2 挂战法多选反筛。 */
function FactorSection({ factor, onPick }: { factor: FactorResult; onPick: (code: string) => void }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const layers = factor.layers ?? [];
  const l2 = layers.find((l) => l.layer_id === "LS-2");
  // L2 passed 的 best_strategy 去重 → 战法 chips（非空）
  const strategies = Array.from(
    new Set((l2?.passed ?? []).map((c) => c.best_strategy).filter((s): s is string => !!s)),
  );

  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="h-4 w-4" />
          <span className="font-medium">{factor.factor_name}</span>
        </div>
        <span className="text-xs text-muted-foreground">{factor.data_date}</span>
      </div>

      {layers.length > 0 ? (
        <div className="mt-3 space-y-2">
          {layers.map((l) => {
            // L2 战法层：StrategyFilter 多选 + 即时反筛 passed（纯前端，不请求后端）
            if (l.layer_id === "LS-2" && strategies.length > 0) {
              const all = l.passed ?? [];
              const filteredPassed = selected.size > 0
                ? all.filter((c) => c.best_strategy && selected.has(c.best_strategy))
                : all;
              const l2Display: FunnelLayer = { ...l, passed: filteredPassed, output_count: filteredPassed.length };
              return (
                <div key={l.layer_id}>
                  <StrategyFilter strategies={strategies} selected={selected} onChange={setSelected} className="mb-2" />
                  <FunnelLayerCard layer={l2Display} variant="info" onPick={onPick} date={factor.data_date} />
                </div>
              );
            }
            return <FunnelLayerCard key={l.layer_id} layer={l} variant="info" onPick={onPick} date={factor.data_date} />;
          })}
        </div>
      ) : (
        <p className="mt-2 text-sm text-muted-foreground">无漏斗层数据</p>
      )}
    </GlassCard>
  );
}
