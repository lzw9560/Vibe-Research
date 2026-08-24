// S092：三 Tab 容器重写——复盘(review) / 当日(today) / 前瞻(forward)。
// 替代 S087 6-tab / S084 两级 Tab。单一交易日锚 F + 时段推断三视图模型。
// URL ?view= 记录当前 Tab，?date= 记录手动选的复盘日（双 query 共存）。
// 顶部公共区：PageHeader + date picker + 锚条 + TaskStatusCard。
// useMarketClock 接入双定时器（15:00 复盘推进 + 17:15 F 推进）。
import { useEffect, useRef, useState, lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { CollapsibleFold } from "@/components/ui/CollapsibleFold";
import { EntryCard } from "@/components/workflow/EntryCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useDateTriplet, usePreMarketRefresh, usePreMarketDates, usePreMarketBriefing } from "@/lib/query";
import { useCrossValidationGroups } from "@/lib/query/useCrossValidation";
import { useMarketClock } from "@/lib/useMarketClock";
import { TaskStatusCard } from "@/components/workflow/TaskStatusCard";
import { PremarketSelectionSection } from "@/components/workflow/PremarketSelectionSection";
import CandidateFunnelEmbed from "@/components/workflow/CandidateFunnelEmbed";
import { CrossValidationBadge } from "@/components/workflow/CrossValidationBadge";
import { P2RiskPanel } from "@/components/workflow/P2RiskPanel";
import { WeatherDecisionBar } from "@/components/workflow/WeatherDecisionBar";
import { ContextTab } from "@/components/workflow/ContextTab";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StrategySubPipelineView } from "@/components/pipeline/StrategySubPipelineView";
import { NonLimitupLane } from "@/components/pipeline/NonLimitupPlaceholder";
import type { DateTripletResponse } from "@/lib/api";

// 三视图组件懒加载（已有路由也懒加载，此处统一）
const PostMarketReview = lazy(() => import("./workflow/PostMarketReview"));
const PreMarketBriefing = lazy(() => import("./workflow/PreMarketBriefing"));

type TabKey = "review" | "today" | "forward";

const TABS: { key: TabKey; label: string }[] = [
  { key: "review", label: "复盘" },
  { key: "today", label: "当日" },
  { key: "forward", label: "前瞻" },
];

/** stage → 自动高亮 Tab（S093 R3：加 pre_open→当日）：
 *  pre_market → 前瞻 | pre_open → 当日 | intraday → 当日 | post_transition → 复盘
 *  post_market → 前瞻 | non_trading → 复盘 */
function stageToDefaultTab(stage: string): TabKey {
  switch (stage) {
    case "pre_market": return "forward";
    case "pre_open": return "today";
    case "intraday": return "today";
    case "post_transition": return "review";
    case "post_market": return "forward";
    case "non_trading": return "review";
    default: return "review";
  }
}

/** stage → 锚条时段标签文本 + 颜色（S093 R3：加 pre_open + post_transition 改 15:30） */
function stageLabel(stage: string): { text: string; color: string } {
  switch (stage) {
    case "pre_market":
      return { text: "盘前", color: "text-muted-foreground" };
    case "pre_open":
      return { text: "集合竞价 · 09:00-09:30", color: "text-muted-foreground" };
    case "intraday":
      return { text: "盘中", color: "text-muted-foreground" };
    case "post_transition":
      return { text: "数据采集中 · 15:30-17:15", color: "text-warning" };
    case "post_market":
      return { text: "数据就绪 · 17:15 后", color: "text-success" };
    case "non_trading":
      return { text: "非交易日", color: "text-muted-foreground" };
    default:
      return { text: stage, color: "text-muted-foreground" };
  }
}

