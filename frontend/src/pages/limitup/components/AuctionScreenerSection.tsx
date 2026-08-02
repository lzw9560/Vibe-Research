/** 竞价预案 TOP N */
import { useState, useEffect, useCallback } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Loader2 } from "lucide-react";

export function AuctionScreenerSection() {
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().slice(0, 10));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    // TODO: 实现竞价筛选 API
    setTimeout(() => {
      setLoading(false);
    }, 500);
  }, [selectedDate]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="mb-6">
      <h3 className="mb-3 text-sm font-semibold text-muted-foreground">竞价预案 TOP N</h3>
      <GlassCard className="p-4">
        <div className="mb-3">
          <input type="date" value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)}
            className="rounded-lg border border-border bg-black/20 px-2 py-1 text-sm" />
        </div>
        {loading ? (
          <div className="flex items-center justify-center py-8"><Loader2 className="h-5 w-5 animate-spin" /></div>
        ) : error ? (
          <div className="py-4 text-center text-sm text-destructive">{error}</div>
        ) : (
          <div className="py-8 text-center text-sm text-muted-foreground">竞价筛选功能开发中</div>
        )}
      </GlassCard>
    </div>
  );
}
