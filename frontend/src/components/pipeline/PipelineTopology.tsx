// S099 拓扑主视图：echarts graph ①~⑧ pipeline nodes + 涨停/非涨停分叉。
// 替代原 ForwardTabSection 的 ①~⑧ 垂直节点列表——graph 为主视图，细节折叠。
// ②⑦ click → expand StrategySubPipelineView inline（战法分组折叠入拓扑）。
// 徽标 per node（命中数/数据态/通过率）+ 复选框 toggle + localStorage 持久化。
// 工程底线：不臆造——query 无数据返 "—"/"未取得"；graph 结构常驻（数据空也显拓扑）。
// grill design B+（2026-08-26 收敛）：topology 直接替代（非 overlay），细节折叠。
import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import * as echarts from "echarts/core";
import { GraphChart } from "echarts/charts";
import { TooltipComponent, LegendComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import { StrategySubPipelineView } from "./StrategySubPipelineView";
import { NonLimitupLane } from "./NonLimitupPlaceholder";
import { CollapsibleFold } from "@/components/ui/CollapsibleFold";
import CandidateFunnelEmbed from "@/components/workflow/CandidateFunnelEmbed";
import { PremarketSelectionSection } from "@/components/workflow/PremarketSelectionSection";
import { CandidateFactorTable } from "@/components/workflow/CandidateFactorTable";
import type { PreMarketBriefing, ScoredCandidate, FunnelLayer } from "@/lib/api";
import type { DiagnosisCard } from "@/lib/candidates";
import type { CrossValidationGroups } from "@/lib/query/useCrossValidation";

// Graph chart 自注册（NOT in useECharts hook——grill design 要求：graph chart 未在 useECharts 注册）。
// useECharts hook 只注册了 Line/Scatter/Radar + 组件；GraphChart 仅在 GraphView.tsx（另一 chunk）注册。
// 本组件自注册确保不依赖 GraphView 的加载。
echarts.use([GraphChart, TooltipComponent, LegendComponent, CanvasRenderer]);

// ---- localStorage key for badge field preferences ----
const LS_KEY = "s099-topology-badge-fields";

// ---- Badge field toggle options ----
const BADGE_FIELDS = ["hitCount", "dataStatus", "passRate"] as const;
type BadgeField = (typeof BADGE_FIELDS)[number];

const FIELD_LABELS: Record<BadgeField, string> = {
  hitCount: "命中数",
  dataStatus: "数据态",
  passRate: "通过率",
};

// ---- Pipeline node definitions (fixed layout: layout='none' with x/y) ----
interface NodeDef {
  id: string;
  name: string;
  x: number;
  y: number;
  category: "入口" | "涨停叉" | "非涨停叉";
  /** ②⑦ 可展开战法分组（click → expand StrategySubPipelineView inline）。 */
  expandable?: "strategy-limitup" | "strategy-nonlimitup";
}

const NODE_DEFS: NodeDef[] = [
  { id: "root", name: "盘前简报 F", x: 300, y: 20, category: "入口" },
  // 涨停叉（左列）
  { id: "n1", name: "① 涨停股池+漏斗", x: 80, y: 110, category: "涨停叉" },
  { id: "n2", name: "② 战法匹配", x: 80, y: 200, category: "涨停叉", expandable: "strategy-limitup" },
  { id: "n3", name: "③ breakout", x: 80, y: 290, category: "涨停叉" },
  { id: "n4", name: "④ 交叉验证", x: 80, y: 380, category: "涨停叉" },
  // 非涨停叉（右列）
  { id: "n5", name: "⑤ 选股宇宙", x: 520, y: 110, category: "非涨停叉" },
  { id: "n6", name: "⑥ K线形态", x: 520, y: 200, category: "非涨停叉" },
  { id: "n7", name: "⑦ 战法匹配", x: 520, y: 290, category: "非涨停叉", expandable: "strategy-nonlimitup" },
  { id: "n8", name: "⑧ 候选终选", x: 520, y: 380, category: "非涨停叉" },
];

const EDGES = [
  { source: "root", target: "n1" },
  { source: "root", target: "n5" },
  { source: "n1", target: "n2" },
  { source: "n2", target: "n3" },
  { source: "n3", target: "n4" },
  { source: "n5", target: "n6" },
  { source: "n6", target: "n7" },
  { source: "n7", target: "n8" },
];

// ---- Badge computation ----
interface NodeBadge {
  hitCount?: number | string;
  dataStatus?: string;
  passRate?: number | null;
}

/** 从 scored_candidates 的 strategy_funnel 条件中取平均 pass_rate（无 funnel 返 null）。 */
function computePassRate(candidates: ScoredCandidate[]): number | null {
  const funnels = candidates
    .map((c) => c.strategy_funnel)
    .filter((f): f is NonNullable<ScoredCandidate["strategy_funnel"]> => !!f);
  if (funnels.length === 0) return null;
  let total = 0;
  let count = 0;
  for (const f of funnels) {
    for (const cond of f.conditions) {
      if (cond.pass_rate != null) {
        total += cond.pass_rate;
        count++;
      }
    }
  }
  return count > 0 ? total / count : null;
}

/** 从 briefing + funnel_layers + cv 算出每个节点的徽标数据。 */
function computeBadges(
  briefing: PreMarketBriefing | null | undefined,
  funnelLayers: FunnelLayer[] | undefined,
  cv: CrossValidationGroups,
): Record<string, NodeBadge> {
  const scored = briefing?.scored_candidates ?? [];
  const marketScan = briefing?.market_scan_scored ?? [];
  const finals = briefing?.final_candidates ?? [];
  const ztCount = briefing?.market_emotion?.zt_count;
  const r1 = funnelLayers?.find((l) => l.layer_id === "R1");

  const scoredUnique = new Set(scored.map((s) => s.code)).size;
  const marketScanUnique = new Set(marketScan.map((s) => s.code)).size;
  const breakoutTotal = cv.breakoutOnly.length + cv.dual.length;

  const ds = (hasData: boolean) => (hasData ? "已取得" : "未取得");

  return {
    root: { hitCount: ztCount ?? finals.length },
    n1: {
      hitCount: ztCount ?? finals.length,
      dataStatus: ds(!!r1),
      passRate: r1 && r1.input_count > 0 ? r1.output_count / r1.input_count : null,
    },
    n2: {
      hitCount: scoredUnique,
      dataStatus: ds(scored.length > 0),
      passRate: computePassRate(scored),
    },
    n3: {
      hitCount: breakoutTotal,
      dataStatus: ds(!cv.isLoading),
      passRate: null,
    },
    n4: {
      hitCount: cv.dual.length,
      dataStatus: ds(!cv.isLoading),
      passRate: null,
    },
    n5: {
      hitCount: marketScanUnique,
      dataStatus: ds(marketScan.length > 0),
      passRate: null,
    },
    n6: {
      hitCount: marketScanUnique,
      dataStatus: ds(marketScan.length > 0),
      passRate: null,
    },
    n7: {
      hitCount: marketScanUnique,
      dataStatus: ds(marketScan.length > 0),
      passRate: computePassRate(marketScan),
    },
    n8: {
      hitCount: marketScanUnique,
      dataStatus: ds(marketScan.length > 0),
      passRate: null,
    },
  };
}

// ---- echarts option builder ----
function formatPct(v: number | null | undefined): string {
  return v != null ? `${Math.round(v * 100)}%` : "—";
}

function buildOption(
  badges: Record<string, NodeBadge>,
  fields: Set<BadgeField>,
): EChartsOption {
  const categories = [
    { name: "入口" },
    { name: "涨停叉" },
    { name: "非涨停叉" },
  ];
  const catIndex = (c: string): number =>
    categories.findIndex((cat) => cat.name === c);

  const COLORS: Record<string, string> = {
    入口: "#a78bfa",
    涨停叉: "#f97316",
    非涨停叉: "#3b82f6",
  };

  return {
    tooltip: {
      trigger: "item",
      formatter: (params: { data?: { id?: string; name?: string } }): string => {
        const d = params?.data;
        if (!d) return "";
        const b = badges[d.id ?? ""];
        if (!b) return d.name ?? "";
        const lines = [d.name ?? ""];
        if (fields.has("hitCount")) lines.push(`命中: ${b.hitCount ?? "—"}`);
        if (fields.has("dataStatus")) lines.push(`数据态: ${b.dataStatus ?? "—"}`);
        if (fields.has("passRate")) lines.push(`通过率: ${formatPct(b.passRate)}`);
        return lines.join("<br/>");
      },
    },
    legend: [{ data: categories.map((c) => c.name), bottom: 5 }],
    series: [
      {
        type: "graph",
        layout: "none",
        roam: true,
        draggable: true,
        categories,
        top: 10,
        bottom: 40,
        left: 10,
        right: 10,
        data: NODE_DEFS.map((n) => {
          const b = badges[n.id];
          const lines = [n.name];
          if (fields.has("hitCount") && b?.hitCount != null) lines.push(`命中 ${b.hitCount}`);
          if (fields.has("dataStatus") && b?.dataStatus) lines.push(`态 ${b.dataStatus}`);
          if (fields.has("passRate") && b?.passRate != null) lines.push(`通过率 ${formatPct(b.passRate)}`);
          return {
            id: n.id,
            name: n.name,
            x: n.x,
            y: n.y,
            symbolSize: n.expandable ? 42 : 34,
            category: catIndex(n.category),
            itemStyle: {
              color: COLORS[n.category],
              borderColor: n.expandable ? "#fbbf24" : "rgba(255,255,255,0.2)",
              borderWidth: n.expandable ? 3 : 1,
            },
            label: {
              show: true,
              position: n.x < 300 ? "right" : n.x > 300 ? "left" : "bottom",
              formatter: lines.join("\n"),
              fontSize: 11,
              lineHeight: 15,
              color: "#e5e7eb",
              backgroundColor: "rgba(15,23,42,0.6)",
              padding: [2, 4],
              borderRadius: 3,
            },
          };
        }),
        links: EDGES.map((e) => {
          const isFork = e.source === "root";
          return {
            source: e.source,
            target: e.target,
            lineStyle: {
              color: isFork ? "#8b5cf6" : "#6b7280",
              width: isFork ? 2.5 : 1.5,
              type: isFork ? "dashed" : "solid",
              curveness: 0.1,
            },
          };
        }),
        emphasis: { focus: "adjacency" },
      },
    ],
  } as EChartsOption;
}

// ---- Props ----
interface PipelineTopologyProps {
  briefing: PreMarketBriefing | null | undefined;
  F: string;
  forward: string;
  funnelLayers: FunnelLayer[] | undefined;
  cv: CrossValidationGroups;
}

/**
 * S099 拓扑主视图：echarts graph ①~⑧ pipeline + 涨停/非涨停分叉。
 * 直接替代原 ForwardTabSection 的垂直节点列表（grill B+ 设计）。
 * ②⑦ click → expand StrategySubPipelineView inline。
 * 徽标 per node + 复选框 toggle + localStorage 持久化。
 */
export function PipelineTopology({
  briefing,
  F,
  forward,
  funnelLayers,
  cv,
}: PipelineTopologyProps) {
  const navigate = useNavigate();
  const chartRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<echarts.ECharts | null>(null);
  // 默认展开 ②（涨停战法分组）——与原 StrategySubPipelineView defaultOpen=true 一致
  const [expandedNode, setExpandedNode] = useState<string | null>("n2");
  const [badgeFields, setBadgeFields] = useState<Set<BadgeField>>(() => {
    try {
      const saved = localStorage.getItem(LS_KEY);
      if (saved) {
        const arr = JSON.parse(saved) as BadgeField[];
        return new Set(arr.length > 0 ? arr : [...BADGE_FIELDS]);
      }
    } catch {
      /* ignore malformed localStorage */
    }
    return new Set([...BADGE_FIELDS]);
  });

  // 徽标数据（每次 render 重算——轻量，无 useMemo 必要）
  const badges = computeBadges(briefing, funnelLayers, cv);

  // refs 持有最新值，避免 effect 重跑（init effect 只跑一次）
  const badgesRef = useRef(badges);
  badgesRef.current = badges;
  const fieldsRef = useRef(badgeFields);
  fieldsRef.current = badgeFields;
  const onNodeClickRef = useRef<(nodeId: string) => void>(() => {});
  onNodeClickRef.current = (nodeId: string) => {
    const def = NODE_DEFS.find((n) => n.id === nodeId);
    if (def?.expandable) {
      setExpandedNode((prev) => (prev === nodeId ? null : nodeId));
    }
  };

  // ---- Init echarts instance (once) ----
  useEffect(() => {
    const el = chartRef.current;
    if (!el) return;
    const instance = echarts.init(el);
    instanceRef.current = instance;

    // 初始 option
    instance.setOption(buildOption(badgesRef.current, fieldsRef.current), true);

    // 节点点击 → 展开 ②⑦（dataType='node' 或 'main'，跳过 edge）
    instance.on("click", (params: unknown) => {
      const p = params as { dataType?: string; data?: { id?: string } };
      if (!p?.data?.id || p.dataType === "edge") return;
      onNodeClickRef.current(p.data.id);
    });

    // 响应式 resize
    const onResize = () => instanceRef.current?.resize();
    window.addEventListener("resize", onResize);
    const ro = new ResizeObserver(() => instanceRef.current?.resize());
    ro.observe(el);

    return () => {
      window.removeEventListener("resize", onResize);
      ro.disconnect();
      instanceRef.current?.dispose();
      instanceRef.current = null;
    };
  }, []);

  // ---- Update option when data or badge fields change ----
  useEffect(() => {
    instanceRef.current?.setOption(buildOption(badges, badgeFields), true);
  }, [badges, badgeFields]);

  // ---- Persist badge fields to localStorage ----
  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify([...badgeFields]));
    } catch {
      /* ignore quota errors */
    }
  }, [badgeFields]);

  const toggleField = useCallback((field: BadgeField) => {
    setBadgeFields((prev) => {
      const next = new Set(prev);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  }, []);

  // ---- 派生数据（供折叠区组件用） ----
  const scoredCandidates: ScoredCandidate[] = briefing?.scored_candidates ?? [];
  const marketScanScored: ScoredCandidate[] = briefing?.market_scan_scored ?? [];
  const finalCandidates: DiagnosisCard[] = briefing?.final_candidates ?? [];
  const ztCount = briefing?.market_emotion?.zt_count ?? undefined;

  return (
    <div className="space-y-3">
      {/* ============ 复选框：徽标字段 toggle ============ */}
      <div className="flex items-center gap-4 rounded-lg border border-border/30 bg-card/20 px-3 py-2">
        <span className="text-xs text-muted-foreground/70">徽标字段</span>
        {BADGE_FIELDS.map((field) => (
          <label key={field} className="flex items-center gap-1 text-xs">
            <input
              type="checkbox"
              checked={badgeFields.has(field)}
              onChange={() => toggleField(field)}
              className="h-3 w-3"
            />
            <span className="text-muted-foreground">{FIELD_LABELS[field]}</span>
          </label>
        ))}
        <span className="ml-auto text-[10px] text-muted-foreground/50">
          ②⑦ 金框节点可点击展开战法分组
        </span>
      </div>

      {/* ============ echarts graph 主视图 ============ */}
      <div ref={chartRef} className="w-full" style={{ height: 480 }} />

      {/* ============ ②⑦ 展开面板（click → inline StrategySubPipelineView） ============ */}
      {expandedNode === "n2" && (
        <StrategySubPipelineView
          scoredCandidates={scoredCandidates}
          marketScanScored={marketScanScored}
          lane="limitup"
          scoredTotal={scoredCandidates.length}
        />
      )}
      {expandedNode === "n7" && (
        <StrategySubPipelineView
          scoredCandidates={scoredCandidates}
          marketScanScored={marketScanScored}
          lane="non-limitup"
        />
      )}

      {/* ============ 折叠细节区（①③⑤⑥⑦⑧——graph 外可展开） ============ */}
      {/* ① 涨停股池+漏斗（CandidateFunnelEmbed，date=F） */}
      <CollapsibleFold
        title="① 涨停股池+漏斗"
        subtitle="CandidateFunnelEmbed · R1 涨停池全量直通"
        defaultOpen={false}
      >
        <CandidateFunnelEmbed
          date={briefing?.data_date ?? F}
          onPick={(code) => navigate(`/stock/${code}`)}
          snapshotLayers={funnelLayers}
          scoredCandidates={scoredCandidates}
          marketScanScored={marketScanScored}
          finalCandidates={finalCandidates}
          ztPoolSize={ztCount}
          sharedSectorRotation={true}
        />
      </CollapsibleFold>

      {/* ①b 候选因子表（异步回填的基因分/八项标准/量价/资金/涨停池/分时派生/K线派生） */}
      {finalCandidates.length > 0 && (
        <CollapsibleFold
          title="候选因子表"
          subtitle={`终选 ${finalCandidates.length} 只 · 基因分 · 八项标准 · 量价/资金 · 涨停池原始 · 分时派生 · K线派生`}
          defaultOpen={false}
        >
          <CandidateFactorTable candidates={finalCandidates} date={briefing?.data_date ?? F} />
        </CollapsibleFold>
      )}

      {/* ③ breakout 弱信号（PremarketSelectionSection，date=forward） */}
      <CollapsibleFold
        title="③ breakout 弱信号"
        subtitle="PremarketSelectionSection · date=forward"
        defaultOpen={false}
      >
        <PremarketSelectionSection date={forward} />
      </CollapsibleFold>

      {/* ⑤⑥⑦⑧ 非涨停叉（NonLimitupLane 自管四节点结构） */}
      <CollapsibleFold
        title="⑤⑥⑦⑧ 非涨停叉"
        subtitle="选股宇宙 · K线形态 · 战法匹配 · 候选终选"
        defaultOpen={false}
      >
        <NonLimitupLane
          date={briefing?.data_date ?? F}
          candidates={marketScanScored}
        />
      </CollapsibleFold>
    </div>
  );
}
