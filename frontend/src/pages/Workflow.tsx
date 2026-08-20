// S087 v2：工作流 tab 按 pipeline 重设计——6-tab（T-1/语境/盘前/盘中/盘后/战法）。
// 主轴=交易时段（PipelineProgressBar current 驱动默认 tab）；战法 tab 跨阶段（战绩+参数）。
// 盘前三步①选股→②战法匹配→③仓位可折叠+线性流动箭头。战法/选股池两级 tab 融入①②。
// R15 6-tab 顶部；R14 战法 tab；R20 删非涨停池卡；R16 选股改名涨停池；R13 AskAiButton 每 tab。

import { Fragment, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Clock, TrendingUp, BarChart3, ChevronRight, RefreshCw, Activity, Share2, Zap, Layers } from "lucide-react";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { useQuery } from "@tanstack/react-query";
import { request } from "@/lib/api/client";
import { candidatesApi } from "@/lib/candidates";
import { CandidateFactorTable } from "@/components/workflow/CandidateFactorTable";
import { T1Tab } from "@/components/workflow/T1Tab";
import { ContextTab } from "@/components/workflow/ContextTab";
import { StrategyMatchMatrix } from "@/components/workflow/StrategyMatchMatrix";
import { useWorkflowStatus, usePreMarketBriefing, usePreMarketDates, useWorkflowStates } from "@/lib/query";

type TabKey = "t1" | "ctx" | "pre" | "intraday" | "post" | "strategy";

const TABS: { key: TabKey; label: string }[] = [
  { key: "t1", label: "T-1 数据" },
  { key: "ctx", label: "语境" },
  { key: "pre", label: "盘前" },
  { key: "intraday", label: "盘中" },
  { key: "post", label: "盘后" },
  { key: "strategy", label: "战法" },
];

function stageToTab(stageKey: string): TabKey {
  if (stageKey === "intraday") return "intraday";
  if (stageKey === "post-market") return "post";
  return "pre";
}

function EntryCard({ to, title, subtitle, icon: Icon, date }: { to: string; title: string; subtitle: string; icon: React.ComponentType<{ className?: string }>; date?: string }) {
  return (
    <Link to={date ? `${to}?date=${date}` : to} className="block">
      <GlassCard className="p-4 transition-all hover:ring-2 hover:ring-primary/30">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-primary/10 border border-primary/30"><Icon className="h-5 w-5 text-primary" /></div>
          <div className="flex-1">
            <div className="flex items-center gap-2"><h3 className="font-semibold">{title}</h3><ChevronRight className="h-4 w-4 text-muted-foreground/50" /></div>
            <p className="text-xs text-muted-foreground/70 mt-0.5">{subtitle}</p>
          </div>
        </div>
      </GlassCard>
    </Link>
  );
}

// 盘前三步可折叠卡
function StepSection({ index, title, subtitle, children, defaultOpen = true }: { index: number; title: string; subtitle?: string; children: React.ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <GlassCard className="p-3">
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 text-left">
        <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/20 text-xs font-medium text-primary">{index}</div>
        <h3 className="text-sm font-semibold">{title}</h3>
        {subtitle && <span className="text-xs text-muted-foreground/60">{subtitle}</span>}
        <ChevronRight className={cn("ml-auto h-4 w-4 transition-transform", open && "rotate-90")} />
      </button>
      {open && <div className="mt-3 space-y-2">{children}</div>}
    </GlassCard>
  );
}

