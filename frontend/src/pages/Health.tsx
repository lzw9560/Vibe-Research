import { useEffect, useState } from "react";
import { Activity, Database, Cpu, Calendar, Shield, FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";

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
  const [data, setData] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchHealth = async () => {
      try {
        const res = await fetch("/api/health");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!cancelled) {
          setData(json);
          setLoading(false);
        }
      } catch (exc) {
        if (!cancelled) {
          setError(exc instanceof Error ? exc.message : String(exc));
          setLoading(false);
        }
      }
    };
    fetchHealth();
    const timer = setInterval(fetchHealth, 30_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

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
      <h1 className="text-2xl font-bold">系统健康状态</h1>
      <p className="mt-1 text-xs text-muted-foreground">
        最后更新：{" "}
        {data ? new Date(data.timestamp).toLocaleString("zh-CN") : "--"}
      </p>

      {loading && (
        <div className="mt-6 rounded-lg border border-dashed border-muted-foreground/40 p-6 text-center text-sm text-muted-foreground">
          正在读取后端健康状态...
        </div>
      )}

      {error && (
        <div className="mt-6 rounded-lg border border-rose-500/40 bg-rose-500/5 p-4 text-sm text-rose-600 dark:text-rose-400">
          读取失败：{error}
        </div>
      )}

      {!loading && !error && data && (
        <div className="mt-6 space-y-3">
          <div
            className={cn(
              "rounded-lg border p-4 text-sm",
              data.ok
                ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300"
                : "border-rose-500/40 bg-rose-500/5 text-rose-700 dark:text-rose-300"
            )}
          >
            总体状态：{data.ok ? "正常" : "异常"}（{data.service} {data.version}）
          </div>

          <div className="grid gap-3">
            {checks.map((item) => {
              const Icon = item.icon;
              const statusColor = item.ok
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-rose-600 dark:text-rose-400";
              return (
                <div
                  key={item.label}
                  className="rounded-lg border border-muted-foreground/20 bg-background/60 p-4"
                >
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
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
