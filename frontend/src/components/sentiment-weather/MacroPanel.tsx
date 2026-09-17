import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";

interface FredFactor {
  series_id: string;
  description: string;
  latest_date?: string | null;
  latest_value?: number | null;
  n_obs?: number;
  error?: string;
}

interface FomcInfo {
  last_verified?: string;
  today?: { date: string; type: string; time_beijing_summer?: string; note?: string } | null;
  next?: { date: string; type: string; time_beijing_summer?: string; note?: string } | null;
  total?: number;
  error?: string;
}

interface WeatherCap {
  probability?: number;
  risk_level?: string;  // 低/中/高/极高
  suggested_position?: number;  // 0.25/0.5/0.7/1.0
  data_status?: string;
  date?: string;
  error?: string;
}

interface MacroSnapshot {
  fred_factors: Record<string, FredFactor>;
  fred_key_loaded: boolean;
  fomc: FomcInfo;
  weather_cap?: WeatherCap;
}

// FRED 因子中文名 + 信号方向（用于展示）
const FACTOR_LABEL: Record<string, string> = {
  us_10y_yield: "美债 10Y",
  dxy: "美元指数",
  us_fed_funds_eff: "美联储利率",
  us_10y2y_spread: "美债 10Y-2Y 利差",
  usd_cny: "人民币兑美元",
  wti_crude: "WTI 原油",
  lme_copper: "LME 铜",
  us_vix: "VIX 恐慌指数",
};

export function MacroPanel() {
  const [data, setData] = useState<MacroSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const res = await fetch("/api/macro/snapshot");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) {
          setData(json.data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "加载失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (loading) return <Skeleton className="h-40" />;
  if (error) return <GlassCard className="p-4">宏观快照加载失败：{error}</GlassCard>;
  if (!data) return <GlassCard className="p-4">无数据</GlassCard>;

  const factors = Object.entries(data.fred_factors);
  const fomc = data.fomc;

  return (
    <div className="space-y-4">
      <GlassCard className="p-5">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-foreground">FRED 宏观因子（8 因子）</h3>
          <Badge variant={data.fred_key_loaded ? "success" : "default"}>
            {data.fred_key_loaded ? "Key 已加载" : "Key 未加载"}
          </Badge>
        </div>
        <div className="grid grid-cols-2 gap-3">
          {factors.map(([name, f]) => (
            <div key={name} className="border border-border rounded-lg p-3">
              <div className="text-xs text-muted-foreground">{FACTOR_LABEL[name] ?? name}</div>
              <div className="text-lg font-semibold text-foreground">
                {f.latest_value != null ? f.latest_value : "—"}
              </div>
              <div className="text-xs text-muted-foreground">
                {f.latest_date ? `@ ${f.latest_date}` : ""} {f.n_obs ? `(${f.n_obs} obs)` : ""}
              </div>
              <div className="text-xs text-muted-foreground truncate" title={f.description}>
                {f.series_id}
              </div>
            </div>
          ))}
        </div>
      </GlassCard>

      <GlassCard className="p-5">
        <h3 className="text-sm font-medium text-foreground mb-3">FOMC 日历</h3>
        {fomc.error ? (
          <div className="text-sm text-muted-foreground">{fomc.error}</div>
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">今日：</span>
              {fomc.today ? (
                <Badge variant="danger">
                  {fomc.today.type} {fomc.today.time_beijing_summer ?? ""}
                </Badge>
              ) : (
                <Badge variant="default">非 FOMC 日</Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">下次：</span>
              {fomc.next ? (
                <span className="text-sm">
                  {fomc.next.date} {fomc.next.type} {fomc.next.time_beijing_summer ?? ""}
                </span>
              ) : (
                <span className="text-sm text-muted-foreground">无</span>
              )}
            </div>
            <div className="text-xs text-muted-foreground">
              日历 {fomc.total ?? 0} 条，last_verified {fomc.last_verified ?? "—"}
            </div>
          </div>
        )}
      </GlassCard>

      {data.weather_cap && !data.weather_cap.error && (
        <GlassCard className="p-5">
          <h3 className="text-sm font-medium text-foreground mb-3">Storm 风险门（weather_cap）</h3>
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-muted-foreground">风险等级：</span>
            <Badge variant={
              data.weather_cap.risk_level === "极高" || data.weather_cap.risk_level === "高" ? "danger" :
              data.weather_cap.risk_level === "中" ? "default" :
              "success"
            }>
              {data.weather_cap.risk_level ?? "—"}
            </Badge>
            <span className="text-xs text-muted-foreground">
              概率 {data.weather_cap.probability?.toFixed(1) ?? "—"}
            </span>
          </div>
          <div className="text-xs text-muted-foreground">
            建议仓位 {data.weather_cap.suggested_position != null ? `${(data.weather_cap.suggested_position * 100).toFixed(0)}%` : "—"}
            （weather_cap×0.3 压仓位，{data.weather_cap.data_status ?? "—"}）
          </div>
        </GlassCard>
      )}
    </div>
  );
}
