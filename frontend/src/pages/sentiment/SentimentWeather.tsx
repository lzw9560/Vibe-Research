import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { RefreshCw, Settings } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import type { WeatherState, StrategyRecommendation, FuseRule, WeatherTimelineItem, WeatherStats, AuctionMetric, SealRiskMetric, FusePardonRecord } from "@/lib/api";
import { WeatherHero } from "@/components/sentiment-weather/WeatherHero";
import { AuctionMetricsCard } from "@/components/sentiment-weather/AuctionMetricsCard";
import { SealRiskCard } from "@/components/sentiment-weather/SealRiskCard";
import { PardonManagement } from "@/components/sentiment-weather/PardonManagement";
import { STITimelineChart } from "@/components/sti/STITimelineChart";

type TabId = "realtime" | "history" | "strategy" | "fuse";

export default function SentimentWeather() {
  const location = useLocation();
  const activeTab = (() => {
    if (location.pathname.includes("/history")) return "history" as TabId;
    if (location.pathname.includes("/strategy")) return "strategy" as TabId;
    if (location.pathname.includes("/fuse")) return "fuse" as TabId;
    return "realtime" as TabId;
  })();

  // Data state
  const [weather, setWeather] = useState<WeatherState | null>(null);
  const [strategy, setStrategy] = useState<StrategyRecommendation | null>(null);
  const [fuseRules, setFuseRules] = useState<{ rules: FuseRule[]; updated_at: string } | null>(null);
  const [timeline, setTimeline] = useState<{ timeline: WeatherTimelineItem[]; stats: WeatherStats } | null>(null);
  const [auctionMetrics, setAuctionMetrics] = useState<{ auction_metrics: AuctionMetric[]; phase: string } | null>(null);
  const [sealRiskMetrics, setSealRiskMetrics] = useState<{ seal_risk_metrics: SealRiskMetric[] } | null>(null);
  const [pardonData, setPardonData] = useState<{ pardon_records: FusePardonRecord[]; is_admin: boolean } | null>(null);

  // UI state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  // Load data
  const loadData = async () => {
    try {
      setError(null);
      const [weatherData, strategyData, fuseData, timelineData, auctionData, sealRiskData, pardonRecordsData] = await Promise.all([
        api.sentimentWeatherLatest(),
        api.sentimentWeatherStrategy(),
        api.sentimentWeatherFuse(),
        api.sentimentWeatherTimeline(30),
        api.sentimentWeatherAuction(),
        api.sentimentWeatherSealRisk(),
        api.sentimentWeatherPardon(),
      ]);
      setWeather(weatherData as WeatherState);
      setStrategy(strategyData as StrategyRecommendation);
      setFuseRules(fuseData as unknown as { rules: FuseRule[]; updated_at: string });
      setTimeline(timelineData as unknown as { timeline: WeatherTimelineItem[]; stats: WeatherStats });
      setAuctionMetrics(auctionData.data as { auction_metrics: AuctionMetric[]; phase: string });
      setSealRiskMetrics(sealRiskData.data as { seal_risk_metrics: SealRiskMetric[] });
      setPardonData(pardonRecordsData.data as { pardon_records: FusePardonRecord[]; is_admin: boolean });
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const weatherState = weather?.weather_state ?? "未知";

  useEffect(() => {
    setLoading(true);
    loadData();
    // Auto-refresh every 5 minutes
    const interval = setInterval(loadData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    loadData();
  };

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
                {strategy?.strategies.map((s) => (
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
                      {s.conditions.map((c, i) => (
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
                onUpdate={async () => {
                  const data = await api.sentimentWeatherPardon();
                  setPardonData(data.data);
                }}
              />
            )}
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
              <h3 className="text-sm font-medium text-foreground mb-3">策略建议</h3>
              <p className="text-sm text-foreground/60">策略建议内容 - 待实现</p>
            </GlassCard>
          </div>
        );

      case "fuse":
        return (
          <div className="space-y-4">
            <GlassCard className="p-5">
              <h3 className="text-sm font-medium text-foreground mb-3">熔断规则</h3>
              <p className="text-sm text-foreground/60">熔断规则详细配置 - 待实现</p>
            </GlassCard>
          </div>
        );

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
          <p className="text-xs text-muted-foreground/60">市场情绪天气 · 策略自动切换中枢</p>
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

      {/* Weather Hero */}
      <WeatherHero weather={weather} onRefresh={handleRefresh} refreshing={refreshing} />

      {/* Tab Content */}
      {renderTabContent()}

      <Disclaimer compact />
    </div>
  );
}
