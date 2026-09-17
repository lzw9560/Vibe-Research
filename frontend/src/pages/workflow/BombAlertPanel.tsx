// S216 P0 接线：炸板预警接 /api/risk/bomb-alerts 真实信号（risk.py:195 调
// risk.bomb_alert_dispatcher.get_active_alerts）。旧 S036 标灰（桩端点
// /workflow/alerts 返 not_implemented）已废弃——/risk/bomb-alerts 已建返真实。
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";

export default function BombAlertPanel() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["risk", "bombAlerts"] as const,
    queryFn: () => api.bombAlerts(),
  });
  const alerts = data?.alerts ?? [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold">炸板预警</h3>
          <p className="text-xs text-muted-foreground">
            Bomb Alert Panel · C1-C6 全市场统一规则
          </p>
        </div>
        <span className="text-xs text-muted-foreground">
          {data?.date ?? "—"} · {data?.count ?? 0} 条
        </span>
      </div>

      {isLoading && (
        <span className="text-xs text-muted-foreground">加载中…</span>
      )}
      {error && !isLoading && (
        <span className="text-xs text-red-500">炸板预警加载失败</span>
      )}
      {!isLoading && !error && alerts.length === 0 && (
        <HonestEmptyState
          message="当日无炸板预警信号"
          hint="risk.bomb_alert_dispatcher.get_active_alerts 返空，无封单异常"
        />
      )}
      {alerts.length > 0 && (
        <ul className="space-y-2">
          {alerts.map((a) => (
            <li
              key={a.id}
              className="border border-border rounded-lg p-2 flex items-center gap-2"
            >
              <span
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                  a.alert_level === "red"
                    ? "bg-red-500/10 text-red-600"
                    : a.alert_level === "orange"
                    ? "bg-orange-500/10 text-orange-600"
                    : a.alert_level === "yellow"
                    ? "bg-amber-500/10 text-amber-600"
                    : "bg-blue-500/10 text-blue-600"
                }`}
              >
                {a.rule_id} {a.alert_level}
              </span>
              <span className="text-sm font-medium">
                {a.code} {a.name}
              </span>
              <span className="text-xs text-muted-foreground">
                {a.condition}
              </span>
              {a.data_status !== "ok" && (
                <span className="text-[10px] text-amber-600">
                  {a.data_status}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {data?.note && (
        <p className="text-xs text-muted-foreground">{data.note}</p>
      )}
    </div>
  );
}
