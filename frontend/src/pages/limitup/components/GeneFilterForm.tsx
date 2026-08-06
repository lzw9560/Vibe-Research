/** 基因筛选表单（S029：阈值动态可配 B1 + 执行检索）。
 *  筛选：按 minScore/maxScore 即时过滤得分（不等重算）。
 *  保存阈值并重算：持久化 qualify/high/lookback → 触发后台重算（异步，~90s 落库）。
 */
import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { getGeneParams, type GeneScreenerParams } from "@/lib/limitup";

export interface GeneFilterParams {
  minScore: number;
  maxScore: number;
  date: string;
}

interface Props {
  onSearch: (params: GeneFilterParams) => void;
  onRecompute: (params: GeneScreenerParams) => void;
  recomputeBusy?: boolean;
}

export function GeneFilterForm({ onSearch, onRecompute, recomputeBusy }: Props) {
  const [minScore, setMinScore] = useState(60);
  const [maxScore, setMaxScore] = useState(100);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [qualify, setQualify] = useState(60);
  const [high, setHigh] = useState(75);
  const [lookback, setLookback] = useState(252);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // 初始阈值从后端加载（非硬编码）
  useEffect(() => {
    getGeneParams()
      .then((p) => {
        if (p?.gene_qualify_threshold) setQualify(p.gene_qualify_threshold);
        if (p?.gene_high_threshold) setHigh(p.gene_high_threshold);
        if (p?.lookback_days) setLookback(p.lookback_days);
      })
      .catch(() => {
        /* 后端未起/未配，沿用默认 */
      });
  }, []);

  const handleSearch = () => onSearch({ minScore, maxScore, date });

  const handleRecompute = () =>
    onRecompute({
      gene_qualify_threshold: qualify,
      gene_high_threshold: high,
      lookback_days: lookback,
    });

  return (
    <GlassCard className="p-4 mb-6">
      <h3 className="mb-3 text-sm font-semibold">基因筛选</h3>
      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label className="text-xs text-muted-foreground">最低分</label>
          <input
            type="number"
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">最高分</label>
          <input
            type="number"
            value={maxScore}
            onChange={(e) => setMaxScore(Number(e.target.value))}
            className="w-full rounded-lg border border-border bg-black/20 px-3 py-2 text-sm"
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
