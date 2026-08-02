/** 基因筛选表单 */
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";

interface Props {
  onSearch: (params: GeneFilterParams) => void;
}

interface GeneFilterParams {
  minScore: number;
  maxScore: number;
  date: string;
}

export function GeneFilterForm({ onSearch }: Props) {
  const [minScore, setMinScore] = useState(60);
  const [maxScore, setMaxScore] = useState(100);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));

  const handleSearch = () => {
    onSearch({ minScore, maxScore, date });
  };

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
      <div className="mt-3">
        <Button onClick={handleSearch}>筛选</Button>
      </div>
    </GlassCard>
  );
}
