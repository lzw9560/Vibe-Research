import { useState, useEffect, useCallback } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SeatProfileModal } from "@/components/layout/SeatProfileModal";
import { api, type SeatProfile } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── 主页面：席位引擎 ────────────────────────────────────────
export function SeatEngine() {
  const [profiles, setProfiles] = useState<Record<string, SeatProfile>>({});
  const [loading, setLoading] = useState(true);
  const [building, setBuilding] = useState(false);
  const [buildDone, setBuildDone] = useState(false);
  // 席位详情弹窗
  const [selectedSeat, setSelectedSeat] = useState<string | null>(null);

  const loadProfiles = useCallback(() => {
    setLoading(true);
    api.seatProfiles()
      .then((raw) => {
        // Backend returns {profiles: [...], total: N}
        const arr = Array.isArray(raw) ? raw : (raw as any).profiles || [];
        const dict: Record<string, SeatProfile> = {};
        for (const p of arr) {
          if (p.seat_name) dict[p.seat_name] = p;
        }
        setProfiles(dict);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  const handleBuild = useCallback(async () => {
    setBuilding(true);
    try {
      await api.seatBuildProfiles(180);
      setBuildDone(true);
      loadProfiles();
    } catch {
      // ignore
    } finally {
      setBuilding(false);
    }
  }, [loadProfiles]);

  // 按类型分组
  const grouped: Record<string, SeatProfile[]> = {};
  for (const [, p] of Object.entries(profiles)) {
    if (!grouped[p.seat_type]) grouped[p.seat_type] = [];
    grouped[p.seat_type].push(p);
  }
  // 按数量降序
  const groups = Object.entries(grouped).sort((a, b) => b[1].length - a[1].length);

  const typeColors: Record<string, string> = {
    "活跃游资": "text-primary",
    "量化席位": "text-info",
    "跟风席位": "text-muted-foreground",
    "机构专用": "text-accent",
    "inactive": "text-muted-foreground/40",
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-foreground">席位引擎</h2>
          <p className="mt-1 text-xs text-muted-foreground">龙虎榜席位统计特征 · 游资/量化/机构行为画像</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleBuild}
            disabled={building}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-xs font-medium text-primary shadow-glow transition-colors hover:bg-primary/25 disabled:opacity-50"
            title="构建席位画像（需数分钟）"
          >
            {building ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            {building ? "构建中…" : "构建画像"}
          </button>
          <button
            onClick={loadProfiles}
            className="text-muted-foreground hover:text-primary"
            title="刷新"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <GlassCard>
        {loading && !buildDone ? (
          <p className="py-4 text-center text-sm text-muted-foreground/60">加载中…</p>
        ) : groups.length === 0 ? (
          <div className="py-4 text-center">
            <p className="text-sm text-muted-foreground">暂无席位数据</p>
            <p className="mt-1 text-xs text-muted-foreground/50">点击「构建画像」拉取历史龙虎榜数据</p>
          </div>
        ) : (
          <div className="space-y-4">
            {groups.map(([type, seats]) => (
              <div key={type}>
                <div className="mb-1.5 flex items-center gap-2">
                  <span className={cn("text-xs font-medium", typeColors[type] || "text-muted-foreground")}>
                    {type}
                  </span>
                  <span className="text-[11px] text-muted-foreground/50">({seats.length})</span>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {seats.slice(0, 12).map((s) => (
                    <div
                      key={s.seat_name}
                      onClick={() => setSelectedSeat(s.seat_name)}
                      className="cursor-pointer rounded-lg bg-muted/20 p-2.5 transition-colors hover:bg-muted/30"
                    >
                      <p className="truncate text-xs font-medium">{s.seat_name}</p>
                      <div className="mt-1 flex items-center justify-between text-[11px]">
                        <span className="text-muted-foreground">出现 {s.total_appearances} 次</span>
                        <span className={cn("font-mono", s.net_amt >= 0 ? "text-danger" : "text-success")}>
                          净{s.net_amt >= 0 ? "+" : ""}{(s.net_amt / 10000).toFixed(0)}万
                        </span>
                      </div>
                      <p className="mt-0.5 text-[10px] text-muted-foreground/50">
                        交易 {s.stock_cooldown} 只 · 最后 {s.last_seen || "未知"}
                      </p>
                    </div>
                  ))}
                </div>
                {seats.length > 12 && (
                  <p className="mt-1 text-[11px] text-muted-foreground/50">… 还有 {seats.length - 12} 个席位</p>
                )}
              </div>
            ))}
            <p className="text-[11px] text-muted-foreground/50">
              免责声明：席位标签基于龙虎榜历史数据统计特征，不代表对未来行为的预测，不构成投资建议。
            </p>
          </div>
        )}
      </GlassCard>

      {/* 席位详情弹窗 */}
      {selectedSeat && (
        <SeatProfileModal
          seatName={selectedSeat}
          onClose={() => setSelectedSeat(null)}
        />
      )}
    </div>
  );
}
