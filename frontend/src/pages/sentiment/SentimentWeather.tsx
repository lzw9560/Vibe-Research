import { type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { RefreshCw, Settings, Cloud, History, Lightbulb, Zap, Globe } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Skeleton } from "@/components/ui/Skeleton";
import { TabBar } from "@/components/ui/TabBar";
import type { FuseRule, WeatherTimelineItem, WeatherStats, AuctionMetric, SealRiskMetric, FusePardonRecord } from "@/lib/api";
import {
  useSentimentWeatherLatest,
  useSentimentWeatherStrategy,
  useSentimentWeatherFuse,
  useSentimentWeatherTimeline,
  useSentimentWeatherAuction,
  useSentimentWeatherSealRisk,
  useSentimentWeatherPardon,
  useExitSignals,
} from "@/lib/query";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { WeatherHero } from "@/components/sentiment-weather/WeatherHero";
import { AuctionMetricsCard } from "@/components/sentiment-weather/AuctionMetricsCard";
import { SealRiskCard } from "@/components/sentiment-weather/SealRiskCard";
import { PardonManagement } from "@/components/sentiment-weather/PardonManagement";
import { MacroPanel } from "@/components/sentiment-weather/MacroPanel";
import { STITimelineChart } from "@/components/sti/STITimelineChart";

type TabId = "realtime" | "history" | "strategy" | "fuse" | "macro";

// S179 R3.5: 页内 TabBar 替代 Layout 二级 SUB_TABS（4 子路由切换）
const SENTIMENT_TABS: { key: TabId; label: string; icon: ReactNode }[] = [
  { key: "realtime", label: "实时天气", icon: <Cloud className="h-3.5 w-3.5" /> },
  { key: "history", label: "历史趋势", icon: <History className="h-3.5 w-3.5" /> },
  { key: "strategy", label: "策略建议", icon: <Lightbulb className="h-3.5 w-3.5" /> },
  { key: "fuse", label: "熔断规则", icon: <Zap className="h-3.5 w-3.5" /> },
  { key: "macro", label: "宏观", icon: <Globe className="h-3.5 w-3.5" /> },
];

const TAB_ROUTE: Record<TabId, string> = {
  realtime: "/sentiment/weather",
  history: "/sentiment/weather/history",
  strategy: "/sentiment/weather/strategy",
  fuse: "/sentiment/weather/fuse",
  macro: "/sentiment/weather/macro",
};

// 5 分钟自动刷新——原 loadData 每 5 分钟 Promise.all 全量重拉，现拆为 7 个 hook
// 各自 refetchInterval 5min，TanStack 会并行调度，效果与原 Promise.all 等价。
const REFRESH_MS = 5 * 60 * 1000;

