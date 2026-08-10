import { useEffect, useCallback, useState } from "react";
import { TrendingUp } from "lucide-react";
import { WorkflowStage } from "./components/WorkflowStage";
import { usePreMarketBriefing, usePreMarketRefresh } from "@/lib/query";
import { useStrategyBacktest } from "@/lib/query/strategy";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { FunnelLayerCard } from "@/components/ui/FunnelLayerCard";
import { StrategyFilter } from "@/components/ui/StrategyFilter";
import { WinRateComparePanel } from "@/components/ui/WinRateComparePanel";
import { CandidateDetailPanel } from "./CandidateDetail";
import type { FactorResult } from "@/lib/api";
import type { FunnelLayer, PassedItem as FunnelPassedEntry } from "@/lib/candidates";
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

/** S049 B：市场情绪区——STI 分数+阶段 + 三率 chips + ladder 分布 + 涨跌停家数。缺数据显 "--"。 */
function MarketEmotionBlock({ emotion }: { emotion: import("@/lib/api/types").MarketEmotionBriefing | undefined }) {
  if (!emotion) return null;
  const hasAny = emotion.sti_score != null || emotion.sti_phase || emotion.seal_rate != null
    || emotion.ladder?.length || emotion.zt_count != null;
  if (!hasAny) return null;
  const pct = (v: number | null | undefined) => v != null ? `${(v * 100).toFixed(1)}%` : "—";
  const num = (v: number | null | undefined) => v != null ? String(v) : "—";
  return (
    <div className="mb-6">
      <SectionHeader title="市场情绪" subtitle="STI 温度 + 连板梯队 + 三率" />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <GlassCard className="p-4">
          <p className="text-xs text-muted-foreground">STI 温度</p>
          <p className="mt-1 text-2xl font-bold">{emotion.sti_score != null ? emotion.sti_score.toFixed(1) : "—"}</p>
        </GlassCard>
        <GlassCard className="p-4">
          <p className="text-xs text-muted-foreground">情绪阶段</p>
          <p className="mt-1 text-2xl font-bold">{emotion.sti_phase ?? "—"}</p>
        </GlassCard>
        <GlassCard className="p-4">
          <p className="text-xs text-muted-foreground">涨停 / 跌停</p>
          <p className="mt-1 text-2xl font-bold">{num(emotion.zt_count)} / {num(emotion.dt_count)}</p>
        </GlassCard>
        <GlassCard className="p-4">
          <p className="text-xs text-muted-foreground">连板梯队</p>
          <p className="mt-1 text-sm font-medium leading-relaxed">
            {emotion.ladder?.length
              ? emotion.ladder.map((t) => `${t.boards}板×${t.count}`).join(" ")
              : "—"}
          </p>
        </GlassCard>
      </div>
      <div className="mt-2 flex flex-wrap gap-2 text-xs">
        <GlassCard className="px-3 py-1.5">封板率 {pct(emotion.seal_rate)}</GlassCard>
        <GlassCard className="px-3 py-1.5">炸板率 {pct(emotion.break_rate)}</GlassCard>
        <GlassCard className="px-3 py-1.5">晋级率 {pct(emotion.promotion_rate)}</GlassCard>
      </div>
    </div>
  );
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
  // S049 D4：done/snapshot 响应都携带 funnel_layers（live done 经 _build_funnel_layers 命中缓存）
  const funnelLayers = briefing.funnel_layers;

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
          {/* ① 市场情绪（S049 B 重写：STI+三率+ladder+涨跌停） */}
          <MarketEmotionBlock emotion={emotion} />

          {/* ② 涨停基因因子漏斗（打分→战法→仓位 三步）——S049 D3：跳 candidate_funnel 卡（消重复，候选池漏斗在 ③ 统一呈现） */}
          {factors.filter((fr) => fr.factor_id !== "candidate_funnel").length > 0 ? (
            <div className="mb-6 space-y-4">
              <SectionHeader title="涨停基因因子漏斗" subtitle="L1 打分 → L2 战法 → L3 仓位（逐层可验证）" />
              {factors.filter((fr) => fr.factor_id !== "candidate_funnel").map((fr) => (
                <FactorSection key={fr.factor_id} factor={fr} onPick={setDrawerCode} />
              ))}
            </div>
          ) : (
            <GlassCard className="mb-6 p-4">
              <p className="text-sm text-muted-foreground">采集完成但无候选标的（见各因子 data_status 区分采集失败 vs 真空池）。</p>
            </GlassCard>
          )}

          {/* ③ 候选池 R1/R2/R3 漏斗矩阵（S049 D2：FunnelMatrix 三列+全参数列替 FunnelLayers；
              D4：优先读 briefing.funnel_layers，不发额外 GET） */}
          <CandidateFunnelEmbed
            date={briefing.data_date}
            onPick={setDrawerCode}
            snapshotLayers={briefing.from_snapshot ? funnelLayers : funnelLayers}
          />

          {/* ④ 战法胜率对比（真实回测 vs 合成估算） */}
          <WinRateCompareSection factors={factors} onPick={setDrawerCode} />
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

/** S049 D2/D4：候选池漏斗矩阵嵌入——优先读 briefing.funnel_layers（done/snapshot 均携带），
 * 不发额外 GET（消重复请求）。无 funnel_layers 时降级 live 查询。 */
function CandidateFunnelEmbed({
  onPick,
  snapshotLayers,
}: {
  date?: string;
  onPick: (code: string) => void;
  snapshotLayers?: FunnelLayer[];
}) {
  // S049 D4：done/snapshot 响应都带 funnel_layers → 直用，不发 GET
  if (snapshotLayers && snapshotLayers.length > 0) {
    return (
      <div className="mb-6 space-y-3">
        <SectionHeader title="候选池漏斗矩阵" subtitle="R1/R2/R3 三列对齐 + 全参数" />
        <FunnelMatrixSimple layers={snapshotLayers} onPick={onPick} />
      </div>
    );
  }
  return null;
}

/** S049 D2：简易矩阵渲染（完整 FunnelMatrix 组件在 S7 任务建；此处先占位用 FunnelLayers 兜底） */
function FunnelMatrixSimple({ layers, onPick }: { layers: FunnelLayer[]; onPick: (code: string) => void }) {
  // 三层 passed union 去重
  const r1 = layers.find((l) => l.layer_id === "R1");
  const r2 = layers.find((l) => l.layer_id === "R2");
  const r3 = layers.find((l) => l.layer_id === "R3");
  const allCodes = Array.from(new Set([
    ...(r1?.passed ?? []).map((p) => p.code),
    ...(r2?.passed ?? []).map((p) => p.code),
    ...(r3?.passed ?? []).map((p) => p.code),
  ]));
  if (allCodes.length === 0) return null;
  // 取最深一层 passed entry（R3>R2>R1）
  const entryFor = (code: string): FunnelPassedEntry | undefined =>
    r3?.passed?.find((p) => p.code === code) ?? r2?.passed?.find((p) => p.code === code) ?? r1?.passed?.find((p) => p.code === code);
  // 排序：R3 通过优先 → R2 → R1 得分降序
  const inR3 = (c: string) => r3?.passed?.some((p) => p.code === c);
  const inR2 = (c: string) => r2?.passed?.some((p) => p.code === c);
  const sorted = [...allCodes].sort((a, b) => {
    const ra = (inR3(a) ? 3 : inR2(a) ? 2 : 1), rb = (inR3(b) ? 3 : inR2(b) ? 2 : 1);
    if (ra !== rb) return rb - ra;
    return (entryFor(b)?.gene_score ?? 0) - (entryFor(a)?.gene_score ?? 0);
  });
  const display = sorted.slice(0, 15);
  const v = (x: number | null | undefined) => x != null ? String(x) : "—";
  return (
    <GlassCard className="p-2">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-muted-foreground">
              <th className="px-2 py-1 text-left">代码</th>
              <th className="px-2 py-1 text-left">名称</th>
              <th className="px-2 py-1">R1</th>
              <th className="px-2 py-1">R2</th>
              <th className="px-2 py-1">R3</th>
              <th className="px-2 py-1">连板</th>
              <th className="px-2 py-1">换手%</th>
              <th className="px-2 py-1">量比</th>
              <th className="px-2 py-1">额(亿)</th>
              <th className="px-2 py-1">主力(万)</th>
              <th className="px-2 py-1">5日(万)</th>
              <th className="px-2 py-1">北向</th>
              <th className="px-2 py-1">催化</th>
              <th className="px-2 py-1">打分</th>
            </tr>
          </thead>
          <tbody>
            {display.map((code) => {
              const e = entryFor(code);
              const name = e?.name ?? code;
              return (
                <tr key={code} className="cursor-pointer border-t border-border/30 hover:bg-accent/30" onClick={() => onPick(code)}>
                  <td className="px-2 py-1 font-mono">{code}</td>
                  <td className="px-2 py-1">{name}</td>
                  <td className="px-2 py-1 text-center">{r1?.passed?.some((p) => p.code === code) ? "✓" : "—"}</td>
                  <td className="px-2 py-1 text-center">{r2?.passed?.some((p) => p.code === code) ? "✓" : "—"}</td>
                  <td className="px-2 py-1 text-center">{r3?.passed?.some((p) => p.code === code) ? "✓" : "—"}</td>
                  <td className="px-2 py-1 text-center">{v(e?.consec_boards)}</td>
                  <td className="px-2 py-1 text-center">{v(e?.turnover_pct)}</td>
                  <td className="px-2 py-1 text-center">{v(e?.vol_ratio)}</td>
                  <td className="px-2 py-1 text-center">{v(e?.amount_yi)}</td>
                  <td className="px-2 py-1 text-center">{v(e?.main_net_inflow)}</td>
                  <td className="px-2 py-1 text-center">{v(e?.main_net_5d)}</td>
                  <td className="px-2 py-1 text-center">{v(e?.northbound)}</td>
                  <td className="px-2 py-1 text-center max-w-[120px] truncate" title={e?.catalyst_summary ?? ""}>{e?.catalyst_summary ?? "—"}</td>
                  <td className="px-2 py-1 text-center font-mono">{v(e?.gene_score)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {sorted.length > 15 && (
        <p className="mt-2 text-xs text-muted-foreground">显示前 15 / 共 {sorted.length} 行</p>
      )}
    </GlassCard>
  );
}

/** S031 R22：战法胜率对比——useStrategyBacktest 真实回测 + 各因子 L2 passed 合成估算。 */
function WinRateCompareSection({ factors, onPick }: { factors: FactorResult[]; onPick: (code: string) => void }) {
  const { data: backtest, isLoading } = useStrategyBacktest(60);
  // 取所有因子 L2 战法层 passed（携 best_strategy + confidence_value）
  const l2Passed = factors
    .flatMap((f) => f.layers ?? [])
    .filter((l) => l.layer_id === "LS-2")
    .flatMap((l) => l.passed ?? []);
  if (!factors.length) return null;
  return (
    <div className="mb-6">
      <WinRateComparePanel backtest={backtest} l2Passed={l2Passed} loading={isLoading} onPickCandidate={onPick} />
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
