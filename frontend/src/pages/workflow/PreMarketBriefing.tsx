import { useEffect, useCallback, useState } from "react";
import { TrendingUp } from "lucide-react";
import { WorkflowStage } from "./components/WorkflowStage";
import { WeatherDecisionBar } from "@/components/workflow/WeatherDecisionBar";
import { StrategyGroupTabs } from "@/components/workflow/StrategyGroupTabs";
import { CalendarFactorHint } from "@/components/workflow/CalendarFactorHint";
import { MarketKillSwitchBanner } from "@/components/workflow/MarketKillSwitchBanner";
import { usePreMarketBriefing, usePreMarketRefresh, useShadowComparison } from "@/lib/query";
import { useStrategyBacktest } from "@/lib/query/strategy";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { FunnelLayerCard } from "@/components/ui/FunnelLayerCard";
import { StrategyFilter } from "@/components/ui/StrategyFilter";
import { WinRateComparePanel } from "@/components/ui/WinRateComparePanel";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { CandidateDetailPanel } from "./CandidateDetail";
import { deriveAssessmentTips } from "@/lib/winrate-assessment";
import { useTransitionWorkflowState } from "@/lib/query";
import type { TransitionRequest, FactorResult } from "@/lib/api";
import type { FunnelLayer, PassedItem as FunnelPassedEntry } from "@/lib/candidates";
import { Link, useSearchParams } from "react-router-dom";
import { VerificationCardBlock } from "@/components/workflow/VerificationCardBlock";

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
  // S054：盘前录入建仓入口（候选矩阵「买入」按钮 → 弹 TransitionForm）
  const [buyEntry, setBuyEntry] = useState<{ code: string; name: string } | null>(null);
  const transition = useTransitionWorkflowState();

  const handleBuy = (entry: { code: string; name: string }) => setBuyEntry(entry);
  const handleBuySubmit = (req: TransitionRequest) => {
    transition.mutate(req);
    setBuyEntry(null);
  };

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
  const funnelLayers = briefing.funnel_layers;

  // 问 AI 上下文——注入盘前简报真实数据
  const pmCtx = briefing.sentiment_context;
  const pmEmotion = briefing.market_emotion;
  const askAiContext = [
    `当前页面：盘前简报`,
    `日期：${briefing.data_date ?? date ?? "未取得"}`,
    pmCtx
      ? `情绪天气：${pmCtx.weather_state}，STI=${pmCtx.sti_score ?? "--"}（${pmCtx.sti_phase ?? "--"}）`
      : `情绪天气：未取得`,
    pmEmotion
      ? `市场情绪：涨停${pmEmotion.zt_count ?? "--"}/跌停${pmEmotion.dt_count ?? "--"}/连板梯队${pmEmotion.ladder?.map(t => `${t.boards}板×${t.count}`).join(" ") || "--"}/封板率${pmEmotion.seal_rate != null ? pmEmotion.seal_rate.toFixed(0) : "--"}%/炸板率${pmEmotion.break_rate != null ? pmEmotion.break_rate.toFixed(0) : "--"}%/晋级率${pmEmotion.promotion_rate != null ? pmEmotion.promotion_rate.toFixed(0) : "--"}%`
      : `市场情绪：未取得`,
    pmCtx?.fuse_state
      ? `熔断：${pmCtx.fuse_state.fuse_state}，允许战法：${(pmCtx.allowed_styles ?? []).join("、") || "无"}，禁用：${(pmCtx.forbidden_styles ?? []).join("、") || "无"}`
      : `熔断：未取得`,
    `因子漏斗：${factors.map(f => `${f.factor_id}:候选${(f.candidates ?? []).length}只`).join("，") || "无"}`,
    funnelLayers && funnelLayers.length > 0
      ? `漏斗层：${funnelLayers.map(l => `${l.layer_id}输入${l.input_count}/输出${l.output_count}`).join("，")}`
      : `漏斗层：未取得`,
    funnelLayers
      ?.flatMap(l => (l.passed ?? []).map(p => (p as FunnelPassedEntry).matched_triggers).flat())
      .filter(Boolean)
      .length
      ? `R3 触发：${[...new Set(funnelLayers.flatMap(l => (l.passed ?? []).flatMap(p => (p as FunnelPassedEntry).matched_triggers ?? [])))].join("、")}`
      : `R3 触发：无`,
  ].filter(Boolean).join("\n");

  return (
    <WorkflowStage
      title="盘前简报"
      subtitle="Pre-Market Briefing"
      loading={isLoading}
      onRefresh={canRefresh ? handleRefresh : undefined}
      actions={<AskAiButton context={askAiContext} />}
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

      {/* S031 R23：done 纵向流——天气决策条 → 情绪 → 因子漏斗 → 候选池漏斗 → 战法胜率对比 → 抽屉 */}
      {status === "done" && (
        <>
          {/* ⓪ 天气决策条（S063：T-1 硬标准头部，全宽非卡片） */}
          <div className="mb-6 space-y-3">
            <WeatherDecisionBar ctx={briefing.sentiment_context} />
            {/* S066 §16.4 市场级熔断横幅（触发时才渲染） */}
            <MarketKillSwitchBanner />
            {/* S066 §6 日历因子提示（周五×0.7/节前×0.3） */}
            <CalendarFactorHint date={briefing.data_date ?? ""} />
          </div>

          {/* S066 §3.3 策略组 Tab——按天气硬开关激活的策略分 tab */}
          <div className="mb-6">
            <StrategyGroupTabs
              weatherState={briefing.sentiment_context?.weather_state}
              activeStrategy={null}
              onSelect={() => {}}
            />
          </div>

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
            onBuy={handleBuy}
            snapshotLayers={briefing.from_snapshot ? funnelLayers : funnelLayers}
          />

          {/* ④ 战法胜率对比（真实回测 vs 合成估算） */}
          <WinRateCompareSection factors={factors} onPick={setDrawerCode} />
        </>
      )}

      {briefing.as_of && status === "done" && (
        <p className="mt-4 text-xs text-muted-foreground/50">更新于 {formatRelativeTime(briefing.as_of)}</p>
      )}

      {/* S054 R4：盘前行为干预卡（展开不收起）——三桶算账 + 研判 + 深看链接 */}
      {status === "done" && <PreMarketBehaviorBlock />}

      {/* S060：昨日验证对账块（嵌市场情绪区下方） */}
      {status === "done" && <VerificationCardBlock />}

      {/* ⑤ 候选诊断抽屉——点候选弹侧边卡，不整页跳；Esc/点遮罩关（S033：传 date 供状态卡/徽标） */}
      <Sheet open={!!drawerCode} onClose={() => setDrawerCode(null)}>
        {drawerCode && <CandidateDetailPanel code={drawerCode} date={briefing.data_date} />}
      </Sheet>

      {/* S054：盘前录入建仓抽屉——候选矩阵「买入」按钮触发 */}
      <Sheet open={!!buyEntry} onClose={() => setBuyEntry(null)}>
        {buyEntry && (
          <div className="space-y-3 p-4">
            <SectionHeader title="录入建仓" subtitle={`${buyEntry.code} ${buyEntry.name}`} />
            <BuyEntryForm
              code={buyEntry.code}
              name={buyEntry.name}
              date={briefing.data_date}
              submitting={transition.isPending}
              onSubmit={handleBuySubmit}
              onCancel={() => setBuyEntry(null)}
            />
          </div>
        )}
      </Sheet>
    </WorkflowStage>
  );
}

