// S073 选股 pipeline 可视化（简洁：统一节点 + 箭头 + 分叉，点击展开详情）
// 涨停股池 root → 板块轮动 → 分叉（涨停叉 lane + 非涨停叉 placeholder lane）
// §44 诚实：scored 不接 R3 → 虚线漂移；非涨停 Phase 2 → placeholder；STI/天气去噪不展示
import { useState } from "react";
import { HonestyBanner } from "@/components/ui/HonestyBanner";
import { useMultiRotation } from "@/lib/query/strategy";
import { FunnelLayerCard } from "@/components/ui/FunnelLayerCard";
import { NonLimitupLane } from "./NonLimitupPlaceholder";
import type { FunnelLayer, FunnelResult, DiagnosisCard } from "@/lib/candidates";

interface RerunHandlers {
  rerunLayer: (layerId: string, date?: string, body?: Record<string, unknown>) => Promise<unknown>;
  rerunDownstream: (layerId: string, date?: string) => Promise<unknown>;
}

interface Props {
  funnelResult?: FunnelResult;
  funnelLayers?: FunnelLayer[];
  finalCandidates?: DiagnosisCard[];
  scoredCandidatesCount?: number;
  screenerPoolSize?: number;
  date?: string;
  mode?: "full" | "funnel-only";
  fork?: "limitup" | "non-limitup" | "both";
  onPick?: (code: string) => void;
  rerunHandlers?: RerunHandlers;
  showHonestyBanner?: boolean;
}

// 统一节点样式（实线/虚线两态，颜色按语义）
const NODE = "rounded-lg border border-border/40 bg-card/40 p-3";
const NODE_DASHED = "rounded-lg border border-dashed p-3";

export function SelectionPipeline({
  funnelResult, funnelLayers, finalCandidates, scoredCandidatesCount,
  screenerPoolSize, date, mode = "funnel-only", fork = "both", onPick, rerunHandlers,
  showHonestyBanner = true,
}: Props) {
  const layers = funnelResult?.layers ?? funnelLayers ?? [];
  const finals = funnelResult?.final_candidates ?? finalCandidates ?? [];
  const r1 = layers.find((l) => l.layer_id === "R1");
  const rootSize = screenerPoolSize ?? r1?.input_count;
  const hasScored = scoredCandidatesCount != null;
  const showLimitup = fork !== "non-limitup";
  const showNonLimitup = fork !== "limitup";
  const bothLanes = showLimitup && showNonLimitup;

  return (
    <div className="space-y-1.5">
      {showHonestyBanner !== false && <HonestyBanner />}

      <PipelineNode label="涨停股池" sub="screener · T日涨停 → 选 T+1" count={rootSize} />
      <ArrowDown />
      {date && <SectorRotationNode date={date} />}
      {date && <ArrowDown label={bothLanes ? "分叉" : undefined} />}
      {!date && <ArrowDown label={bothLanes ? "分叉" : undefined} />}

      <div className={bothLanes ? "grid gap-3 sm:grid-cols-2" : "space-y-1.5"}>
        {showLimitup && (
          <div className="space-y-1.5">
            <LaneHeader title="涨停叉" sub="已实现" />
            {layers.map((layer, i) => (
              <LayerStep
                key={layer.layer_id}
                layer={layer}
                next={layers[i + 1]}
                onPick={onPick}
                rerunHandlers={rerunHandlers}
                date={date}
              />
            ))}
            <ArrowDown />
            <PipelineNode label="终选" sub="final_candidates" count={finals.length} />
            <ArrowDown label="战法分" />
            {mode === "full" && hasScored ? (
              <ScoredBranch count={scoredCandidatesCount!} />
            ) : (
              <ScoredDegraded />
            )}
            <ArrowDown label="风控" />
            <RiskNode />
          </div>
        )}
        {showNonLimitup && <NonLimitupLane date={date} />}
      </div>
    </div>
  );
}

