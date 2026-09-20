// 多维度 IA: /data — 数据底座（骨干数据层页）
// 采集 / cache / backfill 2018 / 质控 status
// 数据源: /api/metrics/data_fetch + useScheduledTasks(数据采集任务) + honest-empty backfill 2018
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Database, HardDrive, History, ShieldCheck, RefreshCw, AlertCircle } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { LineStatusLight } from "@/components/lines/LineStatusLight";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";
import { useScheduledTasks } from "@/lib/query";
import { request } from "@/lib/api/client";
import { cn } from "@/lib/utils";

// 数据采集任务类型
const DATA_TASK_TYPES = [
  "daily_full_pull",
  "kline_refresh",
  "baostock_5min_freeze",
  "ofi_collect",
  "intraday_microstructure_snapshot",
  "intraday_auction_dense",
  "market_data_sync",
  "daily_data_refresh",
] as const;

interface DataFetchMetrics {
  total_fetches?: number;
  success_count?: number;
  fail_count?: number;
  cache_hit_rate?: number;
  avg_latency_ms?: number;
  [k: string]: unknown;
}

export function DataFoundationPage() {
  const { data: tasks } = useScheduledTasks();
  const taskList = tasks ?? [];

  // 数据采集 metrics
  const { data: metrics, isLoading: metricsLoading } = useQuery({
    queryKey: ["metrics", "data_fetch"] as const,
    queryFn: () => request<DataFetchMetrics>("/metrics/data_fetch"),
    staleTime: 60_000,
  });

  // 数据任务健康度
  const dataTasks = taskList.filter(t => DATA_TASK_TYPES.includes(t.task_type as typeof DATA_TASK_TYPES[number]));
  const failedDataTasks = dataTasks.filter(t => t.last_run_status === "failed");
  const dataHealthStatus = failedDataTasks.length > 0 ? "alert" : dataTasks.length > 0 ? "ok" : "idle";

  // cache 状态（从 metrics 推断）
  const cacheHitRate = metrics?.cache_hit_rate;
  const cacheStatus = cacheHitRate != null
    ? cacheHitRate > 0.5 ? "ok" : "pending"
    : "idle";

  // backfill 2018 状态——honest-empty（无直接 endpoint）
  const backfillStatus = "idle";

  // 质控状态——从 fail_count 推断
  const failCount = metrics?.fail_count ?? 0;
  const qcStatus = failCount > 0 ? "pending" : metrics ? "ok" : "idle";

  return (
    <div>
      <PageHeader
        title="数据层"
        subtitle="数据底座 · 采集 / cache / backfill 2018 / 质控 status"
        actions={<RefreshCw className="h-4 w-4 text-muted-foreground" />}
      />

      {/* 数据健康概览 */}
      <GlassCard tier="primary" className="mb-4">
        <div className="mb-3 flex items-center gap-2">
          <Database className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold">数据健康</h2>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <LineStatusLight
            lineKey="collection"
            label="采集"
            status={dataHealthStatus}
            detail={dataTasks.length > 0 ? `${dataTasks.length} 任务${failedDataTasks.length > 0 ? ` · ${failedDataTasks.length} 失败` : ""}` : "待接线"}
            link="/pipeline"
          />
          <LineStatusLight
            lineKey="cache"
            label="cache"
            status={cacheStatus}
            detail={cacheHitRate != null ? `命中率 ${(cacheHitRate * 100).toFixed(0)}%` : "待接线"}
          />
          <LineStatusLight
            lineKey="backfill"
            label="backfill 2018"
            status={backfillStatus}
            detail="待接线"
          />
          <LineStatusLight
            lineKey="qc"
            label="质控"
            status={qcStatus}
            detail={failCount > 0 ? `${failCount} 失败` : metrics ? "正常" : "待接线"}
          />
        </div>
      </GlassCard>

      {/* 采集 metrics 详情 */}
      <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
        <GlassCard>
          <div className="mb-2 flex items-center gap-2">
            <HardDrive className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">采集 metrics</h3>
          </div>
          {metricsLoading ? (
            <p className="text-xs text-muted-foreground">加载 metrics…</p>
          ) : metrics ? (
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-muted-foreground">总拉取</span>
                <span className="ml-2 font-mono font-medium">{metrics.total_fetches ?? "—"}</span>
              </div>
              <div>
                <span className="text-muted-foreground">成功</span>
                <span className="ml-2 font-mono text-emerald-500">{metrics.success_count ?? "—"}</span>
              </div>
              <div>
                <span className="text-muted-foreground">失败</span>
                <span className="ml-2 font-mono text-red-500">{metrics.fail_count ?? "—"}</span>
              </div>
              <div>
                <span className="text-muted-foreground">均延迟</span>
                <span className="ml-2 font-mono">{metrics.avg_latency_ms != null ? `${metrics.avg_latency_ms.toFixed(0)}ms` : "—"}</span>
              </div>
            </div>
          ) : (
            <HonestEmptyState message="metrics 待接线" hint="/api/metrics/data_fetch endpoint 未返回数据" />
          )}
        </GlassCard>

        <GlassCard>
          <div className="mb-2 flex items-center gap-2">
            <History className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">backfill 2018</h3>
          </div>
          <HonestEmptyState
            message="历史数据 backfill 状态待接线"
            hint="需后端 /api/data/backfill-status endpoint，当前 cache 有 9 个月 bars，backfill 2018 脚本可生成更早 case（见 memory: backfill-historical-data-before-waiting）"
          />
        </GlassCard>
      </div>

      {/* 数据采集任务列表 */}
      <GlassCard className="mb-4">
        <h3 className="mb-3 text-sm font-semibold">数据采集任务</h3>
        {dataTasks.length > 0 ? (
          <div className="space-y-1.5">
            {dataTasks.map(task => (
              <div key={task.id} className="flex items-center gap-3 rounded-lg border border-border/30 bg-muted/10 px-3 py-2">
                <span className={cn(
                  "h-2 w-2 shrink-0 rounded-full",
                  task.last_run_status === "success" ? "bg-emerald-500"
                  : task.last_run_status === "failed" ? "bg-red-500"
                  : "bg-gray-400",
                )} />
                <span className="text-xs font-medium">{task.name}</span>
                <span className="font-mono text-xs text-muted-foreground">{task.cron_expr}</span>
                <span className="ml-auto text-xs text-muted-foreground">
                  {task.last_run_at ? new Date(task.last_run_at).toLocaleString("zh-CN") : "—"}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <HonestEmptyState message="无数据采集任务" hint="定时任务未返回数据类任务" />
        )}
        <div className="mt-2 text-right">
          <Link to="/pipeline" className="text-xs text-primary">全部任务 →</Link>
        </div>
      </GlassCard>

      {/* 质控 */}
      <GlassCard tier="sub" className="mb-4">
        <div className="mb-2 flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-xs font-semibold">质控</h3>
        </div>
        {failedDataTasks.length > 0 ? (
          <div className="space-y-1">
            {failedDataTasks.map(t => (
              <p key={t.id} className="flex items-center gap-1 text-xs text-red-500">
                <AlertCircle className="h-3 w-3" /> {t.name} 上次失败 · 点击
                <Link to="/pipeline" className="underline">任务健康</Link>查看日志
              </p>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">数据采集任务无失败 · em_get 防封 + 熔断器正常</p>
        )}
      </GlassCard>

      {/* CTA 脊 */}
      <NextStepBar pageCtx="data" />
    </div>
  );
}
