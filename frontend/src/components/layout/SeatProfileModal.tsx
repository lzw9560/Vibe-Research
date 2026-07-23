import { useEffect, useState, useCallback } from "react";
import { X, Loader2, TrendingUp, TrendingDown, Clock, Tag } from "lucide-react";
import { api, ApiError, type SeatProfile, type ConsensusSignal } from "@/lib/api";
import { cn } from "@/lib/utils";

interface Props {
  seatName: string;
  onClose: () => void;
}

const TYPE_COLORS: Record<string, string> = {
  "活跃游资": "text-primary",
  "量化席位": "text-blue-400",
  "跟风席位": "text-muted-foreground",
  "机构专用": "text-purple-400",
  "inactive": "text-muted-foreground/40",
};

const TYPE_BGS: Record<string, string> = {
  "活跃游资": "bg-primary/10 text-primary",
  "量化席位": "bg-blue-400/10 text-blue-400",
  "跟风席位": "bg-muted-foreground/10 text-muted-foreground",
  "机构专用": "bg-purple-400/10 text-purple-400",
  "inactive": "bg-muted-foreground/5 text-muted-foreground/40",
};

export function SeatProfileModal({ seatName, onClose }: Props) {
  const [profile, setProfile] = useState<SeatProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [consensus, setConsensus] = useState<ConsensusSignal | null>(null);
  const [consensusLoading, setConsensusLoading] = useState(false);
  const [consensusError, setConsensusError] = useState<string | null>(null);

  const loadProfile = useCallback(() => {
    setLoading(true);
    api.seatProfile(seatName)
      .then(setProfile)
      .catch((e) => setError(e instanceof ApiError ? e.message : "席位加载失败"))
      .finally(() => setLoading(false));
  }, [seatName]);

  const loadConsensus = useCallback(() => {
    setConsensusLoading(true);
    setConsensusError(null);
    api.seatConsensus(seatName)
      .then(setConsensus)
      .catch((e) => setConsensusError(e instanceof ApiError ? e.message : "共识加载失败"))
      .finally(() => setConsensusLoading(false));
  }, [seatName]);

  useEffect(() => {
    loadProfile();
    loadConsensus();
  }, [loadProfile, loadConsensus]);

  // ESC 关闭
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const netColor = profile?.net_amt != null ? (profile.net_amt >= 0 ? "text-danger" : "text-success") : "text-muted-foreground";
  const typeColor = TYPE_COLORS[profile?.seat_type || ""] || "text-muted-foreground";
  const typeBg = TYPE_BGS[profile?.seat_type || ""] || "bg-muted-foreground/5 text-muted-foreground";

  const fmtAmt = (amt: number) => {
    if (amt >= 1e8) return `${(amt / 1e8).toFixed(2)} 亿`;
    if (amt >= 1e4) return `${(amt / 1e4).toFixed(1)} 万`;
    return amt.toLocaleString();
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="mx-4 max-h-[85vh] w-full max-w-2xl overflow-auto rounded-xl border border-border/60 bg-background/95 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 border-b border-border/50 bg-background/95 px-6 py-4 backdrop-blur-sm">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-bold">{seatName}</h2>
              <div className="mt-1 flex items-center gap-2">
                <span className={cn("inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium", typeBg)}>
                  {profile?.seat_type || "—"}
                </span>
                {profile?.last_seen && (
                  <span className="text-xs text-muted-foreground">最后出现: {profile.last_seen}</span>
                )}
              </div>
            </div>
            <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <span className="ml-3 text-sm text-muted-foreground">加载席位画像…</span>
          </div>
        ) : error ? (
          <div className="py-8 text-center text-sm text-destructive">{error}</div>
        ) : profile ? (
          <div className="p-6 space-y-6">
            {/* 核心指标 */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { label: "总出现次数", value: `${profile.total_appearances}`, icon: TrendingUp },
                { label: "净买入", value: fmtAmt(profile.net_amt), color: netColor, icon: profile.net_amt >= 0 ? TrendingUp : TrendingDown },
                { label: "平均买入", value: fmtAmt(profile.avg_buy_amt), icon: TrendingUp },
                { label: "平均卖出", value: fmtAmt(profile.avg_sell_amt), icon: TrendingDown },
              ].map((m) => (
                <div key={m.label} className="rounded-lg bg-muted/20 p-3 text-center">
                  <div className="flex items-center justify-center gap-1 text-muted-foreground/60">
                    <m.icon className="h-3 w-3" />
                    <p className="text-[10px]">{m.label}</p>
                  </div>
                  <p className={cn("mt-1 font-mono text-lg font-bold", m.color || "text-foreground")}>
                    {m.value}
                  </p>
                </div>
              ))}
            </div>

            {/* 买卖明细 */}
            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">买卖金额明细</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-muted/15 p-3">
                  <p className="text-[11px] text-muted-foreground">总买入</p>
                  <p className="mt-0.5 font-mono text-xl font-bold text-danger">{fmtAmt(profile.total_buy_amt)}</p>
                </div>
                <div className="rounded-lg bg-muted/15 p-3">
                  <p className="text-[11px] text-muted-foreground">总卖出</p>
                  <p className="mt-0.5 font-mono text-xl font-bold text-success">{fmtAmt(profile.total_sell_amt)}</p>
                </div>
              </div>
            </div>

            {/* 冷却期 & 其他 */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg bg-muted/20 p-3">
                <div className="flex items-center gap-1.5 text-muted-foreground/60">
                  <Clock className="h-3.5 w-3.5" />
                  <p className="text-[11px]">股票冷却期</p>
                </div>
                <p className="mt-1 font-mono text-lg font-bold text-foreground">{profile.stock_cooldown} 只</p>
              </div>
              <div className="rounded-lg bg-muted/20 p-3">
                <div className="flex items-center gap-1.5 text-muted-foreground/60">
                  <Tag className="h-3.5 w-3.5" />
                  <p className="text-[11px]">席位类型</p>
                </div>
                <p className={cn("mt-1 font-mono text-lg font-bold", typeColor)}>
                  {profile.seat_type}
                </p>
              </div>
            </div>

            {/* 席位共识信号 */}
            <div>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-medium text-muted-foreground">席位共识信号</p>
                {consensusLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
              </div>
              {consensusError ? (
                <p className="rounded-lg border border-border/30 bg-muted/10 p-3 text-xs text-muted-foreground/60">
                  {consensusError}
                </p>
              ) : consensus ? (
                <div className="rounded-lg border border-border/30 bg-muted/10 p-3">
                  <div className="flex items-center gap-2">
                    <span className={cn(
                      "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium",
                      consensus.signal === "多资金共识" ? "bg-danger/10 text-danger"
                      : consensus.signal === "机构主导" ? "bg-purple-400/10 text-purple-400"
                      : consensus.signal === "游资主导" ? "bg-primary/10 text-primary"
                      : consensus.signal === "分歧信号" ? "bg-warning/10 text-warning"
                      : "bg-muted-foreground/10 text-muted-foreground",
                    )}>
                      {consensus.signal || "无信号"}
                    </span>
                    <span className="text-[11px] text-muted-foreground/50">{consensus.date}</span>
                  </div>
                  {consensus.stock_code && (
                    <p className="mt-1.5 text-[11px] text-muted-foreground">
                      标的: {consensus.stock_code}
                    </p>
                  )}
                  {/* 详情展开 */}
                  {Object.entries(consensus.details || {}).length > 0 && (
                    <div className="mt-2 rounded bg-muted/20 p-2 text-[11px] text-muted-foreground/70">
                      {Object.entries(consensus.details).map(([k, v]) => (
                        <div key={k} className="flex justify-between gap-4">
                          <span className="capitalize">{k.replace(/_/g, " ")}</span>
                          <span className="font-mono">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {consensus.disclaimer && (
                    <p className="mt-2 text-[10px] text-muted-foreground/40 italic">{consensus.disclaimer}</p>
                  )}
                </div>
              ) : (
                <p className="rounded-lg border border-border/30 bg-muted/10 p-3 text-xs text-muted-foreground/60">
                  暂无共识数据
                </p>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
