import { useState, useCallback } from "react";
import { TrendingUp, ShieldAlert, Volume2, VolumeX } from "lucide-react";
import { WorkflowStage } from "./components/WorkflowStage";
import { useIntradayData } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import type { TradingSignal, BombAlertItem } from "@/lib/api";

export default function IntradayMonitor() {
  const { data, isLoading, refetch } = useIntradayData();
  const [soundEnabled, setSoundEnabled] = useState(false);
  const handleRefresh = useCallback(() => refetch(), [refetch]);

  const signals: TradingSignal[] = data?.signals ?? [];
  const alerts: BombAlertItem[] = data?.alerts ?? [];

  return (
    <WorkflowStage 
      title="盘中监控" 
      subtitle="Intraday Monitor"
      loading={isLoading}
      onRefresh={handleRefresh}
    >
      <div className="mb-6 flex gap-3">
        <button
          onClick={() => setSoundEnabled(!soundEnabled)}
          className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm bg-muted/20 text-muted-foreground"
        >
          {soundEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
          声音提醒
        </button>
      </div>

      <div className="mb-6">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <TrendingUp className="h-4 w-4" /> 实时信号
        </h3>
        {signals.length === 0 ? (
          <p className="text-sm text-muted-foreground/60">暂无信号</p>
        ) : (
          <div className="space-y-2">
            {signals.slice(0, 10).map((s, i) => (
              <GlassCard key={i} className="flex items-center gap-3 p-3">
                <Badge variant="info">{s.type ?? s.signal_type ?? "signal"}</Badge>
                <div className="flex-1">
                  <p className="font-medium">{s.name ?? s.code}</p>
                  <p className="text-xs text-muted-foreground">{s.description}</p>
                </div>
              </GlassCard>
            ))}
          </div>
        )}
      </div>

      <div>
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <ShieldAlert className="h-4 w-4" /> 预警信息
        </h3>
        {alerts.length === 0 ? (
          <p className="text-sm text-muted-foreground/60">暂无预警</p>
        ) : (
          <div className="space-y-2">
            {alerts.map((a, i) => (
              <GlassCard key={i} className="flex items-center gap-3 p-3 border-l-4 border-l-orange-500">
                <Badge variant="warning">{a.alert_level}</Badge>
                <div className="flex-1">
                  <p className="font-medium">{a.name}</p>
                  <p className="text-xs text-muted-foreground">{a.condition}</p>
                </div>
              </GlassCard>
            ))}
          </div>
        )}
      </div>
    </WorkflowStage>
  );
}
