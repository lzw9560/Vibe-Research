/** 基因筛选表单（S029：阈值动态可配 B1 + 执行检索）。
 *  S051 D3：分段视图 qualified/all/custom——合格按后端 qualify 标志；全部全量按分降序（未合格行降级）；自定义走分数区间。
 *  保存阈值并重算：持久化 qualify/high/lookback → 触发后台重算（异步，~90s 落库）。
 */
import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { getGeneParams, type GeneScreenerParams } from "@/lib/limitup";
import { cn } from "@/lib/utils";

export interface GeneFilterParams {
  minScore: number;
  maxScore: number;
  date: string;
}

export type ViewMode = "qualified" | "all" | "custom";

interface Props {
  onSearch: (params: GeneFilterParams, mode: ViewMode) => void;
  onSwitchView: (mode: ViewMode, params: GeneFilterParams) => void;
  viewMode: ViewMode;
  onRecompute: (params: GeneScreenerParams) => void;
  recomputeBusy?: boolean;
}

const VIEW_TABS: { key: ViewMode; label: string }[] = [
  { key: "qualified", label: "合格" },
  { key: "all", label: "全部" },
  { key: "custom", label: "自定义分数段" },
];

export function GeneFilterForm({ onSearch, onSwitchView, viewMode, onRecompute, recomputeBusy }: Props) {
  const [minScore, setMinScore] = useState(50);  // 跟后端 GENE_QUALIFY_THRESHOLD 默认对齐，getGeneParams 返回后覆盖
  const [maxScore, setMaxScore] = useState(100);
  const [date, setDate] = useState("");  // S149: 默认空（非今日）——mount 搜 date=""→后端 resolve last_trading（周末/盘前今日无 zt 池→0）；用户选日期再按选日查
  const [qualify, setQualify] = useState(50);
  const [high, setHigh] = useState(60);
  const [lookback, setLookback] = useState(252);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // 初始阈值从后端加载（非硬编码）；默认 qualified 视图，首次检索拉全量后按 qualify 过滤
  useEffect(() => {
    getGeneParams()
      .then((p) => {
        const q = p?.gene_qualify_threshold ?? 50;
        if (p?.gene_high_threshold) setHigh(p.gene_high_threshold);
        if (p?.lookback_days) setLookback(p.lookback_days);
        setQualify(q);
        setMinScore(q);
        onSearch({ minScore: q, maxScore, date }, "qualified");
      })
      .catch(() => {
        onSearch({ minScore: 50, maxScore, date }, "qualified");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSearch = () => onSearch({ minScore, maxScore, date }, viewMode);
  const handleSwitchView = (mode: ViewMode) => onSwitchView(mode, { minScore, maxScore, date });

  const handleRecompute = () =>
    onRecompute({
      gene_qualify_threshold: qualify,
      gene_high_threshold: high,
      lookback_days: lookback,
    });

  return (
    <GlassCard className="p-4 mb-6">
      <h3 className="mb-3 text-sm font-semibold">基因筛选</h3>

      {/* S051 D3：分段视图切换 */}
      <div className="mb-3 flex items-center gap-1">
        {VIEW_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => handleSwitchView(t.key)}
            aria-pressed={viewMode === t.key}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
              viewMode === t.key
                ? "bg-primary text-primary-foreground"
                : "bg-muted/40 text-muted-foreground hover:bg-muted/60",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label className="text-xs text-muted-foreground">最低分（仅自定义模式生效）</label>
          <input
            type="number"
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            disabled={viewMode !== "custom"}
            className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm disabled:opacity-50"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">最高分（仅自定义模式生效）</label>
          <input
            type="number"
            value={maxScore}
            onChange={(e) => setMaxScore(Number(e.target.value))}
            disabled={viewMode !== "custom"}
            className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm disabled:opacity-50"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">日期</label>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm"
          />
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button onClick={handleSearch}>筛选</Button>
        <Button variant="ghost" size="sm" onClick={() => setShowAdvanced((v) => !v)}>
          {showAdvanced ? "收起阈值配置" : "阈值配置"}
        </Button>
      </div>

      {/* 高级：阈值动态可配（B1）——保存后触发后台重算 */}
      {showAdvanced && (
        <div className="mt-3 border-t border-border/40 pt-3">
          <p className="mb-2 text-xs text-muted-foreground">
            改阈值后「保存并重算」会持久化并触发后台预计算（异步，~90s 落库）；qualify/高基因标志稍后刷新可见。
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <label className="text-xs text-muted-foreground">合格阈值</label>
              <input
                type="number"
                value={qualify}
                onChange={(e) => setQualify(Number(e.target.value))}
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">高基因阈值</label>
              <input
                type="number"
                value={high}
                onChange={(e) => setHigh(Number(e.target.value))}
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">回溯天数</label>
              <input
                type="number"
                value={lookback}
                onChange={(e) => setLookback(Number(e.target.value))}
                className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div className="mt-2">
            <Button variant="ghost" size="sm" onClick={handleRecompute} disabled={recomputeBusy}>
              {recomputeBusy ? "重算中…" : "保存并重算"}
            </Button>
          </div>
        </div>
      )}
    </GlassCard>
  );
}
