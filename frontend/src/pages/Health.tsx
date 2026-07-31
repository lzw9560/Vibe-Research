import { Activity, Database, Cpu, Calendar, Shield, FlaskConical } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import { useHealth } from "@/lib/query";

interface HealthResponse {
  ok: boolean;
  service: string;
  version: string;
  checks: Record<string, any>;
  timestamp: string;
}

interface CheckItem {
  label: string;
  ok: boolean;
  detail: string | Record<string, any>;
  icon: React.ElementType;
}

function formatDetail(detail: string | Record<string, any>): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.join(", ");
  return JSON.stringify(detail);
}

export function HealthPage() {
  // T9：原 useState/useEffect + setInterval(30s) 轮询 → useHealth + refetchInterval。
  // 注：api.health() 类型签名仅 { ok: boolean }，实际后端返完整 HealthResponse，就地窄→宽 cast。
  const { data: raw, isLoading, error } = useHealth({ refetchInterval: 30_000 });
  const data = raw as unknown as HealthResponse | undefined;

  const checks: CheckItem[] = data
    ? Object.entries(data.checks).map(([key, value]) => {
        const iconMap: Record<string, React.ElementType> = {
          database: Database,
          circuit_breaker: Shield,
          data_freshness: Calendar,
          scheduler: Cpu,
          fallback: FlaskConical,
          extreme_market: Activity,
        };
        return {
          label: key
            .replace(/_/g, " ")
            .replace(/\b\w/g, (c) => c.toUpperCase()),
          ok: (value as any).ok ?? false,
          detail: (value as any).detail ?? "",
          icon: iconMap[key] ?? Activity,
        };
      })
    : [];

  return (
    <div className="mx-auto max-w-3xl px-4 py-6">
      <PageHeader
        title="系统健康状态"
        subtitle={`最后更新：${data ? new Date(data.timestamp).toLocaleString("zh-CN") : "--"}`}
      />

      {isLoading && (
        <GlassCard>
          <div className="py-6 text-center text-sm text-muted-foreground">
            正在读取后端健康状态...
          </div>
        </GlassCard>
      )}

      {error && (
        <GlassCard>
          <div className="p-4 text-sm text-rose-600 dark:text-rose-400">
            读取失败：{error instanceof Error ? error.message : String(error)}
          </div>
        </GlassCard>
      )}

      {!isLoading && !error && data && (
        <div className="mt-6 space-y-3">
          <GlassCard
            className={cn(
              "border",
              data.ok
                ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300"
                : "border-rose-500/40 bg-rose-500/5 text-rose-700 dark:text-rose-300"
            )}
          >
            总体状态：{data.ok ? "正常" : "异常"}（{data.service} {data.version}）
          </GlassCard>

          <div className="grid gap-3">
            {checks.map((item) => {
              const Icon = item.icon;
              const statusColor = item.ok
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-rose-600 dark:text-rose-400";
              return (
                <GlassCard key={item.label}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Icon className={cn("h-4 w-4", statusColor)} />
                      <span className="text-sm font-medium">{item.label}</span>
                    </div>
                    <span
                      className={cn(
                        "text-xs font-semibold",
                        item.ok
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-rose-600 dark:text-rose-400"
                      )}
                    >
                      {item.ok ? "正常" : "异常"}
                    </span>
                  </div>
                  <div className="mt-2 text-xs text-muted-foreground">
                    {formatDetail(item.detail)}
                  </div>
                </GlassCard>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
