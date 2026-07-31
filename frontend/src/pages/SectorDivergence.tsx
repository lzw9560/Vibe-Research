import { useState, useEffect, useMemo } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { MetricCard } from "@/components/ui/MetricCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Badge } from "@/components/ui/Badge";
import {
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Activity,
  ArrowUpDown,
  Info,
} from "lucide-react";
import { api } from "@/lib/api";

// ─── Types ───────────────────────────────────────────────────────────────────

interface SectorDivergenceItem {
  sector: string;
  date: string;
  divergence_score: number;
  rotation_speed: number;
  up_count: number;
  down_count: number;
  avg_change_pct: number;
  std_change_pct: number;
  leader_code: string;
  leader_name: string;
  leader_change_pct: number;
  interpretation: string;
  last_updated: string;
}

interface SectorRotationData {
  date: string;
  sectors: Array<{
    name: string;
    change_pct: number;
    up_count: number;
    down_count: number;
  }>;
  rotation_speed: number;
  hot_sectors: string[];
  cold_sectors: string[];
  interpretation: string;
  last_updated: string;
}

interface SectorDivergenceHistory {
  date: string;
  avg_divergence: number;
  max_divergence: number;
  min_divergence: number;
  sector_count: number;
}

type SortField = "divergence_score" | "rotation_speed" | "avg_change_pct" | "sector";
type SortDir = "asc" | "desc";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function divergenceLabel(score: number): { label: string; variant: "danger" | "warning" | "success" } {
  if (score >= 70) return { label: "严重分化", variant: "danger" };
  if (score >= 50) return { label: "明显分化", variant: "warning" };
  if (score >= 30) return { label: "轻微分化", variant: "warning" };
  return { label: "一致", variant: "success" };
}