/** 锚条组件：显示 F + stage + 各视图数据日 */
function AnchorBar({ triplet, isManual }: { triplet: DateTripletResponse; isManual: boolean }) {
  const sl = stageLabel(triplet.stage);
  // P6 修复：手动回看历史日时前瞻数据已存在，不显"待产出"
  const isPending = triplet.stage === "post_transition" && !isManual;
  return (
    <GlassCard className="mb-3 grid grid-cols-1 gap-3 p-4 sm:grid-cols-[auto_1fr_auto] sm:items-center">
      {/* 左：F 锚值 */}
      <div className="flex flex-col gap-0.5">
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">锚定交易日 F</span>
        <span className="font-mono text-base font-bold text-primary">{triplet.F}</span>
      </div>
      {/* 中：三视图数据日 */}
      <div className="flex items-center justify-center gap-0 text-xs">
        <div className="flex flex-col items-center gap-0.5 px-2">
          <span className="text-[10px] text-muted-foreground">复盘</span>
          <span className="font-mono text-[13px] font-semibold text-foreground">{triplet.review}</span>
        </div>
        <div className="mx-1 h-px w-10 bg-border sm:w-10" />
        <div className="flex flex-col items-center gap-0.5 px-2">
          <span className="text-[10px] text-muted-foreground">当日</span>
          <span className="font-mono text-[13px] font-semibold text-muted-foreground">{triplet.today}</span>
        </div>
        <div className="mx-1 h-px w-10 bg-border" />
        <div className="flex flex-col items-center gap-0.5 px-2">
          <span className="text-[10px] text-muted-foreground">前瞻</span>
          {isPending ? (
            <span className="font-mono text-[13px] font-semibold text-warning">待 17:15 产出</span>
          ) : (
            <span className="font-mono text-[13px] font-semibold text-muted-foreground">{triplet.forward}</span>
          )}
        </div>
      </div>
      {/* 右：时段标签 */}
      <div className="flex items-center justify-start gap-2 sm:justify-end">
        <span
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold whitespace-nowrap",
            triplet.stage === "post_transition" && "border-warning/35 bg-warning/10 text-warning",
            triplet.stage === "post_market" && "border-success/35 bg-success/10 text-success",
            triplet.stage !== "post_transition" && triplet.stage !== "post_market" && "border-border/50 bg-muted/10 text-muted-foreground",
          )}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          {sl.text}
        </span>
      </div>
    </GlassCard>
  );
}

