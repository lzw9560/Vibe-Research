// S093 T17：当日 Tab 改盯盘执行台——WatchlistBoard + 持仓 chips + 市场情绪 + 盯盘入口全天可见。
// 选股决策内容迁前瞻 Tab（T15）；行为对照移复盘（T18 BehaviorComparisonCard）。
import { useEffect, useCallback, useState } from "react";
import { TrendingUp, Zap, Activity } from "lucide-react";
import { Link } from "react-router-dom";
import { WorkflowStage } from "./components/WorkflowStage";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { Sheet } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { EntryCard } from "@/components/workflow/EntryCard";
import { WatchlistBoard } from "@/components/workflow/WatchlistBoard";
import { CandidateDetailPanel } from "./CandidateDetail";
import { useTransitionWorkflowState, usePreMarketBriefing, usePreMarketRefresh, useWorkflowStates, useIntradayLatest, useDateTriplet } from "@/lib/query";
import type { TransitionRequest } from "@/lib/api";
import type { IntradaySnapshot } from "@/lib/api/types";
import { VerificationCardBlock } from "@/components/workflow/VerificationCardBlock";
import { STATUS_COLORS } from "@/components/workflow/statusMeta";

// S092 R4：PreMarketBriefing 改受控 date prop（=dateTriplet.today）+ 接收 stage prop。
// S093 T15：选股决策内容迁出至前瞻 Tab（ForwardTabSection）。当日 Tab 保留空壳。
// P9 修复：深链 /workflow/pre-market 时 props 缺省→用 dateTriplet 兜底（同 PostMarketReview 模式）
interface PreMarketBriefingProps {
  /** 当日数据日（=dateTriplet.today），受控 prop；深链缺省→dateTriplet 兜底 */
  date?: string;
  /** 时段（dateTriplet.stage），盘后标注"数据为今早盘前采集口径"；深链缺省→dateTriplet 兜底 */
  stage?: string;
}

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

