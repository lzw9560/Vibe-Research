// S179 Phase 1: 申万 30 板块热力图（ECharts treemap，聚合一级板块，不裸渲染叶子）。
// 范式：useRef + useEffect + echarts.init（echarts 6 tree-shakeable import）。
// 保留最近有效 sectors——API 返空/失败时显示最近（标 stale hint，非伪装实时）。
import { useRef, useEffect, useState } from "react";
import * as echarts from "echarts/core";
import { TreemapChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import type { ComposeOption, EChartsType } from "echarts/core";
import type { TreemapSeriesOption } from "echarts/charts";
import type { TooltipComponentOption } from "echarts/components";
import { Loader2, RefreshCw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { SectorFlow } from "@/lib/api";

echarts.use([TreemapChart, TooltipComponent]);

type ChartOption = ComposeOption<TreemapSeriesOption | TooltipComponentOption>;

// A股红涨绿跌——与整个看板一致（Simon 2026-07-05 确认；非国际绿涨惯例，勿改）。
function pctToHeatColor(pct: number): string {
  const abs = Math.abs(pct);
  if (pct > 0) {
    if (abs > 5) return "#9b1c1c";
    if (abs > 3) return "#c0392b";
    if (abs > 1) return "#e74c3c";
    return "#ff6b6b";
  }
  if (pct < 0) {
    if (abs > 5) return "#155724";
    if (abs > 3) return "#1e7e34";
    if (abs > 1) return "#2ecc71";
    return "#6bcf7f";
  }
  return "#6b7280";
}

interface TreemapNodeData {
  name: string;
  value: number;
  itemStyle: { color: string };
  pct: number;
  net: number;
  firms: number;
}

function buildOption(sectors: SectorFlow[]): ChartOption {
  const items: TreemapNodeData[] = sectors.map((s) => ({
    name: s.name,
    value: Math.max(s.firms || 1, 1),
    itemStyle: { color: pctToHeatColor(s.pct) },
    pct: s.pct,
    net: s.net,
    firms: s.firms,
  }));

  return {
    tooltip: {
      formatter: (info: unknown) => {
        const d = (info as { data?: TreemapNodeData })?.data;
        if (!d) return "";
        const sign = d.pct > 0 ? "+" : "";
        const netSign = d.net > 0 ? "+" : "";
        return `<b>${d.name}</b><br/>涨跌 ${sign}${d.pct.toFixed(2)}%<br/>净流入 ${netSign}${d.net.toFixed(1)} 亿<br/>家数 ${d.firms}`;
      },
    },
    series: [
      {
        type: "treemap" as const,
        name: "申万板块",
        data: items,
        roam: false,
        nodeClick: "zoomToNode",
        breadcrumb: { show: false },
        label: {
          show: true,
          formatter: (info: unknown) => {
            const d = (info as { data?: TreemapNodeData })?.data;
            if (!d) return "";
            const sign = d.pct > 0 ? "+" : "";
            return `${d.name}\n${sign}${d.pct.toFixed(1)}%`;
          },
          fontSize: 11,
          color: "#fff",
          textShadowColor: "rgba(0,0,0,0.5)",
        },
        itemStyle: {
          borderColor: "#1a1a2e",
          borderWidth: 1,
          gapWidth: 1,
        },
        levels: [
          {
            itemStyle: {
              borderColor: "#1a1a2e",
              borderWidth: 1,
              gapWidth: 1,
            },
          },
        ],
      },
    ],
  } as ChartOption;
}

interface Props {
  sectors: SectorFlow[];
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}

// localStorage cache 最近有效 sectors（跨刷新保留）——Safari 无痕/配额 try-catch
const LAST_SECTORS_KEY = "vr-last-sectors";
function loadLastSectors(): { sectors: SectorFlow[]; time: string } | null {
  try {
    const raw = localStorage.getItem(LAST_SECTORS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed?.sectors)) return null;
    // L1 TTL：cache 超时不用（防长期 stale 误导，4h 过期）
    const savedAt = parsed.savedAt ? new Date(parsed.savedAt).getTime() : 0;
    if (savedAt && Date.now() - savedAt > 4 * 60 * 60 * 1000) return null;
    return parsed;
  } catch { return null; }
}
function saveLastSectors(sectors: SectorFlow[]): void {
  try {
    localStorage.setItem(LAST_SECTORS_KEY, JSON.stringify({
      sectors,
      time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      savedAt: new Date().toISOString(),  // L1 TTL timestamp
    }));
  } catch { /* 配额/隐私模式，静默忽略 */ }
}

export function MarketTreemap({ sectors, loading, error, onRefresh }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | null>(null);
  // 保留最近有效 sectors——API 返空/失败时显示最近（标 stale hint 非伪装实时）
  const [lastValid, setLastValid] = useState<{ sectors: SectorFlow[]; time: string } | null>(() => loadLastSectors());

  // init on mount + dispose on unmount
  useEffect(() => {
    if (!containerRef.current) return;
    chartRef.current = echarts.init(containerRef.current);
    const handleResize = () => chartRef.current?.resize();
    window.addEventListener("resize", handleResize);
    return () => {
      window.removeEventListener("resize", handleResize);
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  // cache 最近非空 sectors（localStorage 跨刷新保留）
  useEffect(() => {
    if (sectors.length > 0) {
      const entry = { sectors, time: new Date().toLocaleTimeString("zh-CN", { hour12: false }) };
      saveLastSectors(sectors);
      setLastValid(entry);
    }
  }, [sectors]);

  // effectiveSectors: 当前非空用当前，否则用 cache（保留最近）
  const effectiveSectors = sectors.length > 0 ? sectors : (lastValid?.sectors ?? []);
  const isStale = sectors.length === 0 && lastValid !== null; // 显示 cache 标 stale

  // update option when effectiveSectors changes
  useEffect(() => {
    if (!chartRef.current || effectiveSectors.length === 0) return;
    chartRef.current.setOption(buildOption(effectiveSectors));
  }, [effectiveSectors]);

  return (
    <GlassCard className="p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">申万板块热力图</h3>
        <button
          onClick={onRefresh}
          className="text-muted-foreground hover:text-primary"
          title="刷新板块数据"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      {/* honest banner: aggregate level + performance caveat（grill F10 / #11） */}
      <div className="mb-3 rounded-md bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
        聚合一级 30 板块 · 不裸渲染 5000 叶子 · 60fps 待 Phase 1 A6 压测确认
      </div>

      {effectiveSectors.length === 0 ? (
        // 无 cache 且当前空/失败 → 显空/失败
        <div className="flex h-[400px] items-center justify-center text-sm text-destructive">
          {error ? `板块数据加载失败：${error}` : loading ? "加载中…" : "暂无板块数据（可能是非交易时段）"}
        </div>
      ) : (
        <>
          {isStale && (
            // 显示 cache 标 stale hint（诚实标注非实时）
            <div className="mb-2 rounded bg-amber-500/10 px-2 py-1 text-xs text-amber-600">
              显示最近数据（{lastValid?.time}）· 当前 {error ? "API 失败" : "返空"}，非实时
            </div>
          )}
          <div ref={containerRef} className="h-[400px] w-full" />
        </>
      )}
    </GlassCard>
  );
}