export default function Workflow() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlDate = searchParams.get("date") ?? undefined;
  const urlView = (searchParams.get("view") as TabKey | null) ?? undefined;

  // dateTriplet：用户手动选 date 时传给后端覆盖 F；不传则按时段自动算
  const { data: triplet } = useDateTriplet(urlDate);

  // view 状态：从 URL 初始化，用户切 Tab 时更新 URL
  const [view, setView] = useState<TabKey>(urlView ?? "review");
  // 跟踪用户是否手动切过 Tab——未手动切时 stage 变化自动高亮（R12）
  // P1 修复：URL 显式带 ?view= 时视为用户已选，不被自动高亮覆盖
  const userTouchedTab = useRef(!!urlView);

  // 自动高亮：用户未手动切 Tab 时，stage 变化 → 自动切 Tab
  useEffect(() => {
    if (!userTouchedTab.current && triplet) {
      const autoTab = stageToDefaultTab(triplet.stage);
      setView(autoTab);
    }
  }, [triplet?.stage]);

  // 同步 view 到 URL（用户手动切 Tab 时）
  useEffect(() => {
    setSearchParams(
      (p) => {
        const n = new URLSearchParams(p);
        n.set("view", view);
        return n;
      },
      { replace: true },
    );
  }, [view, setSearchParams]);

  // 双定时器接入：next_*_at 驱动；用户手动选 date 时 is_manual=true 暂停定时器
  const refresh = usePreMarketRefresh();
  useMarketClock({
    next_review_advance_at: triplet?.next_review_advance_at ?? 0,
    next_f_advance_at: triplet?.next_f_advance_at ?? 0,
    non_trading: triplet?.non_trading ?? false,
    is_manual: !!urlDate,
    onFAdvance: () => {
      // 17:15 F 推进后刷新简报（R2 全量刷新三视图）
      refresh.mutate(undefined);
    },
  });

  // S092 内嵌补全：历史快照日期 chips（原 S087 usePreMarketDates）
  const { data: datesData } = usePreMarketDates();

  // S093 R13：战法战绩表移出三 Tab → /strategy 独立路由（S5 承接）。
  // 此处不再内联 registry/backtest query——删战法战绩折叠区。

  const handleDateChange = (value: string) => {
    if (value) {
      setSearchParams((p) => {
        const n = new URLSearchParams(p);
        n.set("date", value);
        return n;
      });
    }
  };
  const clearDate = () => {
    setSearchParams((p) => {
      const n = new URLSearchParams(p);
      n.delete("date");
      return n;
    });
  };

  const handleTabClick = (tab: TabKey) => {
    userTouchedTab.current = true;
    setView(tab);
  };

  // AskAi 上下文
  const askAiContext = [
    "当前页面：选股工作流（三 Tab 容器）",
    `当前 Tab：${view} | 时段：${triplet?.stage ?? "未取得"} | F：${triplet?.F ?? "未取得"}`,
    `复盘数据日：${triplet?.review ?? "未取得"} | 当日：${triplet?.today ?? "未取得"} | 前瞻：${triplet?.forward ?? "未取得"}`,
    urlDate ? `手动选的复盘日：${urlDate}（定时器已暂停）` : "自动态（定时器激活）",
  ].join("\n");

  return (
    <div className="space-y-3">
      {/* 顶部公共区 */}
      <PageHeader
        title="选股工作流"
        subtitle="单一交易日锚 F · 时段推断三视图 · 复盘 / 当日 / 前瞻"
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton context={askAiContext} />
            {/* date picker（容器级管控 ?date=） */}
            <input
              type="date"
              value={urlDate ?? ""}
              onChange={(e) => handleDateChange(e.target.value)}
              aria-label="选择复盘日 F"
              className="rounded-lg border border-border/40 bg-muted/10 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
            {urlDate && (
              <Button variant="ghost" size="sm" onClick={clearDate}>
                清除日期
              </Button>
            )}
            <Button
              variant="ghost"
              onClick={() => window.location.reload()}
              className="p-2"
              aria-label="刷新"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        }
      />

      {/* 锚条 */}
      {triplet ? (
        <AnchorBar triplet={triplet} isManual={!!urlDate} />
      ) : (
        <GlassCard className="mb-3 p-4 text-sm text-muted-foreground">dateTriplet 加载中…</GlassCard>
      )}

      {/* 任务状态卡片（公共区常驻） */}
      <TaskStatusCard
        stage={triplet?.stage ?? "non_trading"}
        isTradingDay={triplet?.is_trading_day ?? false}
      />

      {/* S093 T21：战法入口卡片（公共区常驻，锚条下方）——战法战绩移出三 Tab 后的入口 */}
      <EntryCard
        to="/strategy"
        title="战法管理"
        subtitle="战绩 · 前向测试 · 阈值配置"
      />

      {/* S092 内嵌补全：历史快照日期 chips（原 S087 usePreMarketDates） */}
      {datesData?.dates && datesData.dates.length > 0 && (
        <GlassCard className="p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground/70">历史快照</span>
            {datesData.dates.map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => handleDateChange(d)}
                className={cn(
                  "rounded-full border px-2 py-0.5 text-xs",
                  d === urlDate
                    ? "border-primary/50 bg-primary/15 text-primary"
                    : "border-border/40 bg-muted/10 text-muted-foreground hover:border-primary/30",
                )}
              >
                {d}
              </button>
            ))}
          </div>
        </GlassCard>
      )}

      {/* 三 Tab 切换 */}
      <div className="inline-flex gap-1 rounded-xl border border-border/40 bg-muted/30 p-1">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => handleTabClick(t.key)}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-5 py-2 text-sm font-semibold transition-all",
              view === t.key
                ? "bg-primary/16 text-primary shadow-[0_0_18px_hsl(15_89%_56%/0.2)]"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full bg-current transition-opacity",
                view === t.key ? "opacity-100" : "opacity-0",
              )}
            />
            {t.label}
          </button>
        ))}
      </div>

      {/* 三 Tab 内容 */}
      <Suspense fallback={<div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>}>
        {view === "review" && triplet && (
          <PostMarketReview
            date={triplet.review}
            reviewAdvanced={triplet.review_advanced}
            stage={triplet.stage}
          />
        )}
        {view === "today" && triplet && (
          <PreMarketBriefing date={triplet.today} stage={triplet.stage} />
        )}
        {view === "forward" && triplet && (
          <ForwardTabSection F={triplet.F} forward={triplet.forward} urlDate={urlDate} />
        )}
      </Suspense>

      <Disclaimer compact />
    </div>
  );
}