export default function PreMarketBriefing({ date, stage }: PreMarketBriefingProps) {
  // P9 修复：深链 /workflow/pre-market 时 props 缺省→用 dateTriplet 兜底（同 PostMarketReview 模式）
  const { data: triplet } = useDateTriplet();
  const _date = date ?? triplet?.today ?? "";
  const _stage = stage ?? triplet?.stage ?? "pre_market";
  // S093 T17 + S146：WatchlistBoard 需要 F（前瞻数据日——briefing final+scored；breakout 移研究后不再需 forward）
  const F = triplet?.F ?? "";
  // S092：盘后时段（stage=post_market）标注"数据为今早盘前采集口径"
  const isPostMarket = _stage === "post_market";

  // S026: running 5s 轮询；S048 R8: staleTime 由 hook 按 date/status 动态处理
  const { data: briefing, isLoading, refetch } = usePreMarketBriefing(_date, {
    refetchInterval: (query) => (query.state.data?.status === "running" ? 5_000 : false),
  });
  const refresh = usePreMarketRefresh();
  // S093 T17：持仓 chips + 市场情绪实时指标
  const { data: workflowStates } = useWorkflowStates(_date);
  const { data: intradaySnapshot } = useIntradayLatest();
  // S092：isHistorical 语义变更——date 始终有值（容器传入 dateTriplet.today），
  //   原 !!date 判断不再有效。改用 briefing.from_snapshot 判断"历史快照"（不可变）。
  //   历史 done = from_snapshot && status==="done"（旧逻辑：date 非空且 done）。
  const isHistorical = !!briefing?.from_snapshot;
  // S031 R18：候选诊断抽屉（点候选不整页跳，弹侧边抽屉）
  const [drawerCode, setDrawerCode] = useState<string | null>(null);
  // S054：盘前录入建仓入口（候选矩阵「买入」按钮 → 弹 TransitionForm）
  const [buyEntry, setBuyEntry] = useState<{ code: string; name: string } | null>(null);
  const transition = useTransitionWorkflowState();

  // S093 T15：advisory 仓位摘要 + activeStrategy 迁出至前瞻 Tab（ForwardTabSection 承接）。

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

  // S066 grill：running 态显已耗时（从 briefing.as_of 派生，去原"并行两因子，约1分钟"stale 硬编码）
  const [elapsedNow, setElapsedNow] = useState(Date.now());
  useEffect(() => {
    if (briefing?.status !== "running") return;
    const id = setInterval(() => setElapsedNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [briefing?.status]);

  const status = briefing?.status ?? "idle";
  // S048 R7：历史日期 done 后不可变——刷新入口整体移除（UI + staleTime Infinity 双保险）
  const isHistoryDone = isHistorical && status === "done";
  const canRefresh = !isHistoryDone;

  const handleRefresh = useCallback(() => {
    if (!canRefresh) return;
    if (status !== "running") refresh.mutate(_date);
    refetch();
  }, [canRefresh, status, refresh, refetch, _date]);

  if (!briefing) return null;

  // S093 T17：askAiContext 简化为盯盘执行台上下文（选股决策数据迁前瞻 Tab）
  const askAiContext = [
    `当前页面：盯盘执行台（当日 Tab）`,
    `日期：${briefing.data_date ?? _date ?? "未取得"}`,
    `时段：${_stage}`,
    workflowStates?.counts
      ? `持仓状态：候选${workflowStates.counts.candidate ?? 0}/观察${workflowStates.counts.watching ?? 0}/监控${workflowStates.counts.monitoring ?? 0}/持仓${workflowStates.counts.holding ?? 0}/已结${workflowStates.counts.settled ?? 0}`
      : `持仓状态：未取得`,
    intradaySnapshot?.zt_count != null
      ? `市场情绪：涨停${intradaySnapshot.zt_count}/封板率${intradaySnapshot.seal_rate ?? "—"}/炸板率${intradaySnapshot.break_rate ?? "—"}/情绪分${intradaySnapshot.score ?? "—"}/${intradaySnapshot.zone}`
      : `市场情绪：未取得`,
  ].join("\n");

  return (
    <WorkflowStage
      title="盯盘执行台"
      subtitle="Watchlist Monitor"
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
            <span className="text-sm text-muted-foreground">
              盘前因子采集中…
              {briefing.as_of && (
                <span className="tabular-nums"> 已 {Math.max(0, Math.floor((elapsedNow - Date.parse(briefing.as_of)) / 1000))}s</span>
              )}
            </span>
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
          <p className="text-sm text-muted-foreground">{_date} 无采集快照。</p>
          <p className="text-xs text-warning">补采数据可能与当日实盘所见有出入（外部源历史数据会变动）。</p>
          <Button
            variant="primary"
            size="sm"
            disabled={refresh.isPending}
            onClick={() => refresh.mutate(_date)}
          >
            {refresh.isPending ? "补采中…" : "补采该日数据"}
          </Button>
        </GlassCard>
      )}

      {/* S093 T17：当日 Tab = 盯盘执行台（选股决策内容迁前瞻 Tab，行为对照移复盘 Tab） */}

      {/* S092 R4：盘后时段标注——数据为今早盘前采集口径，17:15 后可刷新 */}
      {isPostMarket && (
        <div className="mb-4 rounded-lg border border-primary/25 bg-primary/5 p-3 text-sm text-primary">
          ⓘ 数据为今早盘前采集口径，17:15 后可刷新为最终收盘口径。
        </div>
      )}

      {/* S093 T17：done 状态——盯盘执行台核心内容（WatchlistBoard + 持仓 chips + 市场情绪） */}
      {status === "done" && F && (
        <WatchlistBoard F={F} date={_date} />
      )}

      {/* S093 T17：持仓 chips——useWorkflowStates 取候选/观察/监控/持仓/已结计数 */}
      {status === "done" && workflowStates?.counts && (
        <HoldingChips counts={workflowStates.counts} />
      )}

      {/* S093 T17：市场情绪实时指标——useIntradayLatest zt_count/seal_rate/break_rate/score */}
      {status === "done" && <MarketSentimentBar snapshot={intradaySnapshot} />}

      {briefing.as_of && status === "done" && (
        <p className="mt-4 text-xs text-muted-foreground/50">更新于 {formatRelativeTime(briefing.as_of)}</p>
      )}

      {/* S093 T17（R8）：盯盘入口全天可见——取消 isIntraday 门控，三个 EntryCard 常驻 */}
      <div className="mb-6 space-y-2">
        <EntryCard to="/workflow/intraday" title="实时盯盘" subtitle="持仓+命中标的盯盘·炸板预警C1-C6" icon={TrendingUp} date={_date} />
        <EntryCard to="/workflow/alerts" title="炸板预警" subtitle="炸板规则C1-C6全市场统一" icon={Zap} date={_date} />
        <EntryCard to="/workflow/coach" title="盯盘教练" subtitle="时刻表+条件清单+attention_mode" icon={Activity} date={_date} />
      </div>

      {/* S060：昨日验证对账块 */}
      {status === "done" && <VerificationCardBlock />}

      {/* S093 T15：T-1 数据 + 语境（含暴风雨预测）迁出至前瞻 Tab 辅助折叠区。 */}

      {/* 候选诊断抽屉——点候选弹侧边卡，不整页跳；Esc/点遮罩关（S033：传 date 供状态卡/徽标） */}
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

/** S093 T17：持仓 chips——候选/观察/监控/持仓/已结计数徽章行。 */
function HoldingChips({ counts }: { counts: Record<string, number> }) {
  const chips = [
    { key: "candidate", label: "候选" },
    { key: "watching", label: "观察" },
    { key: "monitoring", label: "监控" },
    { key: "holding", label: "持仓" },
    { key: "settled", label: "已结" },
  ];
  const visible = chips.filter(({ key }) => (counts[key] ?? 0) > 0);
  if (visible.length === 0) return null;
  return (
    <div className="mb-6 flex flex-wrap gap-2">
      {visible.map(({ key, label }) => (
        <span
          key={key}
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs text-white ${
            STATUS_COLORS[key] ?? "bg-gray-300"
          }`}
        >
          {label} {counts[key]}
        </span>
      ))}
    </div>
  );
}

/** S093 T17：市场情绪实时指标——zt_count/seal_rate/break_rate/score/zone。 */
function MarketSentimentBar({ snapshot }: { snapshot?: IntradaySnapshot | null }) {
  if (!snapshot) return null;
  const fmtRate = (v: number | null | undefined) =>
    v != null ? `${v.toFixed(0)}%` : "—";
  return (
    <GlassCard className="mb-6 p-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <div>
          <p className="text-xs text-muted-foreground">涨停数</p>
          <p className="mt-1 text-sm font-medium tabular-nums">
            {snapshot.zt_count ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">炸板数</p>
          <p className="mt-1 text-sm font-medium tabular-nums">
            {snapshot.zb_count ?? "—"}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">封板率</p>
          <p className="mt-1 text-sm font-medium tabular-nums">
            {fmtRate(snapshot.seal_rate)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">炸板率</p>
          <p className="mt-1 text-sm font-medium tabular-nums">
            {fmtRate(snapshot.break_rate)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">情绪分</p>
          <p className="mt-1 text-sm font-medium tabular-nums">
            {snapshot.score ?? "—"}
            {snapshot.zone && (
              <span className="ml-1 text-xs text-muted-foreground">
                {snapshot.zone}
              </span>
            )}
          </p>
        </div>
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/60">
        参考值，非执行指令；市场有风险
      </p>
    </GlassCard>
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
        <option value="weak_turn_strong">弱转强接力</option>
        <option value="pattern_reversal">形态反包</option>
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
