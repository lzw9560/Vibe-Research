// S087：工作流 tab 按 pipeline 重设计——5 tab（T-1/语境/盘前/盘中/盘后）。
// 主轴=交易时段（PipelineProgressBar current 驱动默认 tab）；盘前内闭环=选股→战法匹配→仓位；
// 盘中统一（炸板=市场事件不分叉）；盘后按战法聚合。战法/选股池两级 tab 融入盘前①②步。
// legacy 状态机降为盘前折叠卡（不删能力）。R13：每 tab AskAiButton 带该 tab 上下文。

import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Clock, TrendingUp, BarChart3, ChevronRight, RefreshCw, Activity, Share2, Building2, Zap } from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { PipelineProgressBar } from "@/components/workflow/PipelineProgressBar";
import { useQuery } from "@tanstack/react-query";
import { candidatesApi } from "@/lib/candidates";
import { FunnelLayers } from "@/components/candidate/FunnelLayers";
import { SelectionPipeline } from "@/components/pipeline/SelectionPipeline";
import { T1Tab } from "@/components/workflow/T1Tab";
import { ContextTab } from "@/components/workflow/ContextTab";
import { StrategyMatchMatrix } from "@/components/workflow/StrategyMatchMatrix";
import { useWorkflowStatus, usePreMarketBriefing, usePreMarketDates, useWorkflowStates } from "@/lib/query";

type TabKey = "t1" | "ctx" | "pre" | "intraday" | "post";

const TABS: { key: TabKey; label: string }[] = [
  { key: "t1", label: "T-1 数据" },
  { key: "ctx", label: "语境" },
  { key: "pre", label: "盘前" },
  { key: "intraday", label: "盘中" },
  { key: "post", label: "盘后" },
];

// stageKey → tab（默认 tab 跟后端阶段）
function stageToTab(stageKey: string): TabKey {
  if (stageKey === "intraday") return "intraday";
  if (stageKey === "post-market") return "post";
  return "pre";
}

// 盘前/盘中/盘后入口卡（链接到既有子页）
function EntryCard({ to, title, subtitle, icon: Icon, date }: { to: string; title: string; subtitle: string; icon: React.ComponentType<{ className?: string }>; date?: string }) {
  return (
    <Link to={date ? `${to}?date=${date}` : to} className="block">
      <GlassCard className="p-4 transition-all hover:ring-2 hover:ring-primary/30">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-primary/10 border border-primary/30">
            <Icon className="h-5 w-5 text-primary" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold">{title}</h3>
              <ChevronRight className="h-4 w-4 text-muted-foreground/50" />
            </div>
            <p className="text-xs text-muted-foreground/70 mt-0.5">{subtitle}</p>
          </div>
        </div>
      </GlassCard>
    </Link>
  );
}