/** S049 D2/D4：候选池漏斗矩阵嵌入——优先读 briefing.funnel_layers（done/snapshot 均携带），
 * 不发额外 GET（消重复请求）。无 funnel_layers 时降级 live 查询。 */
function CandidateFunnelEmbed({
  onPick,
  onBuy,
  snapshotLayers,
}: {
  date?: string;
  onPick: (code: string) => void;
  onBuy?: (entry: { code: string; name: string }) => void;
  snapshotLayers?: FunnelLayer[];
}) {
  // S049 D4：done/snapshot 响应都带 funnel_layers → 直用，不发 GET
  if (snapshotLayers && snapshotLayers.length > 0) {
    return (
      <div className="mb-6 space-y-3">
        <SectionHeader title="候选池漏斗矩阵" subtitle="R1/R2/R3 三列对齐 + 全参数" />
        <FunnelMatrixSimple layers={snapshotLayers} onPick={onPick} onBuy={onBuy} />
      </div>
    );
  }
  return null;
}

/** S049 D2：简易矩阵渲染（完整 FunnelMatrix 组件在 S7 任务建；此处先占位用 FunnelLayers 兜底） */
function FunnelMatrixSimple({ layers, onPick, onBuy }: { layers: FunnelLayer[]; onPick: (code: string) => void; onBuy?: (entry: { code: string; name: string }) => void }) {
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
  // 合并三层 passed entry——R3>R2>R1 overlay，但各层独有字段（R2 的换手/量比/主力、
  // R3 的竞价/催化）都保留。取最深会丢 R2 的 activity/fund 字段 → 矩阵多列空。
  const entryFor = (code: string): FunnelPassedEntry | undefined => {
    const e1 = r1?.passed?.find((p) => p.code === code);
    const e2 = r2?.passed?.find((p) => p.code === code);
    const e3 = r3?.passed?.find((p) => p.code === code);
    if (!e1 && !e2 && !e3) return undefined;
    return { ...e1, ...e2, ...e3 } as FunnelPassedEntry;
  };
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
              <th className="px-2 py-1">操作</th>
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
                  <td className="px-2 py-1 text-center">
                    <button
                      type="button"
                      onClick={(ev) => {
                        ev.stopPropagation();
                        onBuy?.({ code, name });
                      }}
                      className="rounded bg-primary/15 px-2 py-0.5 text-[10px] font-medium text-primary hover:bg-primary/25"
                    >
                      买入
                    </button>
                  </td>
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

/** S054 R4：盘前行为干预卡——展开不收起。三桶算账 + 一致率 + 研判 + 深看链接。 */
function PreMarketBehaviorBlock() {
  const { data, isLoading } = useShadowComparison(28);
  if (isLoading) {
    return (
      <div className="mb-6">
        <SectionHeader title="盘前行为账单" subtitle="follow/feeling/missed 三桶 + 独立性" />
        <GlassCard className="p-4">
          <Skeleton variant="rounded" className="h-24" />
        </GlassCard>
      </div>
    );
  }
  if (!data) return null;

  const fmtPct = (v: number | null | undefined) => v != null ? `${(v * 100).toFixed(1)}%` : "—";
  const fmtRet = (v: number | null | undefined) => v != null ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—";

  const tips = deriveAssessmentTips(data);

  return (
    <div className="mb-6">
      <SectionHeader title="盘前行为账单" subtitle="决策前先看自己的行为账单" />
      <GlassCard className="p-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <p className="text-xs text-muted-foreground">跟随单 follow</p>
            <p className="mt-1 text-sm font-medium">n={data.follow.n} · 胜率 {fmtPct(data.follow.win_rate)} · 均收益 {fmtRet(data.follow.avg_return)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">感觉单 feeling</p>
            <p className="mt-1 text-sm font-medium">n={data.feeling.n} · 胜率 {fmtPct(data.feeling.win_rate)} · 均收益 {fmtRet(data.feeling.avg_return)}</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">漏单 missed</p>
            <p className="mt-1 text-sm font-medium">n={data.missed.n} · 胜率 {fmtPct(data.missed.win_rate)} · 均收益 {fmtRet(data.missed.avg_return)}</p>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>一致率 {fmtPct(data.independence.agreement_rate)}</span>
          {!data.sufficient && <span className="text-warning">样本不足（任一桶 n&lt;5），参考价值低</span>}
        </div>

        {tips.length > 0 && (
          <div className="mt-3 border-t border-border/30 pt-3">
            <p className="mb-1 text-xs font-medium">行为研判</p>
            <ul className="space-y-1">
              {tips.map((t) => (
                <li key={t.slice(0, 20)} className="text-xs text-foreground/90">· {t}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-3 flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground/60">{data.disclaimer}</p>
          <Link to="/behavior-loop" className="text-xs text-primary hover:underline">深看 →</Link>
        </div>
      </GlassCard>
    </div>
  );
}

/** S054：盘前录入建仓表单——code/name 固定，填 entry_price/strategy，target=holding。 */
function BuyEntryForm({
  code,
  name,
  date,
  submitting,
  onSubmit,
  onCancel,
}: {
  code: string;
  name: string;
  date?: string;
  submitting: boolean;
  onSubmit: (req: TransitionRequest) => void;
  onCancel: () => void;
}) {
  const [entryPrice, setEntryPrice] = useState("");
  const [strategy, setStrategy] = useState("");
  const [reason, setReason] = useState("");

  const handleSubmit = () => {
    const ep = entryPrice.trim() ? Number(entryPrice) : undefined;
    onSubmit({
      code,
      date: date ?? "",
      target: "holding",
      reason: reason.trim() || name,
      entry_price: Number.isFinite(ep) ? ep : undefined,
      strategy: strategy || undefined,
    });
  };

  return (
    <div className="space-y-2 rounded-lg border border-border/40 bg-muted/20 p-3">
      <div className="text-xs text-muted-foreground">
        <span className="font-mono">{code}</span> {name}
      </div>
      <input
        className="w-full rounded border border-border/50 bg-background px-2 py-1 text-xs"
        placeholder="买入价（可选）"
        inputMode="decimal"
        value={entryPrice}
        onChange={(e) => setEntryPrice(e.target.value)}
      />
      <select
        className="w-full rounded border border-border/50 bg-background px-2 py-1 text-xs"
        value={strategy}
        onChange={(e) => setStrategy(e.target.value)}
      >
        <option value="">战法（可选）</option>
        <option value="first_plate">首板挖掘</option>
        <option value="consecutive_relay">连板接力</option>
        <option value="break_reseal">炸板回封</option>
        <option value="low_absorption">低吸龙头</option>
        <option value="reverse_package">反包战法</option>
        <option value="n_shape_counterattack">N字反击</option>
        <option value="platform_breakout">平台突破</option>
        <option value="end_of_day_sneak">尾盘偷袭</option>
      </select>
      <input
        className="w-full rounded border border-border/50 bg-background px-2 py-1 text-xs"
        placeholder="理由（可选）"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <div className="flex gap-2 pt-1">
        <Button size="sm" onClick={handleSubmit} disabled={submitting}>确认录入建仓</Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={submitting}>取消</Button>
      </div>
    </div>
  );
}
