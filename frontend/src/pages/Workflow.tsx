// S092：三 Tab 容器重写——复盘(review) / 当日(today) / 前瞻(forward)。
// 替代 S087 6-tab / S084 两级 Tab。单一交易日锚 F + 时段推断三视图模型。
// URL ?view= 记录当前 Tab，?date= 记录手动选的复盘日（双 query 共存）。
// 顶部公共区：PageHeader + date picker + 锚条 + TaskStatusCard。
// useMarketClock 接入双定时器（15:00 复盘推进 + 17:15 F 推进）。
import { useEffect, useRef, useState, lazy, Suspense } from "react";
import { useSearchParams } from "react-router-dom";
import { RefreshCw, Activity, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { CollapsibleFold } from "@/components/ui/CollapsibleFold";
import { EntryCard } from "@/components/workflow/EntryCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { useDateTriplet, usePreMarketRefresh, usePreMarketDates } from "@/lib/query";
import { useMarketClock } from "@/lib/useMarketClock";
import { TaskStatusCard } from "@/components/workflow/TaskStatusCard";
import { PremarketSelectionSection } from "@/components/workflow/PremarketSelectionSection";
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

/** stage → 自动高亮 Tab（R12）：
 *  pre_market → 前瞻 | intraday → 当日 | post_transition → 复盘
 *  post_market → 前瞻 | non_trading → 复盘 */
function stageToDefaultTab(stage: string): TabKey {
  switch (stage) {
    case "pre_market": return "forward";
    case "intraday": return "today";
    case "post_transition": return "review";
    case "post_market": return "forward";
    case "non_trading": return "review";
    default: return "review";
  }
}

/** stage → 锚条时段标签文本 + 颜色 */
function stageLabel(stage: string): { text: string; color: string } {
  switch (stage) {
    case "pre_market":
      return { text: "盘前", color: "text-muted-foreground" };
    case "intraday":
      return { text: "盘中", color: "text-muted-foreground" };
    case "post_transition":
      return { text: "数据采集中 · 15:00-17:15", color: "text-warning" };
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

  // S092 内嵌补全：战法战绩表（原 S087 战法 Tab 内联）——registry + backtest 两 query
  const { data: registry } = useQuery({
    queryKey: ["strategy-registry"],
    queryFn: () => request<{ data: Array<{ code: string; name: string; max_hold_days: number; entry_condition: string }> }>(`/strategy/registry`),
    staleTime: 5 * 60_000,
  });
  const { data: backtest } = useQuery({
    queryKey: ["strategy-backtest"],
    queryFn: () => request<{ data: Array<{ strategy_code: string; strategy: string; win_rate: number; avg_return: number; sample_size: number }> }>(`/strategy/backtest?lookback_days=60`),
    staleTime: 5 * 60_000,
  });

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
          <>
            <PremarketSelectionSection date={triplet.forward} />
            {/* 战法战绩 + 参数 + 前向测试入口（原 S087 战法 Tab，R23 归复盘/前瞻） */}
            <CollapsibleFold title="战法战绩 · 参数 · 前向测试" subtitle="12 战法胜率/均收益/持有日 + 阈值配置入口" defaultOpen={false}>
              <GlassCard className="p-2">
                <h3 className="mb-2 px-2 font-semibold">战法战绩 + 参数</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border/40 text-muted-foreground/70">
                        <th className="px-2 py-1 text-left">战法</th>
                        <th className="px-2 py-1 text-right">胜率</th>
                        <th className="px-2 py-1 text-right">均收益%</th>
                        <th className="px-2 py-1 text-right">样本</th>
                        <th className="px-2 py-1 text-right">持有日</th>
                        <th className="px-2 py-1 text-left">入场条件</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(registry?.data ?? []).map((r) => {
                        const bt = (backtest?.data ?? []).find((b) => b.strategy_code === r.code);
                        return (
                          <tr key={r.code} className="border-b border-border/20 hover:bg-muted/10">
                            <td className="px-2 py-1">{r.name}</td>
                            <td className="px-2 py-1 text-right font-mono">
                              {bt ? `${(bt.win_rate * 100).toFixed(1)}%` : "—"}
                            </td>
                            <td className="px-2 py-1 text-right font-mono">{bt ? bt.avg_return : "—"}</td>
                            <td className="px-2 py-1 text-right">{bt?.sample_size ?? "—"}</td>
                            <td className="px-2 py-1 text-right">{r.max_hold_days}</td>
                            <td className="max-w-[16rem] truncate px-2 py-1 text-muted-foreground/70">
                              {r.entry_condition}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </GlassCard>
              <EntryCard
                to="/strategy/funnel/forward-test"
                title="前向测试 §44"
                subtitle="60 日复验 lift/winrate/validation_status"
                icon={Activity}
                date={urlDate}
              />
              <EntryCard
                to="/strategy/funnel/config"
                title="战法阈值配置"
                subtitle="S081 阈值 + funnel config（可改）"
                icon={Layers}
                date={urlDate}
              />
            </CollapsibleFold>
          </>
        )}
      </Suspense>

      <Disclaimer compact />
    </div>
  );
}
