// S073 选股 pipeline 可视化（简洁：统一节点 + 箭头 + 分叉，点击展开详情）
// 涨停股池 root → 板块轮动 → 双叉（segmented control 切换，一次只显一叉）
// S094 R22：双叉从"上下分区同显"改为"segmented control 切换"——减页面长度，专注当前 lane
// §44 诚实：scored 不接 R3 → 虚线漂移；非涨停 Phase 2 → placeholder；STI/天气去噪不展示
import { useState } from "react";
import { HonestyBanner } from "@/components/ui/HonestyBanner";
import { useMultiRotation } from "@/lib/query/strategy";
import { FunnelLayerCard } from "@/components/ui/FunnelLayerCard";
import { NonLimitupLane } from "./NonLimitupPlaceholder";
import type { FunnelLayer, FunnelResult, DiagnosisCard } from "@/lib/candidates";
import type { ScoredCandidate } from "@/lib/api";
import { DiagnosisCardView } from "@/components/candidate/DiagnosisCard";

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
  /** S094 T17/R28：briefing 透传的 market_scan_scored（喂非涨停叉，免独立端点调用）。 */
  nonLimitupCandidates?: ScoredCandidate[];
  date?: string;
  mode?: "full" | "funnel-only";
  /** S094 §11 附录 A1：双叉切换提升到 ForwardTabSection 后，lane prop 控制显哪叉。
   *  fork 兼容旧调用（作初始值），lane 优先；默认涨停。 */
  lane?: "limitup" | "non-limitup";
  /** S094 R22 旧 fork prop 兼容——"limitup"/"non-limitup" 映射 lane；"both" 忽略（默认涨停）。 */
  fork?: "limitup" | "non-limitup" | "both";
  onPick?: (code: string) => void;
  rerunHandlers?: RerunHandlers;
  showHonestyBanner?: boolean;
  /** S094 附录 A2：板块轮动由前置共享区统一渲染时传 true（默认），本组件不再渲染 SectorRotationNode。
   *  避免双叉切换时前置共享区 + SelectionPipeline 内部两处重复渲染同一数据。 */
  sharedSectorRotation?: boolean;
}

type ActiveLane = "limitup" | "non-limitup";

// 统一节点样式（实线/虚线两态，颜色按语义）
const NODE = "rounded-lg border border-border/40 bg-card/40 p-3";