export default function Workflow() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedDate = searchParams.get("date") ?? undefined;

  const { data: backend, isFetching, refetch } = useWorkflowStatus({ refetchInterval: selectedDate ? false : 60_000 });
  const refreshing = isFetching;
  const { data: briefing } = usePreMarketBriefing(selectedDate);
  const { data: datesData } = usePreMarketDates();
  const { data: histStates } = useWorkflowStates(selectedDate);
  const counts = histStates?.counts ?? {};

  // 选股池缓存优先（S087 R10/B5）：读 GET /cache 秒开，404→空态+"重新跑"
  const { data: funnelCache, isLoading: funnelLoading } = useQuery({
    queryKey: ["s087-funnel-cache", selectedDate ?? "latest"],
    queryFn: () => candidatesApi.readFunnelCache(selectedDate),
    retry: false,
  });
  // fallback 实跑（缓存拿不到时）
  const runFunnelReal = () => candidatesApi.runFunnel("all", selectedDate);

  const stageKey = (backend?.stage as string) ?? "pre-market";
  const [tab, setTab] = useState<TabKey>(stageToTab(stageKey));
  const [showLegacy, setShowLegacy] = useState(false);

  const funnelResult = funnelCache;

  const askAiContext = useMemo(() => [
    `当前页面：选股工作流首页（5-tab pipeline）`,
    `当前 tab：${tab} | 后端 stage：${stageKey} | market_status：${backend?.market_status ?? "—"}`,
    `briefing status：${briefing?.status ?? "—"} | data_date：${briefing?.data_date ?? "—"}`,
    `选股缓存：${funnelResult ? `${funnelResult.final_candidates.length} 候选` : "未取得（点重新跑）"}`,
    `工作流状态计数：候选${counts.candidate ?? 0}/观察${counts.watching ?? 0}/监控${counts.monitoring ?? 0}/持仓${counts.holding ?? 0}/已结${counts.settled ?? 0}`,
  ].join("\n"), [tab, stageKey, backend, briefing, funnelResult, counts]);

  const handleDateChange = (value: string) => {
    if (!value) return;
    setSearchParams((prev) => { const n = new URLSearchParams(prev); n.set("date", value); return n; });
  };
  const clearDate = () => setSearchParams((prev) => { const n = new URLSearchParams(prev); n.delete("date"); return n; });

  const headerActions = (
    <div className="flex items-center gap-2">
      <AskAiButton context={askAiContext} />
      <input type="date" value={selectedDate ?? ""} onChange={(e) => handleDateChange(e.target.value)} aria-label="历史日期" className="rounded-lg border border-border/40 bg-muted/10 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50" />
      {selectedDate && <Button variant="ghost" size="sm" onClick={clearDate}>今日</Button>}
      <Button variant="ghost" onClick={() => refetch()} disabled={refreshing} className="p-2" aria-label="刷新"><RefreshCw className={cn("h-4 w-4", refreshing && "animate-spin")} /></Button>
    </div>
  );

  return (
    <div className="space-y-4">
      <PageHeader title="选股工作流" subtitle="5-tab pipeline：T-1 → 语境 → 盘前 → 盘中 → 盘后" actions={headerActions} />

      <PipelineProgressBar current={tab === "t1" ? "t1" : tab === "ctx" ? "ctx" : tab === "pre" ? "pre" : tab === "intraday" ? "intraday" : "post"} />

      {/* 5 tab 导航 */}
      <div className="flex gap-2">
        {TABS.map((t) => (
          <Button key={t.key} variant={tab === t.key ? "primary" : "ghost"} size="sm" onClick={() => setTab(t.key)}>{t.label}</Button>
        ))}
      </div>

      {/* T-1 tab */}
      {tab === "t1" && <T1Tab date={selectedDate} />}

      {/* 语境 tab */}
      {tab === "ctx" && <ContextTab date={selectedDate} />}

      {/* 盘前 tab：①选股 → ②战法匹配 → ③仓位 */}
      {tab === "pre" && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Badge variant="default">① 选股</Badge> <ChevronRight className="h-3 w-3" /> <Badge variant="default">② 战法匹配</Badge> <ChevronRight className="h-3 w-3" /> <Badge variant="default">③ 仓位</Badge>
          </div>

          {/* ① 选股（缓存优先，拿不到才请求） */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold">① 选股（涨停池 R1→R2→R3 采集 + final，缓存优先）</h3>
              <Button variant="ghost" size="sm" onClick={() => { runFunnelReal(); refetch(); }}>重新跑</Button>
            </div>
            {funnelLoading ? <Skeleton className="h-64 w-full" /> : funnelResult ? (
              <>
                <FunnelLayers layers={funnelResult.layers} date={funnelResult.date} onPick={() => {}} />
                <SelectionPipeline finalCandidates={funnelResult.final_candidates} mode="funnel-only" date={funnelResult.date} rerunHandlers={candidatesApi} onPick={() => {}} />
              </>
            ) : (
              <GlassCard className="p-4"><p className="text-sm text-muted-foreground">选股池缓存未取得，点"重新跑"触发实跑（全市场漏斗，约 9 分钟后落缓存秒开）</p></GlassCard>
            )}
          </div>

          {/* ② 战法匹配（双视图） */}
          <div>
            <h3 className="mb-2 text-sm font-semibold">② 战法匹配（票×战法命中 + 按战法分列）</h3>
            <StrategyMatchMatrix date={selectedDate} />
          </div>

          {/* ③ 仓位 */}
          <div>
            <h3 className="mb-2 text-sm font-semibold">③ 仓位建议（PositionAdvisor + P2 仓位闸）</h3>
            <EntryCard to="/advisory" title="仓位建议" subtitle="PositionAdvisor + 龙虎榜风控 + 仓位闸" icon={BarChart3} date={selectedDate} />
          </div>

          {/* legacy 状态机折叠卡 */}
          <GlassCard className="p-4">
            <button type="button" onClick={() => setShowLegacy((v) => !v)} className="flex w-full items-center justify-between text-left">
              <div>
                <h3 className="font-semibold">状态机看板（legacy）</h3>
                <p className="text-xs text-muted-foreground/70">原盘前/盘中/盘后三阶段闭环——保留作降级视图</p>
              </div>
              <ChevronRight className={cn("h-4 w-4 transition-transform", showLegacy && "rotate-90")} />
            </button>
            {showLegacy && (
              <div className="mt-3 space-y-2">
                <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span>候选 {counts.candidate ?? 0}</span><span>观察 {counts.watching ?? 0}</span><span>监控 {counts.monitoring ?? 0}</span><span>持仓 {counts.holding ?? 0}</span><span>已结 {counts.settled ?? 0}</span>
                </div>
                <EntryCard to="/workflow/pre-market" title="盘前简报" subtitle="候选池筛选→战法匹配→仓位建议" icon={Clock} date={selectedDate} />
                <EntryCard to="/workflow/intraday" title="盘中监控" subtitle="实时监控→炸板预警→动态调仓" icon={TrendingUp} date={selectedDate} />
                <EntryCard to="/workflow/post-market" title="盘后复盘" subtitle="自动结算→LLM复盘→胜率更新" icon={BarChart3} date={selectedDate} />
              </div>
            )}
          </GlassCard>

          {/* 非涨停池站位（R12） */}
          <EntryCard to="/api/strategy/non-limitup-funnel" title="非涨停池（站位）" subtitle="板块成分股 + pattern_scan，独立来源（market_scan 战法主路径仍从涨停池）" icon={Building2} date={selectedDate} />
        </div>
      )}

      {/* 盘中 tab：统一监控（不分叉） */}
      {tab === "intraday" && (
        <div className="space-y-3">
          <GlassCard className="p-3">
            <p className="text-xs text-muted-foreground">盘中监控全市场统一（炸板=市场事件非战法事件），持仓行内标战法 max_hold</p>
            <div className="mt-1 text-xs text-muted-foreground/70">持仓 {counts.holding ?? 0} · 监控 {counts.monitoring ?? 0} · 观察 {counts.watching ?? 0}</div>
          </GlassCard>
          <EntryCard to="/workflow/intraday" title="实时监控" subtitle="持仓 + 候选盯盘（统一规则）" icon={TrendingUp} date={selectedDate} />
          <EntryCard to="/workflow/alerts" title="炸板预警" subtitle="炸板规则 C1-C6 全市场统一" icon={Zap} date={selectedDate} />
          <EntryCard to="/workflow/coach" title="盯盘教练" subtitle="时刻表 + 条件清单 + attention_mode" icon={Activity} date={selectedDate} />
        </div>
      )}

      {/* 盘后 tab：按战法聚合 */}
      {tab === "post" && (
        <div className="space-y-3">
          <EntryCard to="/workflow/post-market" title="盘后复盘" subtitle="结算（horizon=max_hold_days）→ LLM 复盘 → 胜率（by_strat 聚合）" icon={BarChart3} date={selectedDate} />
          <EntryCard to="/daily-review" title="每日复盘" subtitle="涨停/炸板/板块热度" icon={Clock} date={selectedDate} />
          <EntryCard to="/workflow/topology" title="拓扑展示" subtitle="关系网 · 漏斗流程 · 连板梯队（三视角）" icon={Share2} date={selectedDate} />
        </div>
      )}

      {/* 历史快照日期 chips */}
      {datesData?.dates && datesData.dates.length > 0 && (
        <GlassCard className="p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground/70">历史快照</span>
            {datesData.dates.map((d) => (
              <button key={d} type="button" onClick={() => handleDateChange(d)} className={cn("rounded-full border px-2 py-0.5 text-xs", d === selectedDate ? "border-primary/50 bg-primary/15 text-primary" : "border-border/40 bg-muted/10 text-muted-foreground hover:border-primary/30")}>{d}</button>
            ))}
          </div>
        </GlassCard>
      )}

      <Disclaimer compact />
    </div>
  );
}
