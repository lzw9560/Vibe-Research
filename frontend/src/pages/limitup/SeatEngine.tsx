import { useState, useCallback } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { PageHeader } from "@/components/ui/PageHeader";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { SeatProfileModal } from "@/components/layout/SeatProfileModal";
import { api, type SeatProfile } from "@/lib/api";
import { useSeatProfiles } from "@/lib/query";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { cn } from "@/lib/utils";

// ── 主页面：席位引擎 ────────────────────────────────────────
export function SeatEngine() {
  // T9：原 useState(profiles/loading) + useCallback(loadProfiles) + useEffect → useSeatProfiles()。
  // 构建画像（POST seatBuildProfiles）仍为直接调用，成功后 refetch() 刷新。
  // 注：useSeatProfiles 经 Opts 参数化 data 已推断为 {profiles: SeatProfile[]; total: number} | undefined，无需 cast。
  const { data: profilesRaw, isLoading: loading, refetch } = useSeatProfiles();
  const [building, setBuilding] = useState(false);
  const [buildDone, setBuildDone] = useState(false);
  // 席位详情弹窗
  const [selectedSeat, setSelectedSeat] = useState<string | null>(null);

  // 后端返回 {profiles: [...], total: N}，构建 seat_name → profile 字典
  const profiles: Record<string, SeatProfile> = {};
  for (const p of profilesRaw?.profiles ?? []) {
    if (p.seat_name) profiles[p.seat_name] = p;
  }

  const handleBuild = useCallback(async () => {
    setBuilding(true);
    try {
      await api.seatBuildProfiles(180);
      setBuildDone(true);
      refetch();
    } catch {
      // ignore
    } finally {
      setBuilding(false);
    }
  }, [refetch]);

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

  // S066 AskAi：注入席位画像统计
  const allProfiles = profilesRaw?.profiles ?? [];
  const askAiContext = [
    `当前页面：席位引擎（SeatEngine）`,
    `画像总数：${profilesRaw?.total ?? 0} 个席位`,
    groups.length > 0
      ? `分类分布：${groups.map(([type, list]) => `${type}×${list.length}`).join("，")}`
      : `分类：未取得（未构建或空）`,
    allProfiles.length > 0
      ? `Top 活跃席位：${allProfiles.slice(0, 8).map((p) => `${p.seat_name.slice(0, 12)}(净${(p.net_amt / 1e8).toFixed(1)}亿/${p.seat_type})`).join("，")}`
      : ``,
  ].filter(Boolean).join("\n");

  return (
    <div className="space-y-4">
      <PageHeader
        title="席位引擎"
        subtitle="龙虎榜席位统计特征 · 游资/量化/机构行为画像"
        actions={
          <div className="flex items-center gap-2">
            <AskAiButton context={askAiContext} />
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
              onClick={() => refetch()}
              className="text-muted-foreground hover:text-primary"
              title="刷新"
            >
              <RefreshCw className="h-3.5 w-3.5" />
            </button>
          </div>
        }
      />

      <GlassCard>
        {loading && !buildDone ? (
          <div className="py-8">
            <Skeleton className="mx-auto h-6 w-32" />
          </div>
        ) : groups.length === 0 ? (
          <EmptyState
            icon={<RefreshCw className="h-8 w-8 text-muted-foreground/40" />}
            title="暂无席位数据"
            description="点击「构建画像」拉取历史龙虎榜数据"
          />
        ) : (
          <div className="space-y-4">
            {groups.map(([type, seats]) => (
              <div key={type}>
                <SectionHeader
                  title={
                    <span className="flex items-center gap-2">
                      <span className={cn("text-xs font-medium", typeColors[type] || "text-muted-foreground")}>
                        {type}
                      </span>
                      <span className="text-[11px] text-muted-foreground/50">({seats.length})</span>
                    </span>
                  }
                />
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