export default function Workflow() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedDate = searchParams.get("date") ?? undefined;

  const { data: backend, isFetching, refetch } = useWorkflowStatus({ refetchInterval: selectedDate ? false : 60_000 });
  const { data: briefing } = usePreMarketBriefing(selectedDate);
  const { data: datesData } = usePreMarketDates();
  const { data: histStates } = useWorkflowStates(selectedDate);
  const counts = histStates?.counts ?? {};

  // 涨停池缓存优先（R16：读近多日缓存，拿不到 fallback POST 实跑）
  const { data: funnelCache, isLoading: funnelLoading } = useQuery({
    queryKey: ["s087-funnel-cache", selectedDate ?? "latest"],
    queryFn: () => candidatesApi.readFunnelCache(selectedDate),
    retry: false,
  });
  const funnelResult = funnelCache;

  // R14 战法 tab：战绩（backtest win_rate/avg_return/sample）+ 参数（registry max_hold/入场条件）
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

  const stageKey = (backend?.stage as string) ?? "pre-market";
  const [tab, setTab] = useState<TabKey>(stageToTab(stageKey));
  const [showLegacy, setShowLegacy] = useState(false);

  const askAiContext = useMemo(() => [
    `当前页面：选股工作流首页（6-tab pipeline）`,
    `当前 tab：${tab} | 后端 stage：${stageKey} | market_status：${backend?.market_status ?? "—"}`,
    `briefing status：${briefing?.status ?? "—"} | data_date：${briefing?.data_date ?? "—"}`,
    `涨停池缓存：${funnelResult ? `${funnelResult.final_candidates.length} 候选` : "未取得（点重新跑）"}`,
    `状态计数：候选${counts.candidate ?? 0}/观察${counts.watching ?? 0}/监控${counts.monitoring ?? 0}/持仓${counts.holding ?? 0}/已结${counts.settled ?? 0}`,
  ].join("\n"), [tab, stageKey, backend, briefing, funnelResult, counts]);

  // R24：盘中命中标的（briefing.scored_candidates 按 code 去重 + 命中战法）
  const hitTargets = useMemo(() => {
    const m = new Map<string, { code: string; name: string; strats: string[] }>();
    for (const s of briefing?.scored_candidates ?? []) {
      const e = m.get(s.code) ?? { code: s.code, name: s.name, strats: [] as string[] };
      if (!e.strats.includes(s.strategy_name)) e.strats.push(s.strategy_name);
      m.set(s.code, e);
    }
    return Array.from(m.values());
  }, [briefing?.scored_candidates]);

  // R23 仓位内嵌：advisory summary（推荐/自选/持仓，5min 缓存避免重算回测）
  const { data: advisory } = useQuery({
    queryKey: ["advisory-summary", selectedDate ?? "latest"],
    queryFn: () => request<{ recommendations: Array<{ code: string; name: string; action: string; win_rate: number; matched_strategy: string }>; watchlist: unknown[]; holdings: unknown[] }>(`/advisory/summary?limit=5`),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const recs = advisory?.recommendations ?? [];

  const handleDateChange = (value: string) => { if (value) setSearchParams((p) => { const n = new URLSearchParams(p); n.set("date", value); return n; }); };
  const clearDate = () => setSearchParams((p) => { const n = new URLSearchParams(p); n.delete("date"); return n; });

  const headerActions = (
    <div className="flex items-center gap-2">
      <AskAiButton context={askAiContext} />
      <input type="date" value={selectedDate ?? ""} onChange={(e) => handleDateChange(e.target.value)} aria-label="历史日期" className="rounded-lg border border-border/40 bg-muted/10 px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-primary/50" />
      {selectedDate && <Button variant="ghost" size="sm" onClick={clearDate}>今日</Button>}
      <Button variant="ghost" onClick={() => refetch()} disabled={isFetching} className="p-2" aria-label="刷新"><RefreshCw className={cn("h-4 w-4", isFetching && "animate-spin")} /></Button>
    </div>
  );

  return (
    <div className="space-y-3">
      {/* R15：6-tab 导航放页面最顶 */}
      <div className="flex gap-2">
        {TABS.map((t) => (
          <Button key={t.key} variant={tab === t.key ? "primary" : "ghost"} size="sm" onClick={() => setTab(t.key)}>{t.label}</Button>
        ))}
      </div>

      <PageHeader title="选股工作流" subtitle="6-tab pipeline：T-1→语境→盘前→盘中→盘后 + 战法管理" actions={headerActions} />

      {tab === "t1" && <T1Tab date={selectedDate} />}
      {tab === "ctx" && <ContextTab date={selectedDate} />}

      {/* 盘前 tab：①涨停池→②战法匹配→③仓位（可折叠+线性流动） */}
      {tab === "pre" && (
        <div className="space-y-3">
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Badge variant="default">① 涨停池</Badge><ChevronRight className="h-3 w-3" />
            <Badge variant="default">② 战法匹配</Badge><ChevronRight className="h-3 w-3" />
            <Badge variant="default">③ 仓位</Badge>
          </div>

          <StepSection index={1} title="涨停池" subtitle="R1→采集→final（缓存优先，R2/R3 采集层不过滤）">
            {/* 选股 pipeline 进度条 */}
            <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
              {["R1 涨停池", "R2/R3 采集", "final 候选", "战法匹配"].map((s, i) => (
                <Fragment key={s}>
                  <span className="rounded bg-primary/15 px-1.5 py-0.5 text-primary">{s}</span>
                  {i < 3 && <ChevronRight className="h-3 w-3" />}
                </Fragment>
              ))}
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground/70">R2/R3 是采集层（S084 下放战法层，标的数不变）</span>
              <Button variant="ghost" size="sm" onClick={() => { candidatesApi.runFunnel("all", selectedDate); refetch(); }}>重新跑</Button>
            </div>
            {funnelLoading ? <Skeleton className="h-64 w-full" /> : funnelResult ? (
              <CandidateFactorTable candidates={funnelResult.final_candidates} date={funnelResult.date} />
            ) : (
              <GlassCard className="p-4"><p className="text-sm text-muted-foreground">涨停池缓存未取得，点"重新跑"触发实跑（全市场漏斗，约 9 分钟落缓存秒开）</p></GlassCard>
            )}
          </StepSection>

          <StepSection index={2} title="战法匹配" subtitle="票×战法命中 + 按战法分列（括号=策略分 strategy_score）">
            <StrategyMatchMatrix date={selectedDate} />
          </StepSection>

          <StepSection index={3} title="仓位建议" subtitle="PositionAdvisor + P2 仓位闸/龙虎榜风控" defaultOpen={false}>
            {/* R23 内嵌仓位摘要（读 briefing P2 字段） */}
            <div className="space-y-1 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground/70">市场档位</span><span>{briefing?.market_phase ?? "—"}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground/70">仓位上限</span><span>{briefing?.market_phase_cap ?? "—"}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground/70">cap tier</span><span>{briefing?.position_cap_tier ?? "—"}</span></div>
              <div className="flex justify-between"><span className="text-muted-foreground/70">席位风控</span><span>{Object.keys(briefing?.seat_risk_flags ?? {}).length} 标</span></div>
            </div>
            {/* R23 advisory 推荐摘要 */}
            <div className="space-y-1 text-sm">
              <div className="flex justify-between"><span className="text-muted-foreground/70">推荐标的</span><span>{recs.length} 只</span></div>
              {recs.slice(0, 3).map((r) => (
                <div key={r.code} className="flex justify-between text-xs">
                  <span>{r.name}({r.code})</span>
                  <span className="text-muted-foreground/60">{r.matched_strategy} 胜率{(r.win_rate * 100).toFixed(0)}% {r.action}</span>
                </div>
              ))}
              {recs.length === 0 && <p className="text-xs text-muted-foreground">推荐未取得（advisory 计算中或无数据）</p>}
            </div>
            <EntryCard to="/advisory" title="仓位详情" subtitle="PositionAdvisor 推荐/自选/持仓三场景" icon={BarChart3} date={selectedDate} />
          </StepSection>

          {/* legacy 状态机折叠卡（R11 保留能力） */}
          <GlassCard className="p-3">
            <button type="button" onClick={() => setShowLegacy((v) => !v)} className="flex w-full items-center justify-between text-left">
              <div><h3 className="text-sm font-semibold">状态机看板（legacy）</h3><p className="text-xs text-muted-foreground/70">原三阶段闭环降级视图</p></div>
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
        </div>
      )}

      {/* 盘中 tab：统一监控 + 默认命中标的（R24） */}
      {tab === "intraday" && (
        <div className="space-y-3">
          <GlassCard className="p-3">
            <p className="text-xs text-muted-foreground">盘中监控全市场统一（炸板=市场事件非战法事件）；默认展示所有战法命中标的（R24）</p>
            <div className="mt-1 text-xs text-muted-foreground/70">持仓 {counts.holding ?? 0} · 监控 {counts.monitoring ?? 0} · 观察 {counts.watching ?? 0}</div>
          </GlassCard>
          {/* R24：命中标的列表 */}
          <GlassCard className="p-2">
            <h3 className="mb-2 px-2 text-sm font-semibold">命中标的（{hitTargets.length} 只）</h3>
            <div className="flex flex-wrap gap-1">
              {hitTargets.map((t) => (
                <span key={t.code} className="rounded border border-border/40 px-2 py-0.5 text-xs">
                  {t.name}({t.code}) <span className="text-muted-foreground/60">{t.strats.join("、")}</span>
                </span>
              ))}
              {hitTargets.length === 0 && <p className="text-sm text-muted-foreground">无命中标的（briefing 未 done 或无候选）</p>}
            </div>
          </GlassCard>
          <EntryCard to="/workflow/intraday" title="实时监控" subtitle="持仓 + 命中标的地盯盘（统一规则）" icon={TrendingUp} date={selectedDate} />
          <EntryCard to="/workflow/alerts" title="炸板预警" subtitle="炸板规则 C1-C6 全市场统一" icon={Zap} date={selectedDate} />
          <EntryCard to="/workflow/coach" title="盯盘教练" subtitle="时刻表 + 条件清单 + attention_mode" icon={Activity} date={selectedDate} />
        </div>
      )}

      {/* 盘后 tab */}
      {tab === "post" && (
        <div className="space-y-3">
          <EntryCard to="/workflow/post-market" title="盘后复盘" subtitle="结算（horizon=max_hold）→ LLM 复盘 → 胜率（by_strat 聚合）" icon={BarChart3} date={selectedDate} />
          <EntryCard to="/daily-review" title="每日复盘" subtitle="涨停/炸板/板块热度" icon={Clock} date={selectedDate} />
          <EntryCard to="/workflow/topology" title="拓扑展示" subtitle="关系网 · 漏斗流程 · 连板梯队" icon={Share2} date={selectedDate} />
        </div>
      )}

      {/* 战法 tab（R14）：战绩+参数表格 + 配置入口 */}
      {tab === "strategy" && (
        <div className="space-y-3">
          <GlassCard className="p-2">
            <h3 className="mb-2 px-2 font-semibold">战法战绩 + 参数（12 战法）</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="border-b border-border/40 text-muted-foreground/70">
                  <th className="px-2 py-1 text-left">战法</th>
                  <th className="px-2 py-1 text-right">胜率</th>
                  <th className="px-2 py-1 text-right">均收益%</th>
                  <th className="px-2 py-1 text-right">样本</th>
                  <th className="px-2 py-1 text-right">持有日</th>
                  <th className="px-2 py-1 text-left">入场条件</th>
                </tr></thead>
                <tbody>
                  {(registry?.data ?? []).map((r) => {
                    const bt = (backtest?.data ?? []).find((b) => b.strategy_code === r.code);
                    return (
                      <tr key={r.code} className="border-b border-border/20 hover:bg-muted/10">
                        <td className="px-2 py-1">{r.name}</td>
                        <td className="px-2 py-1 text-right font-mono">{bt ? `${(bt.win_rate * 100).toFixed(1)}%` : "—"}</td>
                        <td className="px-2 py-1 text-right font-mono">{bt ? bt.avg_return : "—"}</td>
                        <td className="px-2 py-1 text-right">{bt?.sample_size ?? "—"}</td>
                        <td className="px-2 py-1 text-right">{r.max_hold_days}</td>
                        <td className="px-2 py-1 truncate max-w-[16rem] text-muted-foreground/70">{r.entry_condition}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </GlassCard>
          <EntryCard to="/strategy/funnel/forward-test" title="前向测试 §44" subtitle="60 日复验 lift/winrate/validation_status" icon={Activity} date={selectedDate} />
          <EntryCard to="/strategy/funnel/config" title="战法阈值配置" subtitle="S081 阈值 + funnel config（可改）" icon={Layers} date={selectedDate} />
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