// ===========================================================================
// S094 附录 A：前瞻 Tab 双 pipeline 互斥切换重构。
// 布局：前置共享区 → [涨停叉 | 非涨停叉] 切换（默认涨停）→ 当前叉内容 → 后置共享区
// 前置共享区（辅助角色，只显一次）：板块轮动 · 语境(ContextTab) · 情绪天气(WeatherDecisionBar)
// 涨停叉：① 涨停股池+漏斗 → ② 战法匹配（7战法分组视图）→ ③ breakout → ④ 交叉验证
// 非涨停叉：⑤ 选股宇宙 → ⑥ K线形态 → ⑦ 非涨停战法分组视图 → ⑧ 候选终选
// 后置共享区：风控非对称 + P2 仓位（advisory 摘要并入）
// 删除（附录 A4）：FactorSection（因子漏斗）｜ advisory 仓位详情入口（并入后置共享区）｜ T1Tab ｜ "辅助决策" CollapsibleFold
// 板块轮动只渲染一个实例（前置共享区）——SelectionPipeline 内部不渲染（sharedSectorRotation=true）
// 数据源：usePreMarketBriefing(F) + useCrossValidationGroups(F, forward)
// 工程底线：不臆造——query 无数据返空数组；组件缺数据返 null / "—"。
// 历史统计特征标注：参考值，非执行指令；市场有风险。
// ===========================================================================

type ForwardLane = "limitup" | "non-limitup";