export function SelectionPipeline({
  funnelResult, funnelLayers, finalCandidates,
  screenerPoolSize, nonLimitupCandidates, date, lane, fork, onPick, rerunHandlers,
  showHonestyBanner = true,
  sharedSectorRotation = true,
}: Props) {
  // S094 §11 附录 A1：lane prop 优先；fork 兼容旧调用作 fallback；默认涨停。
  // 内部不再有 LaneSwitcher + activeLane state——切换由父组件（ForwardTabSection）控制。
  const activeLane: ActiveLane = lane ?? (fork === "non-limitup" ? "non-limitup" : "limitup");
  const layers = funnelResult?.layers ?? funnelLayers ?? [];
  const finals = funnelResult?.final_candidates ?? finalCandidates ?? [];
  const r1 = layers.find((l) => l.layer_id === "R1");
  // 今日涨停总数优先取 screenerPoolSize（briefing.market_emotion.zt_count 传入）；
  // 缺失时 fallback r1.input_count（采集源输入，非涨停总数）并标注，不冒充涨停数。
  const hasZtTotal = screenerPoolSize != null;
  const rootSize = screenerPoolSize ?? r1?.input_count;
  const rootSub = hasZtTotal
    ? "今日涨停 · screener 选 T+1"
    : "今日涨停数未取得 · 显 R1 输入（非涨停总数）";

  return (
    <div className="space-y-1.5">
      {showHonestyBanner !== false && <HonestyBanner />}

      {/* S094 §11 附录 A1：LaneSwitcher 已移除——切换由父组件 ForwardTabSection 的 ForwardLaneSwitcher 控制 */}

      {/* 共享节点：涨停股池（两模式都显，不在切换范围） */}
      <PipelineNode label="涨停股池" sub={rootSub} count={rootSize} />
      <ArrowDown />
      {/* S094 附录 A2：板块轮动由前置共享区统一渲染（sharedSectorRotation=true），
           本组件不再渲染 SectorRotationNode，避免双叉切换时两处重复 */}
      {!sharedSectorRotation && date && <SectorRotationNode date={date} />}
      {!sharedSectorRotation && date && <ArrowDown />}
      {!sharedSectorRotation && !date && <ArrowDown />}
      {sharedSectorRotation && <ArrowDown />}

      {/* S094 §11 附录 A1：根据 lane prop 显对应叉——一次只显一叉，切换由父组件控制 */}
      {activeLane === "limitup" ? (
        <div className="space-y-1.5">
          <LaneHeader title="涨停叉" sub="已实现" />
          {/* S084 TASK A：R2/R3 已下放战法层（直通透传），只显 R1 + SELF，不显 R2/R3 假漏斗 */}
          {layers.filter((l) => l.layer_id === "R1" || l.layer_id === "SELF").map((layer, i, arr) => (
            <LayerStep
              key={layer.layer_id}
              layer={layer}
              next={arr[i + 1]}
              onPick={onPick}
              rerunHandlers={rerunHandlers}
              date={date}
            />
          ))}
          <ArrowDown />
          <FinalCandidatesNode finals={finals} />
          {/* F1：终选→战法匹配数据流传递节点（消除视觉断流：终选 N 只 → 进入战法匹配）
              数字取 finals.length，与 FinalCandidatesNode 计数同源；战法评估候选总数见 ② StrategySubPipelineView */}
          <HandoffNode count={finals.length} label="进入战法匹配" />
          {/* S094 §11 附录 A2：涨停叉尾部战法分节点已移除——②战法匹配由 StrategySubPipelineView 在外部渲染（ForwardTabSection 涨停叉②） */}
          {/* S094 §11 附录 A2：RiskNode 已移至后置共享区（PostSharedRegion 的 RiskAsymmetryCard） */}
        </div>
      ) : (
        // 非涨停叉：NonLimitupLane 自管⑤⑥⑦⑧四节点结构（见 NonLimitupPlaceholder.tsx）
        <NonLimitupLane date={date} candidates={nonLimitupCandidates} />
      )}
    </div>
  );
}

// S094 §11 附录 A1：LaneSwitcher 已删除——双叉切换由父组件 ForwardTabSection 控制

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