export default function SentimentWeather() {
  const location = useLocation();
  const activeTab = (() => {
    if (location.pathname.includes("/history")) return "history" as TabId;
    if (location.pathname.includes("/strategy")) return "strategy" as TabId;
    if (location.pathname.includes("/fuse")) return "fuse" as TabId;
    if (location.pathname.includes("/macro")) return "macro" as TabId;
    return "realtime" as TabId;
  })();

  const navigate = useNavigate();
  const switchTab = (k: string): void => {
    navigate(TAB_ROUTE[k as TabId] ?? "/sentiment/weather");
  };

  // T9：原 useState/useEffect + Promise.all + setInterval → 7 个 TanStack Query hook。
  // hook data 在 v5 下退化为 {}（与 Health.tsx 同源），按 S013 T9 规约就地窄→宽 cast。
  const latestQ = useSentimentWeatherLatest({ refetchInterval: REFRESH_MS });
  const strategyQ = useSentimentWeatherStrategy({ refetchInterval: REFRESH_MS });
  const fuseQ = useSentimentWeatherFuse({ refetchInterval: REFRESH_MS });
  const timelineQ = useSentimentWeatherTimeline(30, { refetchInterval: REFRESH_MS });
  const auctionQ = useSentimentWeatherAuction({ refetchInterval: REFRESH_MS });
  const sealRiskQ = useSentimentWeatherSealRisk({ refetchInterval: REFRESH_MS });
  const pardonQ = useSentimentWeatherPardon({ refetchInterval: REFRESH_MS });

  // 派生数据槽（保持原变量名，JSX 渲染逻辑不动）
  // latest/strategy 端点返裸类型（无信封），hook data 已类型化，无需 cast。
  // fuse/timeline/auction/sealRisk/pardon 端点返 { data: {...} } 信封，但页面按解包后的字段访问，
  // 故这 5 个保留 as unknown as 窄→宽 cast（api 类型为信封，页面 Iface 为解包形态，类型不一致）。
  const weather = latestQ.data;
  // S216 B future: 次日强制离场信号（exit-signals endpoint，软 gate）
  const _exitDate = new Date().toISOString().slice(0, 10);
  const exitSignalsQ = useExitSignals(_exitDate);
  const strategy = strategyQ.data;
  const fuseRules = fuseQ.data as unknown as { rules: FuseRule[]; fuse_state: string; weather_state: string; updated_at: string } | undefined;
  const timeline = timelineQ.data as unknown as { timeline: WeatherTimelineItem[]; stats: WeatherStats } | undefined;
  const auctionMetrics = auctionQ.data as unknown as { auction_metrics: AuctionMetric[]; phase: string } | undefined;
  const sealRiskMetrics = sealRiskQ.data as unknown as { seal_risk_metrics: SealRiskMetric[] } | undefined;
  const pardonData = pardonQ.data as unknown as { pardon_records: FusePardonRecord[]; is_admin: boolean } | undefined;

  // 错误处理：原 Promise.all 任一失败即整体 setError 阻断全屏。
  // 这里 OR 7 个 hook 的 error —— 任一失败仍显示错误屏（保留原 UX，不静默吞错）。
  const firstError =
    latestQ.error ||
    strategyQ.error ||
    fuseQ.error ||
    timelineQ.error ||
    auctionQ.error ||
    sealRiskQ.error ||
    pardonQ.error ||
    null;
  const error = firstError ? (firstError instanceof Error ? firstError.message : String(firstError)) : null;

  // 加载态：首次全部在加载时显示骨架屏（与原 loading 语义一致）。
  const loading =
    latestQ.isLoading ||
    strategyQ.isLoading ||
    fuseQ.isLoading ||
    timelineQ.isLoading ||
    auctionQ.isLoading ||
    sealRiskQ.isLoading ||
    pardonQ.isLoading;

  // 刷新中：任一 hook 在后台拉取即为刷新中（用于刷新按钮自旋 + disabled）。
  const refreshing =
    latestQ.isFetching ||
    strategyQ.isFetching ||
    fuseQ.isFetching ||
    timelineQ.isFetching ||
    auctionQ.isFetching ||
    sealRiskQ.isFetching ||
    pardonQ.isFetching;

  const handleRefresh = () => {
    void latestQ.refetch();
    void strategyQ.refetch();
    void fuseQ.refetch();
    void timelineQ.refetch();
    void auctionQ.refetch();
    void sealRiskQ.refetch();
    void pardonQ.refetch();
  };

  const weatherState = weather?.weather_state ?? "未知";

  // Render tab content
  const renderTabContent = () => {
    if (loading) {
      return (
        <div className="space-y-6">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      );
    }

    if (error) {
      return (
        <GlassCard className="p-6">
          <div className="text-center text-red-400">
            <p className="text-lg font-medium">加载失败</p>
            <p className="mt-2 text-sm text-white/60">{error}</p>
            <Button variant="primary" size="md" onClick={handleRefresh} className="mt-4">
              重试
            </Button>
          </div>
        </GlassCard>
      );
    }

    switch (activeTab) {
      case "realtime":
        return (
          <div className="space-y-4">
            {/* Multi-Factor Breakdown */}
            <GlassCard className="p-5">
              <h3 className="text-sm font-medium text-foreground mb-3">多因子情绪分解</h3>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                {weather?.factors && Object.entries(weather.factors).map(([key, factor]) => (
                  <div key={key} className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-foreground/70">{factor.name}</span>
                      <span className="text-xs font-medium tabular-nums text-foreground">
                        {factor.score !== null && factor.score !== undefined ? factor.score.toFixed(1) : "--"}
                      </span>
                    </div>
                    <div className="h-1.5 rounded-full bg-foreground/10 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-blue-500 via-green-500 to-red-500 transition-all duration-500"
                        style={{ width: `${Math.min(100, Math.max(0, factor.score ?? 0))}%` }}
                      />
                    </div>
                    <div className="text-[10px] text-foreground/50 text-right">
                      {Math.round(factor.weight * 100)}%
                    </div>
                  </div>
                ))}
              </div>

              {/* Composite Score */}
              <div className="mt-4 pt-3 border-t border-border flex items-center justify-between">
                <div>
                  <p className="text-xs text-foreground/60">综合评分</p>
                  <p className="text-lg font-bold text-foreground">
                    {weather?.composite_score ?? "--"} <span className="text-xs text-foreground/50">/ 100</span>
                  </p>
                </div>
                <Badge variant={weatherState === "晴天" ? "success" : weatherState === "暴风雨" ? "danger" : "warning"}>
                  {weatherState}
                </Badge>
              </div>
              {strategy && (
                <div className="mt-2 text-xs text-foreground/60">
                  <p>{strategy.driver}</p>
                </div>
              )}
            </GlassCard>

            {/* Auction Metrics */}
            {auctionMetrics && (
              <AuctionMetricsCard metrics={auctionMetrics.auction_metrics} phase={auctionMetrics.phase} />
            )}

            {/* Seal Risk Metrics */}
            {sealRiskMetrics && <SealRiskCard metrics={sealRiskMetrics.seal_risk_metrics} />}

            {/* Strategy Recommendation */}
            <GlassCard className="p-5">
              <h3 className="text-sm font-medium text-foreground mb-3">今日策略建议</h3>
              <div className="space-y-2">
                {strategy?.strategies?.map((s) => (
                  <div
                    key={s.style}
                    className={`p-3 rounded-lg border ${
                      s.enabled
                        ? "border-green-500/20 bg-green-500/5"
                        : "border-foreground/5 bg-foreground/5 opacity-50"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">{s.enabled ? "✅" : "⚪"}</span>
                        <span className="text-sm font-medium text-foreground">{s.style}</span>
                      </div>
                      <Badge variant={s.match_score >= 70 ? "success" : s.match_score >= 40 ? "warning" : "danger"} className="text-xs">
                        {s.match_score}%
                      </Badge>
                    </div>
                    <p className="text-xs text-foreground/60 mb-2">{s.description}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {s.conditions?.map((c, i) => (
                        <span key={i} className="text-[10px] text-foreground/40 bg-foreground/5 px-1.5 py-0.5 rounded">
                          {c}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </GlassCard>

            {/* Fuse Rules Panel */}
            <GlassCard className="p-5">
              <h3 className="text-sm font-medium text-foreground mb-3">熔断规则监控</h3>
              <div className="space-y-2">
                {fuseRules?.rules.map((rule) => (
                  <div key={rule.id} className="flex items-center justify-between p-2.5 rounded-lg bg-foreground/5 border border-foreground/5">
                    <div className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full ${rule.status === "enabled" ? "bg-green-400" : "bg-gray-400"}`} />
                      <span className="text-sm text-foreground">{rule.name}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-foreground/50 hidden sm:inline">{rule.current_state}</span>
                      <Badge variant={rule.status === "enabled" ? "success" : "default"} className="text-xs">
                        {rule.status === "enabled" ? "已启用" : "已禁用"}
                      </Badge>
                    </div>
                  </div>
                ))}
              </div>
            </GlassCard>

            {/* Pardon Management */}
            {pardonData && (
              <PardonManagement
                isAdmin={pardonData.is_admin}
                // 原 onUpdate 手动 await api.sentimentWeatherPardon() 再 setPardonData；
                // 现交给 pardonQ.refetch() —— hook 重拉后 data 派生自动更新。
                onUpdate={() => { void pardonQ.refetch(); }}
              />
            )}

            {/* S216 B future: 次日强制离场信号（exit-signals，软 gate） */}
            <GlassCard className="p-4">
              <h3 className="mb-2 text-sm font-medium text-foreground">
                次日强制离场信号
              </h3>
              {exitSignalsQ.isLoading ? (
                <span className="text-xs text-muted-foreground">加载中…</span>
              ) : exitSignalsQ.error ? (
                <span className="text-xs text-red-500">离场信号加载失败</span>
              ) : !exitSignalsQ.data || exitSignalsQ.data.signals.length === 0 ? (
                <HonestEmptyState
                  message={exitSignalsQ.data?.note ?? "无离场信号"}
                  hint="持仓股竞价未高开或开盘破均线触发"
                />
              ) : (
                <div className="space-y-2">
                  <div className="text-xs text-muted-foreground">
                    {exitSignalsQ.data.date} · 触发{" "}
                    {exitSignalsQ.data.summary.triggered}/
                    {exitSignalsQ.data.summary.total}
                  </div>
                  <ul className="space-y-1">
                    {exitSignalsQ.data.signals.map((s) => (
                      <li
                        key={s.code}
                        className={`flex items-center gap-2 rounded border px-2 py-1 text-xs ${
                          s.triggered
                            ? "border-red-500/40 bg-red-500/5"
                            : "border-border"
                        }`}
                      >
                        <span className="font-medium">
                          {s.code} {s.name}
                        </span>
                        {s.triggered ? (
                          <span className="text-red-600">触发</span>
                        ) : (
                          <span className="text-muted-foreground">未触发</span>
                        )}
                        {s.reason && (
                          <span className="text-muted-foreground">{s.reason}</span>
                        )}
                        {s.data_status !== "ok" && (
                          <span className="text-amber-600">{s.data_status}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </GlassCard>
          </div>
        );

      case "history":
        return (
          <div className="space-y-4">
            <GlassCard className="p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-foreground">天气历史趋势 (近30天)</h3>
                {timeline && (
                  <div className="flex gap-3 text-xs">
                    <span className="text-success">晴天 {timeline.stats.晴天}天</span>
                    <span className="text-warning">阴天 {timeline.stats.阴天}天</span>
                    <span className="text-danger">暴风雨 {timeline.stats.暴风雨}天</span>
                    <span className="text-purple-400">极端反弹 {timeline.stats.极端反弹}天</span>
                  </div>
                )}
              </div>
              <STITimelineChart />
            </GlassCard>
          </div>
        );

      case "strategy":
        return (
          <div className="space-y-4">
            <GlassCard className="p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-foreground">策略推荐</h3>
                <Badge variant={strategyQ.data?.weather_state === "暴风雨" ? "danger" : "default"}>
                  {strategyQ.data?.weather_state ?? "—"}
                </Badge>
              </div>
              {strategyQ.isLoading ? (
                <p className="text-sm text-muted-foreground">加载中…</p>
              ) : strategyQ.error ? (
                <p className="text-sm text-muted-foreground">
                  加载失败：{strategyQ.error instanceof Error ? strategyQ.error.message : "未知"}
                </p>
              ) : (strategyQ.data?.strategies ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">无匹配策略。</p>
              ) : (
                <div className="space-y-2">
                  {(strategyQ.data?.strategies ?? []).map((s, i) => (
                    <div key={i} className="border border-border rounded-lg p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-foreground">{s.style}</span>
                        <Badge variant={s.enabled ? "success" : "default"}>
                          {s.enabled ? `推荐 ${s.match_score}` : "不推荐"}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{s.description}</p>
                      {s.order_config ? (
                        <p className="text-xs text-foreground/70 mt-1">下单：{s.order_config}</p>
                      ) : null}
                    </div>
                  ))}
                </div>
              )}
              {strategyQ.data?.risk_note ? (
                <p className="text-xs text-muted-foreground mt-3">{strategyQ.data.risk_note}</p>
              ) : null}
            </GlassCard>
          </div>
        );

      case "fuse":
        return (
          <div className="space-y-4">
            <GlassCard className="p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-medium text-foreground">熔断规则（软 gate，只提醒不锁死）</h3>
                <Badge variant={fuseQ.data?.data.fuse_state === "triggered" ? "danger" : "success"}>
                  {fuseQ.data?.data.fuse_state ?? "—"}
                </Badge>
              </div>
              {fuseQ.isLoading ? (
                <p className="text-sm text-muted-foreground">加载中…</p>
              ) : fuseQ.error ? (
                <p className="text-sm text-muted-foreground">
                  加载失败：{fuseQ.error instanceof Error ? fuseQ.error.message : "未知"}
                </p>
              ) : (fuseQ.data?.data.rules ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">无规则数据。</p>
              ) : (
                <div className="space-y-2">
                  {(fuseQ.data?.data.rules ?? []).map((r) => (
                    <div key={r.id} className="border border-border rounded-lg p-3">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-foreground">{r.name}</span>
                        <Badge variant={r.current_state === "triggered" ? "danger" : "success"}>
                          {r.current_state}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">{r.trigger_condition}</p>
                      <p className="text-xs text-foreground/60 mt-1">{r.description}</p>
                    </div>
                  ))}
                </div>
              )}
            </GlassCard>
          </div>
        );

      case "macro":
        return <MacroPanel />;

      default:
        return null;
    }
  };

  return (
    <div className="space-y-4">
      {/* Compact Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold">情绪气象站</h1>
          <p className="text-xs text-muted-foreground">市场情绪天气 · 策略自动切换中枢</p>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="sm" onClick={handleRefresh} disabled={refreshing} className="h-8 px-2">
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
          </Button>
          <Button variant="ghost" size="sm" className="h-8 px-2">
            <Settings className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* Page-local TabBar (S179 R3.5: 替代 Layout 二级 TabBar) */}
      <TabBar tabs={SENTIMENT_TABS} activeKey={activeTab} onChange={switchTab} />

      {/* Weather Hero */}
      <WeatherHero weather={weather ?? null} onRefresh={handleRefresh} refreshing={refreshing} />

      {/* Tab Content */}
      {renderTabContent()}

      <Disclaimer compact />
    </div>
  );
}