function rotationLabel(speed: number): { label: string; variant: "danger" | "warning" | "success" } {
  if (speed >= 70) return { label: "极快", variant: "danger" };
  if (speed >= 50) return { label: "较快", variant: "warning" };
  if (speed >= 30) return { label: "适中", variant: "success" };
  return { label: "缓慢", variant: "success" };
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function SectorDivergence() {
  const [divergenceData, setDivergenceData] = useState<SectorDivergenceItem[]>([]);
  const [rotationData, setRotationData] = useState<SectorRotationData | null>(null);
  const [historyData, setHistoryData] = useState<SectorDivergenceHistory[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortField, setSortField] = useState<SortField>("divergence_score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [historyDays, setHistoryDays] = useState(30);

  const loadData = async (days?: number) => {
    try {
      setError(null);
      const [divergence, rotation, history] = await Promise.all([
        api.sectorDivergence(),
        api.sectorRotation(),
        api.sectorDivergenceHistory(days || historyDays),
      ]);

      const divergenceList = Array.isArray(divergence) ? divergence : divergence?.data || [];
      const rotationResult = rotation?.data || rotation;
      const historyList = Array.isArray(history) ? history : [];

      setDivergenceData(divergenceList);
      setRotationData(rotationResult);
      setHistoryData(historyList);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleRefresh = () => {
    setRefreshing(true);
    loadData();
  };

  const handleHistoryDaysChange = (days: number) => {
    setHistoryDays(days);
    loadData(days);
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortField(field);
      setSortDir("desc");
    }
  };

  const sortedData = useMemo(() => {
    const data = [...divergenceData];
    data.sort((a, b) => {
      const aVal = a[sortField];
      const bVal = b[sortField];
      if (typeof aVal === "number" && typeof bVal === "number") {
        return sortDir === "asc" ? aVal - bVal : bVal - aVal;
      }
      return sortDir === "asc"
        ? String(aVal).localeCompare(String(bVal))
        : String(bVal).localeCompare(String(aVal));
    });
    return data;
  }, [divergenceData, sortField, sortDir]);

  const avgDivergence = useMemo(() => {
    if (divergenceData.length === 0) return 0;
    return Math.round(divergenceData.reduce((sum, item) => sum + item.divergence_score, 0) / divergenceData.length);
  }, [divergenceData]);

  const avgRotation = useMemo(() => {
    if (divergenceData.length === 0) return 0;
    return Math.round(divergenceData.reduce((sum, item) => sum + item.rotation_speed, 0) / divergenceData.length);
  }, [divergenceData]);

  const highDivergenceCount = useMemo(() => {
    return divergenceData.filter(item => item.divergence_score >= 50).length;
  }, [divergenceData]);

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      <PageHeader
        title="板块情绪分化度"
        subtitle="板块内部分化 + 轮动速度监控（客观数据，非行动建议）"
        actions={
          <button
            onClick={handleRefresh}
            disabled={loading || refreshing}
            className="inline-flex items-center gap-2 rounded-lg bg-primary/90 px-3 py-2 text-sm text-primary-foreground hover:bg-primary disabled:opacity-60"
          >
            {(loading || refreshing) ? (
              <RefreshCw className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            刷新
          </button>
        }
      />

      <Disclaimer compact />

      {error && (
        <GlassCard>
          <div className="p-4 text-sm text-red-600">加载失败：{error}</div>
        </GlassCard>
      )}

      {loading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : (
        <>
          {/* 统计卡片 */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <MetricCard
              label="平均分化度"
              value={avgDivergence}
              valueClassName={avgDivergence >= 50 ? "text-red-600" : avgDivergence >= 30 ? "text-amber-600" : "text-emerald-600"}
            />
            <MetricCard
              label="平均轮动速度"
              value={avgRotation}
              valueClassName={avgRotation >= 50 ? "text-red-600" : avgRotation >= 30 ? "text-amber-600" : "text-emerald-600"}
            />
            <MetricCard
              label="明显分化板块"
              value={highDivergenceCount}
              sub={`/ ${divergenceData.length}`}
              valueClassName={highDivergenceCount > divergenceData.length * 0.5 ? "text-red-600" : "text-amber-600"}
            />
          </div>

          {/* 板块分化度列表 */}
          <GlassCard>
            <SectionHeader
              title="板块分化度排行"
              subtitle={`共 ${divergenceData.length} 个板块 · 按分化度评分排序`}
            />
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                    <th className="px-3 py-2.5 font-medium">#</th>
                    <th className="px-3 py-2.5 font-medium">板块</th>
                    <th className="px-3 py-2.5 font-medium text-right">
                      <button onClick={() => handleSort("divergence_score")} className="inline-flex items-center gap-1 hover:text-foreground">
                        分化度 <ArrowUpDown className="h-3 w-3" />
                      </button>
                    </th>
                    <th className="px-3 py-2.5 font-medium text-center">分化等级</th>
                    <th className="px-3 py-2.5 font-medium text-right">
                      <button onClick={() => handleSort("rotation_speed")} className="inline-flex items-center gap-1 hover:text-foreground">
                        轮动速度 <ArrowUpDown className="h-3 w-3" />
                      </button>
                    </th>
                    <th className="px-3 py-2.5 font-medium text-right">涨跌家数</th>
                    <th className="px-3 py-2.5 font-medium text-right">均价变动%</th>
                    <th className="px-3 py-2.5 font-medium text-right">板块内标准差</th>
                    <th className="px-3 py-2.5 font-medium">龙头股</th>
                    <th className="px-3 py-2.5 font-medium">解读</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/30">
                  {sortedData.length === 0 ? (
                    <tr>
                      <td colSpan={10} className="py-8 text-center text-sm text-muted-foreground/60">
                        暂无板块数据
                      </td>
                    </tr>
                  ) : (
                    sortedData.map((item, idx) => {
                      const divLabel = divergenceLabel(item.divergence_score);
                      const rotLabel = rotationLabel(item.rotation_speed);
                      return (
                        <tr key={item.sector} className="transition-colors hover:bg-muted/20">
                          <td className="px-3 py-2.5 text-muted-foreground">{idx + 1}</td>
                          <td className="px-3 py-2.5 font-medium">{item.sector}</td>
                          <td className="px-3 py-2.5 text-right font-mono font-bold">
                            {item.divergence_score.toFixed(1)}
                          </td>
                          <td className="px-3 py-2.5 text-center">
                            <Badge variant={divLabel.variant}>{divLabel.label}</Badge>
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <div className="flex items-center justify-end gap-1">
                              <span className="font-mono">{item.rotation_speed.toFixed(1)}</span>
                              <Badge variant={rotLabel.variant} className="text-[10px]">{rotLabel.label}</Badge>
                            </div>
                          </td>
                          <td className="px-3 py-2.5 text-right">
                            <span className="text-emerald-600">{item.up_count}</span>
                            <span className="text-muted-foreground mx-1">/</span>
                            <span className="text-red-600">{item.down_count}</span>
                          </td>
                          <td className={`px-3 py-2.5 text-right font-mono ${item.avg_change_pct >= 0 ? "text-red-600" : "text-emerald-600"}`}>
                            {item.avg_change_pct >= 0 ? "+" : ""}{item.avg_change_pct.toFixed(2)}%
                          </td>
                          <td className="px-3 py-2.5 text-right font-mono text-muted-foreground">
                            {item.std_change_pct.toFixed(2)}%
                          </td>
                          <td className="px-3 py-2.5">
                            {item.leader_name ? (
                              <div>
                                <div className="font-medium">{item.leader_name}</div>
                                <div className="text-xs text-muted-foreground font-mono">{item.leader_code}</div>
                              </div>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-xs text-muted-foreground max-w-[200px]">
                            <div className="line-clamp-2">{item.interpretation}</div>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </GlassCard>

          {/* 板块轮动快照 */}
          {rotationData && (
            <GlassCard>
              <SectionHeader
                title="板块轮动快照"
                subtitle={`${rotationData.date} · 轮动速度 ${rotationData.rotation_speed.toFixed(1)}`}
              />
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-emerald-600">
                    <TrendingUp className="h-4 w-4" />
                    热门板块
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {rotationData.hot_sectors.length === 0 ? (
                      <span className="text-sm text-muted-foreground">暂无</span>
                    ) : (
                      rotationData.hot_sectors.map((sector) => (
                        <Badge key={sector} variant="success">{sector}</Badge>
                      ))
                    )}
                  </div>
                </div>
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-red-600">
                    <TrendingDown className="h-4 w-4" />
                    冷门板块
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {rotationData.cold_sectors.length === 0 ? (
                      <span className="text-sm text-muted-foreground">暂无</span>
                    ) : (
                      rotationData.cold_sectors.map((sector) => (
                        <Badge key={sector} variant="danger">{sector}</Badge>
                      ))
                    )}
                  </div>
                </div>
              </div>
              <div className="mt-4 rounded-lg bg-muted/30 p-3 text-xs text-muted-foreground">
                <div className="flex items-start gap-2">
                  <Info className="mt-0.5 h-4 w-4 shrink-0" />
                  <p>{rotationData.interpretation}</p>
                </div>
              </div>
            </GlassCard>
          )}

          {/* 历史趋势 */}
          <GlassCard>
            <div className="flex items-center justify-between">
              <SectionHeader
                title="分化度历史趋势"
                subtitle={`近 ${historyDays} 日平均分化度变化`}
              />
              <div className="flex items-center gap-2">
                {[7, 30, 60, 120].map((days) => (
                  <Button
                    key={days}
                    size="sm"
                    variant={historyDays === days ? "primary" : "ghost"}
                    onClick={() => handleHistoryDaysChange(days)}
                  >
                    {days}日
                  </Button>
                ))}
              </div>
            </div>
            {historyData.length === 0 ? (
              <div className="py-8 text-center text-sm text-muted-foreground/60">
                暂无历史数据
              </div>
            ) : (
              <div className="space-y-3">
                {historyData.map((item, idx) => (
                  <div
                    key={idx}
                    className="flex items-center justify-between rounded-lg border border-border/50 p-3"
                  >
                    <div className="flex-1">
                      <div className="flex items-center gap-3">
                        <span className="font-mono text-sm text-muted-foreground">{item.date}</span>
                        <span className="text-sm font-medium">
                          平均分化度：<span className="font-mono font-bold">{item.avg_divergence.toFixed(1)}</span>
                        </span>
                      </div>
                      <div className="mt-1 flex items-center gap-4 text-xs text-muted-foreground">
                        <span>最高 {item.max_divergence.toFixed(1)}</span>
                        <span>最低 {item.min_divergence.toFixed(1)}</span>
                        <span>{item.sector_count} 个板块</span>
                      </div>
                    </div>
                    <div className="ml-4 text-right">
                      <div className="flex items-center gap-1">
                        <Activity className={`h-4 w-4 ${item.avg_divergence >= 50 ? "text-red-600" : item.avg_divergence >= 30 ? "text-amber-600" : "text-emerald-600"}`} />
                        <span className={`text-sm font-bold ${item.avg_divergence >= 50 ? "text-red-600" : item.avg_divergence >= 30 ? "text-amber-600" : "text-emerald-600"}`}>
                          {item.avg_divergence.toFixed(1)}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </GlassCard>
        </>
      )}
    </div>
  );
}
