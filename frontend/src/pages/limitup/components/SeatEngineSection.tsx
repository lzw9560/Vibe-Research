/** 席位引擎 */
import { useState, useEffect } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Loader2, Building2 } from "lucide-react";

interface SeatItem {
  seat_name: string;
  total_appearances: number;
  net_amt: number;
  stock_cooldown: number;
  last_seen: string;
}

export function SeatEngineSection() {
  const [seats, setSeats] = useState<SeatItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);

  const loadProfiles = () => {
    setLoading(true);
    // TODO: 实现席位画像 API
    setTimeout(() => {
      setSeats([]);
      setLoading(false);
    }, 500);
  };

  const buildProfiles = async () => {
    setBuilding(true);
    await new Promise(r => setTimeout(r, 1000));
    buildProfiles();
    setBuilding(false);
  };

  useEffect(() => { loadProfiles(); }, []);

  return (
    <div className="mb-6">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
          <Building2 className="h-4 w-4" /> 席位引擎
        </h3>
        <button onClick={buildProfiles} disabled={building}
          className="rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25 disabled:opacity-50">
          {building ? <Loader2 className="h-4 w-4 animate-spin" /> : "构建画像"}
        </button>
      </div>
      <GlassCard className="p-4">
        {loading ? (
          <p className="py-4 text-center text-sm text-muted-foreground/60">加载中…</p>
        ) : seats.length === 0 ? (
          <div className="py-4 text-center">
            <p className="text-sm text-muted-foreground">暂无席位数据</p>
            <p className="mt-1 text-xs text-muted-foreground/50">点击「构建画像」拉取历史龙虎榜数据</p>
          </div>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {seats.slice(0, 12).map((s) => (
              <div key={s.seat_name} className="rounded-lg bg-muted/20 p-2.5">
                <p className="truncate text-xs font-medium">{s.seat_name}</p>
                <div className="mt-1 flex items-center justify-between text-[11px]">
                  <span className="text-muted-foreground">出现 {s.total_appearances} 次</span>
                  <span className={`font-mono ${s.net_amt >= 0 ? "text-danger" : "text-success"}`}>
                    净{s.net_amt >= 0 ? "+" : ""}{(s.net_amt / 10000).toFixed(0)}万
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </GlassCard>
    </div>
  );
}