function PipelineNode({ label, sub, count }: { label: string; sub?: string; count?: number }) {
  return (
    <div className={NODE}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium">{label}</div>
          {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
        </div>
        <div className="text-lg font-bold text-primary">{count ?? "—"}</div>
      </div>
    </div>
  );
}

function ArrowDown({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center py-0.5">
      <div className="h-2 w-px bg-border/40" />
      <span className="text-[9px] text-border/50 leading-none">▼</span>
      {label && <span className="text-[10px] text-muted-foreground">{label}</span>}
    </div>
  );
}

function LaneHeader({ title, sub, tone }: { title: string; sub?: string; tone?: "active" | "placeholder" }) {
  return (
    <div className={tone === "placeholder" ? "flex items-center gap-2 opacity-50" : "flex items-center gap-2"}>
      <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</span>
      {sub && <span className="text-[10px] text-muted-foreground/70">{sub}</span>}
    </div>
  );
}

function SectorRotationNode({ date }: { date: string }) {
  const { data: rot, isLoading } = useMultiRotation(date);
  if (isLoading) return <div className={`${NODE} text-xs text-muted-foreground`}>板块轮动加载中…</div>;
  if (!rot) return null;
  const dim = rot.multi_dim_rank.slice(0, 5);
  const top = rot.multi_rank.slice(0, 10);
  return (
    <div className={NODE}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium">板块轮动（多维度融合）</span>
        <span className="text-[10px] text-muted-foreground">§5.4 纯 label · 行业+题材+概念</span>
      </div>
      {dim.length > 0 && (
        <div className="mt-0.5 text-xs text-muted-foreground">
          共振 TOP5：{dim.map((s) => `${s.label}(${s.zt_count_today},${s.dims.length}维)`).join(" · ")}
        </div>
      )}
      <div className="mt-0.5 text-[11px] text-muted-foreground/80">
        全标签 TOP10：{top.map((s) => `${s.label}(${s.zt_count_today})`).join(" · ")}
      </div>
      <div className="mt-1 text-[10px] text-muted-foreground/60">
        多维度共振（dims≥2）更可信；ths 106 全市场 + concept_map 缓存
      </div>
    </div>
  );
}

function ScoredBranch({ count }: { count: number }) {
  return (
    <div className={`${NODE_DASHED} border-purple-500/40 bg-purple-500/5`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-purple-300">战法分</span>
        <span className="rounded bg-purple-500/20 px-1 text-[10px] text-purple-300">漂移</span>
      </div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">
        {count} 只 · 不接 R3（数据链断）· §9.4 游资画像已接（画像未建降级）
      </div>
    </div>
  );
}

function ScoredDegraded() {
  return <div className={`${NODE_DASHED} border-muted/40 bg-muted/5 text-xs text-muted-foreground`}>战法分：未取得（仅盘前简报）</div>;
}

// 风控非对称节点（S071 参数，§44 无 validated edge → 风控是当前唯一盈利 lever：亏小赚大）
function RiskNode() {
  return (
    <div className={`${NODE} border-amber-500/40 bg-amber-500/5`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-amber-300">风控非对称</span>
        <span className="rounded bg-amber-500/20 px-1 text-[10px] text-amber-300">唯一 lever</span>
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-muted-foreground sm:grid-cols-3">
        <span>仓位 3% × 日历</span>
        <span>止损 −4%</span>
        <span>止盈 +8%</span>
        <span>max 3 仓</span>
        <span>max 持 3 日</span>
        <span>R:R ≈ 1:2</span>
      </div>
      <div className="mt-1 text-[10px] text-amber-200/70">
        §44 信号全无 validated edge → 盈利靠风控非对称（小仓+紧止损+非对称 R:R+短持），非信号
      </div>
    </div>
  );
}

function FunnelShrinkBar({ input, output }: { input: number; output: number }) {
  const ratio = input > 0 ? Math.max(output / input, 0.12) : 0.12;
  return (
    <div className="flex items-center gap-1.5 px-1">
      <div className="h-1.5 flex-1 rounded bg-muted/30" />
      <div className="h-1.5 rounded bg-primary/40" style={{ width: `${ratio * 100}%` }} />
      <span className="text-[10px] text-muted-foreground">{input}→{output}</span>
    </div>
  );
}

function RerunFooter({ layer, handlers, date }: { layer: FunnelLayer; handlers: RerunHandlers; date?: string }) {
  const [busy, setBusy] = useState(false);
  const [turnover, setTurnover] = useState("");
  const rerun = async () => {
    setBusy(true);
    try {
      await handlers.rerunLayer(layer.layer_id, date, turnover ? { turnover_cold: Number(turnover) } : undefined);
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <input
        value={turnover}
        onChange={(e) => setTurnover(e.target.value)}
        placeholder="换手冷档%"
        className="w-32 rounded border border-border bg-transparent px-2 py-1 text-sm"
      />
      <button
        onClick={rerun}
        disabled={busy}
        className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground disabled:opacity-50"
      >
        {busy ? "重跑中…" : "重跑此层"}
      </button>
    </>
  );
}

// 简洁节点 + 点击展开 FunnelLayerCard 详情（折叠不显收缩条，展开才显详情+收缩条）
function LayerStep({ layer, next, onPick, rerunHandlers, date }: {
  layer: FunnelLayer;
  next?: FunnelLayer;
  onPick?: (code: string) => void;
  rerunHandlers?: RerunHandlers;
  date?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const mismatch = next != null && layer.output_count !== next.input_count;
  const missing = layer.data_status === "未取得";
  return (
    <div className="space-y-1">
      <button
        onClick={() => setExpanded((v) => !v)}
        className={`${NODE} w-full text-left hover:bg-card/60`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{layer.layer_id}</span>
            <span className="text-sm font-medium">{layer.name}</span>
            {missing && <span className="text-[10px] text-warning">未取得</span>}
            {mismatch && next && <span className="text-[10px] text-warning">失配</span>}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">{layer.input_count}→{layer.output_count}</span>
            <span className="text-[10px] text-muted-foreground">{expanded ? "▼" : "▶"}</span>
          </div>
        </div>
      </button>
      {expanded && (
        <>
          <FunnelShrinkBar input={layer.input_count} output={layer.output_count} />
          <FunnelLayerCard
            layer={layer}
            variant="neutral"
            date={date}
            onPick={onPick}
            footer={rerunHandlers ? <RerunFooter layer={layer} handlers={rerunHandlers} date={date} /> : undefined}
          />
        </>
      )}
      {next && <ArrowDown />}
    </div>
  );
}