// S084：终选节点可展开，展示 final_candidates（DiagnosisCard）全部因子
//   spec §5.1：选股池 Tab = FunnelLayers（三层）+ final_candidates 候选矩阵（含所有因子）
function FinalCandidatesNode({ finals }: { finals: DiagnosisCard[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className={NODE}>
      <button onClick={() => setExpanded((v) => !v)} className="w-full text-left">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-sm font-medium">终选（final_candidates）</div>
            <div className="text-[11px] text-muted-foreground">含所有因子：gene_score/pool_item/derived/indicators</div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold text-primary">{finals.length}</span>
            <span className="text-[10px] text-muted-foreground">{expanded ? "▼" : "▶"}</span>
          </div>
        </div>
      </button>
      {expanded && finals.length > 0 && (
        <div className="mt-2 space-y-2 border-t border-border/30 pt-2">
          {finals.map((c) => (
            <DiagnosisCardView key={c.code} card={c} />
          ))}
        </div>
      )}
      {expanded && finals.length === 0 && (
        <div className="mt-2 text-xs text-muted-foreground">无最终候选</div>
      )}
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

/** F1：终选→战法匹配数据流传递节点（胶囊形带数字，消除视觉断流）。
 *  比 ArrowDown 更醒目：粗箭头 + 数字 pill + 下方标签，让用户看到"终选 N 只 → 进入战法匹配"是连续数据流。 */
function HandoffNode({ count, label }: { count: number; label: string }) {
  return (
    <div className="flex flex-col items-center py-1">
      {/* 胶囊形数字标签：粗箭头 + N 只 */}
      <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/40 bg-primary/10 px-2.5 py-0.5">
        <span className="text-[10px] font-semibold leading-none text-primary">↓</span>
        <span className="text-[11px] font-bold tabular-nums leading-none text-primary">{count}</span>
        <span className="text-[9px] leading-none text-primary/70">只</span>
      </div>
      {/* 下方标签：流向 */}
      <span className="mt-0.5 text-[10px] text-muted-foreground/80">{label}</span>
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
  const [expanded, setExpanded] = useState(false);
  if (isLoading) return <div className={`${NODE} text-xs text-muted-foreground`}>板块轮动加载中…</div>;
  if (!rot) return null;
  const dim = rot.multi_dim_rank.slice(0, 5);
  const top = rot.multi_rank.slice(0, 10);
  return (
    <div className={NODE}>
      <button onClick={() => setExpanded((v) => !v)} className="w-full text-left">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">板块轮动（多维度融合）</span>
          <span className="text-[10px] text-muted-foreground">{expanded ? "▼ 收起" : "▶ 展开"}</span>
        </div>
        {dim.length > 0 && (
          <div className="mt-0.5 text-xs text-muted-foreground">
            共振 TOP5：{dim.map((s) => `${s.label}(${s.zt_count_today},${s.dims.length}维)`).join(" · ")}
          </div>
        )}
        {!expanded && (
          <div className="mt-0.5 text-[11px] text-muted-foreground/80">
            全标签 TOP10：{top.map((s) => `${s.label}(${s.zt_count_today})`).join(" · ")}
          </div>
        )}
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5 border-t border-border/30 pt-2">
          {top.map((s) => (
            <div key={s.label} className="rounded border border-border/30 bg-card/20 p-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium">{s.label}</span>
                <span className="text-[10px] text-muted-foreground">
                  {s.zt_count_today} 涨停 · {s.dims.join("+")}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1 text-[10px]">
                {(s.codes || []).slice(0, 10).map((c) => (
                  <span key={c.code} className="rounded bg-muted/30 px-1 py-0.5 text-muted-foreground">
                    {c.name} <span className="text-muted-foreground/60">{c.code}</span>
                  </span>
                ))}
                {(s.codes || []).length > 10 && <span className="text-muted-foreground/60">…共 {s.codes.length} 只</span>}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="mt-1 text-[10px] text-muted-foreground/60">
        多维度共振（dims≥2）更可信；ths 106 全市场 + concept_map 缓存
      </div>
    </div>
  );
}

// S094 §11 附录 A2：ScoredBranch/ScoredDegraded/RiskNode 已删除——
// ②战法匹配由 StrategySubPipelineView 渲染，风控移至后置共享区 PostSharedRegion

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
  // S090 折叠态醒目选股数：input(次) → output(主,大字醒目) + 滤除 pill
  const filteredOut = layer.filtered_out?.length ?? Math.max(layer.input_count - layer.output_count, 0);
  // conditions 折叠态一行带过（超 2 个用"等"省略）；展开态 FunnelLayerCard 内已显 chips
  const conditions = layer.conditions ?? [];
  const condsSummary = conditions.length > 0
    ? conditions.length <= 2
      ? conditions.join(" · ")
      : `${conditions.slice(0, 2).join(" · ")} 等${conditions.length}项`
    : null;
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
          <div className="flex items-center gap-1.5">
            <span className="text-xs tabular-nums text-muted-foreground">{layer.input_count}</span>
            <span className="text-muted-foreground/50">→</span>
            <span className="text-base font-bold tabular-nums text-primary">{layer.output_count}</span>
            {filteredOut > 0 && (
              <span className="rounded bg-muted/30 px-1 text-[10px] tabular-nums text-muted-foreground">
                ↓{filteredOut}
              </span>
            )}
            <span className="ml-0.5 text-[10px] text-muted-foreground">{expanded ? "▼" : "▶"}</span>
          </div>
        </div>
        {/* 折叠态：过滤条件一行带过（展开态 FunnelLayerCard 内已显完整 chips） */}
        {!expanded && condsSummary && (
          <div className="mt-1 text-[10px] text-muted-foreground/70">
            过滤：{condsSummary}
          </div>
        )}
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
