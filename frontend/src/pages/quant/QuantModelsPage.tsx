// Track D M3: 量化模型页——M1-M7 规划态占位卡（via Cmd+K palette "量化模型"）。
// live 卡：M1 OFI 拉真实快照数（useIntradayOfi），M2/M4 后端已实现但前端 endpoint 缺 → honest "数据待接线"。
// planning 卡：M3/M5/M6/M7 spec-only/未实现 → 琥珀"规划中"徽章。守工程底线：不臆造数据。
import { Link } from "react-router-dom";
import { CheckCircle2, FileClock, ArrowUpRight, Loader2 } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { FocusDayStrip } from "@/components/ui/FocusDayStrip";
import { NextStepBar } from "@/components/ui/NextStepBar";
import { QUANT_MODULES, type QuantModule } from "./modules";
import { useDateTriplet, useIntradayOfi } from "@/lib/query";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

function StatusBadge({ status }: { status: QuantModule["status"] }) {
  return status === "live" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-500">
      <CheckCircle2 className="h-3 w-3" />
      已实现 · live
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-500">
      <FileClock className="h-3 w-3" />
      规划中 · spec-only
    </span>
  );
}

// M1 OFI live 数据徽章：拉最近 1 条快照显 count；失败/空 → honest "数据待接线"
function OfiLiveChip() {
  const { data: triplet } = useDateTriplet();
  const today = triplet?.today ?? "";
  const { data, isLoading, isError } = useIntradayOfi(today, undefined, 1, {
    enabled: !!today,
  });
  if (!today) return <span className="text-[10px] text-muted-foreground">数据待接线</span>;
  if (isLoading) return <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />;
  if (isError || !data) {
    return <span className="text-[10px] text-muted-foreground">数据待接线</span>;
  }
  return (
    <span className="text-[10px] text-muted-foreground">
      最近 {data.count ?? 0} 条快照{data.truncated ? "（截断）" : ""}
    </span>
  );
}

// M4 em_get 防封健康度：circuit_breaker 各 breaker 状态
function EmHealthChip() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["quant", "emHealth"] as const,
    queryFn: () => api.emHealth(),
    refetchInterval: 30 * 1000,
  });
  if (isLoading) return <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />;
  if (isError || !data) return <span className="text-[10px] text-muted-foreground">数据待接线</span>;
  const n = Object.keys(data.breakers || {}).length;
  if (data.data_status === "empty" || n === 0) return <span className="text-[10px] text-muted-foreground">无 breaker</span>;
  return (
    <span className={cn("text-[10px]", data.all_healthy ? "text-emerald-600" : "text-red-500")}>
      {data.all_healthy ? "全熔断器正常" : "有熔断器 OPEN"} · {n} 路
    </span>
  );
}

// M2 预期差：T-1 close + T open 高开% + 量比（用默认 600519 演示，选股后看详情）
function ExpectationGapChip() {
  const { data: triplet } = useDateTriplet();
  const today = triplet?.today ?? "";
  const { data, isLoading, isError } = useQuery({
    queryKey: ["quant", "expectationGap", today] as const,
    queryFn: () => api.expectationGap("600519", today || undefined),
    enabled: !!today,
  });
  if (!today) return <span className="text-[10px] text-muted-foreground">数据待接线</span>;
  if (isLoading) return <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />;
  if (isError || !data) return <span className="text-[10px] text-muted-foreground">数据待接线</span>;
  if (data.data_status === "empty") return <span className="text-[10px] text-muted-foreground">无数据</span>;
  return (
    <span className="text-[10px] text-muted-foreground">
      score {data.score.toFixed(2)} · 高开 {data.gap_pct ?? "—"}%
    </span>
  );
}

function LiveDataChip({ mod }: { mod: QuantModule }) {
  // liveSource 决定拉哪个真实数据；null → honest "数据待接线"（不臆造）
  if (mod.liveSource === "ofi") return <OfiLiveChip />;
  if (mod.liveSource === "emHealth") return <EmHealthChip />;
  if (mod.liveSource === "expectationGap") return <ExpectationGapChip />;
  return <span className="text-[10px] text-muted-foreground">数据待接线</span>;
}

function ModuleCard({ mod }: { mod: QuantModule }) {
  return (
    <GlassCard className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-bold text-primary">
              {mod.key}
            </span>
            <h3 className="text-sm font-semibold">{mod.title}</h3>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{mod.subtitle}</p>
        </div>
        <StatusBadge status={mod.status} />
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground/80">{mod.note}</p>
      <div className="mt-auto flex items-center justify-between pt-1">
        {mod.status === "live" ? <LiveDataChip mod={mod} /> : <span className="text-[10px] text-muted-foreground">未实现</span>}
        {mod.link && (
          <Link to={mod.link} className="inline-flex items-center gap-0.5 text-xs text-primary hover:underline">
            进入 <ArrowUpRight className="h-3 w-3" />
          </Link>
        )}
      </div>
    </GlassCard>
  );
}

export function QuantModelsPage() {
  const liveCount = QUANT_MODULES.filter((m) => m.status === "live").length;
  return (
    <div>
      <PageHeader
        title="量化模型"
        subtitle={`M1-M7 方法论模块（${liveCount} 已实现 / ${QUANT_MODULES.length - liveCount} 规划中）`}
        actions={<FocusDayStrip />}
      />
      <p className="mb-4 text-xs text-muted-foreground">
        S200 量化系统 7 模块：OFI / 预期差 / CentralRouter / em_get防封 / 财报季 / 国家队 / LLM图谱。
        已实现显 live 徽章（数据 endpoint 缺的诚实标"待接线"），规划中显 spec-only 徽章——不臆造。
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {QUANT_MODULES.map((mod) => (
          <ModuleCard key={mod.key} mod={mod} />
        ))}
      </div>
      <div className={cn("mt-6")}>
        <NextStepBar pageCtx="quant-models" />
      </div>
    </div>
  );
}

export default QuantModelsPage;