function ForwardTabSection({ F, forward, urlDate }: { F: string; forward: string; urlDate?: string }) {
  // 数据源：前瞻简报（F 日收盘数据算出来的选 T+1 标的结果）
  const { data: briefing, isLoading: briefingLoading } = usePreMarketBriefing(F);
  // 交叉验证：漏斗 final_candidates ∩ breakout top-N
  const cv = useCrossValidationGroups(F, forward);
  // advisory 仓位推荐摘要
  const { data: advisory } = useQuery({
    queryKey: ["advisory-summary"],  // S094 audit: advisory 是 latest（backend /advisory/summary 不支持 date），非 per-F
    queryFn: () => api.advisorySummary(5),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const recs = advisory?.recommendations ?? [];

  // S094 附录 A1：activeLane 切换状态提升到 ForwardTabSection——
  // 前置/后置共享区在切换两叉时不抖动（前置共享区只渲染一次板块轮动）
  const [activeLane, setActiveLane] = useState<ForwardLane>("limitup");

  const funnelLayers = briefing?.funnel_layers;

  return (
    <>
      {/* ============ 前置共享区（辅助角色，只显一次） ============ */}
      <PreSharedRegion F={F} briefing={briefing} />

      {/* ============ [涨停叉 | 非涨停叉] 切换（默认涨停，无"全部"选项） ============ */}
      <ForwardLaneSwitcher activeLane={activeLane} onChange={setActiveLane} />

      {/* ============ 当前叉内容（互斥，一次只显一叉） ============ */}
      {activeLane === "limitup" ? (
        <LimitupLaneContent
          briefing={briefing}
          F={F}
          forward={forward}
          funnelLayers={funnelLayers}
          cv={cv}
        />
      ) : (
        <NonLimitupLaneContent
          briefing={briefing}
          F={F}
        />
      )}

      {/* ============ 后置共享区：风控 + P2 仓位（advisory 摘要并入） ============ */}
      <PostSharedRegion briefing={briefing} recs={recs} urlDate={urlDate} />

      {briefingLoading && !briefing && (
        <GlassCard className="p-4 text-sm text-muted-foreground">前瞻简报加载中…</GlassCard>
      )}
    </>
  );
}

/** 前置共享区：板块轮动 · 语境(ContextTab) · 情绪天气(WeatherDecisionBar) */
function PreSharedRegion({ F, briefing }: { F: string; briefing: import("@/lib/api").PreMarketBriefing | null | undefined }) {
  return (
    <CollapsibleFold title="前置共享区" subtitle="板块轮动 · 语境 · 情绪天气" defaultOpen={true}>
      {/* 板块轮动（只渲染一个实例，见 SelectionPipeline 内 sharedSectorRotation=true 跳过内部渲染） */}
      <ContextTab date={F} />
      {/* 情绪天气（WeatherDecisionBar）— 天气影响选股决策 */}
      {briefing?.sentiment_context && (
        <div>
          <SectionHeader title="情绪天气决策" subtitle="S063 情绪天气 → 战法推荐/不推荐" />
          <div className="mt-2">
            <WeatherDecisionBar ctx={briefing.sentiment_context} />
          </div>
        </div>
      )}
    </CollapsibleFold>
  );
}

/** [涨停叉 | 非涨停叉] 切换——原生 button + tailwind，默认涨停，无"全部"选项 */
function ForwardLaneSwitcher({ activeLane, onChange }: { activeLane: ForwardLane; onChange: (lane: ForwardLane) => void }) {
  const options: { value: ForwardLane; label: string }[] = [
    { value: "limitup", label: "涨停叉" },
    { value: "non-limitup", label: "非涨停叉" },
  ];
  return (
    <div className="my-2 inline-flex rounded-lg border border-border/40 bg-card/30 p-0.5">
      {options.map((opt) => {
        const active = activeLane === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={
              active
                ? "rounded-md bg-primary/15 px-4 py-1.5 text-sm font-medium text-primary transition-colors"
                : "rounded-md px-4 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-card/60 hover:text-foreground"
            }
            aria-pressed={active}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** 涨停叉内容：① 涨停股池+漏斗 → ② 战法匹配（7战法分组视图）→ ③ breakout → ④ 交叉验证 */
function LimitupLaneContent({
  briefing, F, forward, funnelLayers, cv,
}: {
  briefing: import("@/lib/api").PreMarketBriefing | null | undefined;
  F: string;
  forward: string;
  funnelLayers: import("@/lib/api").FunnelLayer[] | undefined;
  cv: import("@/lib/query/useCrossValidation").CrossValidationGroups;
}) {
  return (
    <div className="space-y-2">
      {/* ① 涨停股池+漏斗（CandidateFunnelEmbed，date=F）—— R1 涨停池全量直通 */}
      <CandidateFunnelEmbed
        date={briefing?.data_date ?? F}
        onPick={() => { /* 前瞻 Tab 不开抽屉（S4 WatchlistBoard 接管） */ }}
        snapshotLayers={briefing?.from_snapshot ? funnelLayers : funnelLayers}
        scoredCandidates={briefing?.scored_candidates}
        marketScanScored={briefing?.market_scan_scored}
        finalCandidates={briefing?.final_candidates}
        ztPoolSize={briefing?.market_emotion?.zt_count ?? undefined}
        sharedSectorRotation={true}  // 附录 A2：板块轮动由前置共享区统一渲染
      />

      {/* ② 涨停战法匹配（7 战法分组视图）—— 替代原独立 CollapsibleFold(StrategyMatchMatrix) */}
      <StrategySubPipelineView
        scoredCandidates={briefing?.scored_candidates}
        marketScanScored={briefing?.market_scan_scored}
        lane="limitup"
      />

      {/* ③ breakout 弱信号（PremarketSelectionSection，date=forward） */}
      <PremarketSelectionSection date={forward} />

      {/* ④ 交叉验证徽章（漏斗∩breakout 双重确认） */}
      <CrossValidationSummary groups={cv} />
    </div>
  );
}

/** 非涨停叉内容：⑤⑥⑦⑧ 全部在 NonLimitupLane 内部（⑦复用 StrategySubPipelineView） */
function NonLimitupLaneContent({
  briefing, F,
}: {
  briefing: import("@/lib/api").PreMarketBriefing | null | undefined;
  F: string;
}) {
  return (
    <div className="space-y-2">
      {/* ⑤⑥⑦⑧ 选股宇宙 + K线形态 + 战法匹配 + 候选终选（NonLimitupLane 自管四节点结构） */}
      <NonLimitupLane
        date={briefing?.data_date ?? F}
        candidates={briefing?.market_scan_scored}
      />
    </div>
  );
}

/** 后置共享区：风控非对称 + P2 仓位 + advisory 摘要（并入此区，不重复展示） */
function PostSharedRegion({
  briefing, recs, urlDate,
}: {
  briefing: import("@/lib/api").PreMarketBriefing | null | undefined;
  recs: import("@/lib/api").AdvisoryItem[];
  urlDate?: string;
}) {
  return (
    <CollapsibleFold title="后置共享区" subtitle="风控非对称 · P2 仓位 · 仓位推荐摘要" defaultOpen={true}>
      {/* 风控非对称（§44 唯一 lever：亏小赚大） */}
      <RiskAsymmetryCard />

      {/* P2 仓位闸 + 龙虎榜风控面板 */}
      {briefing && <P2RiskPanel briefing={briefing} />}

      {/* advisory 仓位推荐摘要（并入后置共享区，不单独展示） */}
      {recs.length > 0 && (
        <GlassCard className="p-4">
          <p className="mb-2 text-sm font-medium">仓位推荐摘要</p>
          <p className="text-xs text-muted-foreground/70">推荐标的 {recs.length} 只</p>
          <div className="mt-2 space-y-1">
            {recs.slice(0, 3).map((r) => (
              <div key={r.code} className="flex min-w-0 items-center justify-between gap-2 text-xs">
                <span className="min-w-0 flex-1 truncate">{r.name}({r.code})</span>
                <span className="shrink-0 text-right text-muted-foreground/60">
                  {r.matched_strategy ?? "—"} 胜率{r.win_rate != null ? `${(r.win_rate * 100).toFixed(0)}%` : "—"} {r.action}
                </span>
              </div>
            ))}
          </div>
          {/* advisory 仓位详情入口（并入后置共享区，独立页 /advisory 保留为详情入口） */}
          <div className="mt-3">
            <EntryCard to="/advisory" title="仓位详情" subtitle="PositionAdvisor 推荐/自选/持仓三场景" date={urlDate} />
          </div>
        </GlassCard>
      )}
    </CollapsibleFold>
  );
}

/** 风控非对称卡片（§44 唯一 lever） */
function RiskAsymmetryCard() {
  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-amber-300">风控非对称</span>
        <span className="rounded bg-amber-500/20 px-1 text-[10px] text-amber-300">唯一 lever</span>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground sm:grid-cols-3">
        <span>仓位 3% × 日历</span>
        <span>止损 −4%</span>
        <span>止盈 +8%</span>
        <span>max 3 仓</span>
        <span>max 持 3 日</span>
        <span>R:R ≈ 1:2</span>
      </div>
      <div className="mt-1 text-[10px] text-amber-200/70">
        §44 信号全无 validated edge → 盈利靠风控非对称（小仓+紧止损+非对称 R:R+短持），非信号
      </div>
    </div>
  );
}

/** 交叉验证摘要——三组分组 + 徽章（spec R4④ + AC9） */
function CrossValidationSummary({ groups }: { groups: import("@/lib/query/useCrossValidation").CrossValidationGroups }) {
  if (groups.isLoading) {
    return <GlassCard className="mb-3 p-4 text-sm text-muted-foreground">交叉验证计算中…</GlassCard>;
  }
  const hasData = groups.dual.length > 0 || groups.funnelOnly.length > 0 || groups.breakoutOnly.length > 0;
  if (!hasData) return null;
  return (
    <GlassCard className="mb-3 p-4">
      <div className="flex items-center gap-2 border-b border-border/30 pb-2">
        <span className="text-sm font-semibold">交叉验证</span>
        <span className="text-xs text-muted-foreground/70">漏斗 ∩ breakout</span>
      </div>
      <div className="mt-3 space-y-2">
        {groups.dual.length > 0 && (
          <div className="flex items-start gap-2">
            <CrossValidationBadge group="dual" />
            <span className="text-xs font-mono text-muted-foreground">{groups.dual.length} 只 · {groups.dual.join(", ")}</span>
          </div>
        )}
        {groups.funnelOnly.length > 0 && (
          <div className="flex items-start gap-2">
            <CrossValidationBadge group="funnelOnly" />
            <span className="text-xs font-mono text-muted-foreground">{groups.funnelOnly.length} 只 · {groups.funnelOnly.join(", ")}</span>
          </div>
        )}
        {groups.breakoutOnly.length > 0 && (
          <div className="flex items-start gap-2">
            <CrossValidationBadge group="breakoutOnly" />
            <span className="text-xs font-mono text-muted-foreground">{groups.breakoutOnly.length} 只 · {groups.breakoutOnly.join(", ")}</span>
          </div>
        )}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground/60">参考值，非执行指令；市场有风险</p>
    </GlassCard>
  );
}
