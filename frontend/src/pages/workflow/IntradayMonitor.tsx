import { useState, useEffect, useCallback, useRef } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Badge } from "@/components/ui/Badge";
import {
  Activity,
  Bell,
  TrendingUp,
  ShieldAlert,
  RefreshCw,
  Clock,
  ArrowUp,
  ArrowDown,
  Minus,
  Volume2,
  VolumeX,
} from "lucide-react";

// ─── TypeScript Interfaces ───────────────────────────────────────────────────

interface SignalItem {
  code: string;
  name?: string;
  signal_type?: string;
  type?: string;
  reasoning?: string;
  description?: string;
  time?: string;
}

interface AlertItem {
  code: string;
  name?: string;
  alert_level?: string;
  level?: string;
  condition?: string;
  message?: string;
  time?: string;
}

interface AdjustmentItem {
  code: string;
  name?: string;
  action?: string;
  reason?: string;
  time?: string;
}

interface IntradayData {
  date: string;
  signals: SignalItem[];
  alerts: AlertItem[];
  adjustments: AdjustmentItem[];
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SIGNAL_TYPE_COLORS: Record<string, "primary" | "success" | "warning" | "danger" | "info"> = {
  buy: "success",
  sell: "danger",
  hold: "info",
  strong_buy: "success",
  strong_sell: "danger",
};

const ALERT_LEVEL_COLORS: Record<string, "danger" | "warning" | "info"> = {
  high: "danger",
  medium: "warning",
  low: "info",
};

const ACTION_BADGE_MAP: Record<string, "success" | "danger" | "default"> = {
  add: "success",
  reduce: "danger",
  close: "default",
  加: "success",
  减: "danger",
  平: "default",
};

const ACTION_ICON_MAP: Record<string, typeof ArrowUp | typeof ArrowDown | typeof Minus> = {
  add: ArrowUp,
  reduce: ArrowDown,
  close: Minus,
  加: ArrowUp,
  减: ArrowDown,
  平: Minus,
};

function normalizeAction(raw?: string): string {
  if (!raw) return raw ?? "";
  const lower = raw.toLowerCase();
  if (lower.includes("add") || lower.includes("买") || lower === "加") return "add";
  if (lower.includes("reduce") || lower.includes("sell") || lower.includes("卖") || lower === "减") return "reduce";
  if (lower.includes("close") || lower.includes("平")) return "close";
  return raw;
}

function timeAgo(from: string | undefined): string {
  if (!from) return "";
  try {
    const diff = Date.now() - new Date(from).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ${mins % 60}m ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  } catch {
    return "";
  }
}

function resolveSignals(resp: Response): Promise<SignalItem[]> {
  return resp.ok ? resp.json().then((b) => b?.data ?? b ?? []) : Promise.resolve([]);
}

function resolveAlerts(resp: Response): Promise<AlertItem[]> {
  return resp.ok ? resp.json().then((b) => b?.data ?? b ?? []) : Promise.resolve([]);
}

function resolveAdjustments(resp: Response): Promise<AdjustmentItem[]> {
  return resp.ok ? resp.json().then((b) => b?.data ?? b ?? []) : Promise.resolve([]);
}

// ─── Sound Notification Hook ─────────────────────────────────────────────────

function useSoundNotification(enabled: boolean) {
  const audioCtxRef = useRef<AudioContext | null>(null);

  const playAlert = useCallback(() => {
    if (!enabled) return;
    try {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new AudioContext();
      }
      const ctx = audioCtxRef.current;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.type = "sine";
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(440, ctx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.3, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.4);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.4);
    } catch {
      // Audio API not available – silently ignore
    }
  }, [enabled]);

  return playAlert;
}

// ─── Desktop Notification Helper ─────────────────────────────────────────────

async function requestDesktopNotificationPermission(): Promise<boolean> {
  if (typeof Notification === "undefined") return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  const result = await Notification.requestPermission();
  return result === "granted";
}

function sendDesktopNotification(title: string, body: string) {
  if (typeof Notification !== "undefined" && Notification.permission === "granted") {
    try {
      new Notification(title, { body, icon: "/favicon.ico" });
    } catch {
      // ignore
    }
  }
}

// ─── Countdown Clock ─────────────────────────────────────────────────────────

function CountdownClock({ targetMs }: { targetMs: number }) {
  const [remaining, setRemaining] = useState(targetMs);

  useEffect(() => {
    const start = Date.now();
    const tick = () => {
      const elapsed = Date.now() - start;
      setRemaining(Math.max(0, targetMs - elapsed));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [targetMs]);

  const secs = Math.ceil(remaining / 1000);
  const pct = Math.round((remaining / targetMs) * 100);

  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <Clock className="h-3.5 w-3.5" />
      <span>Next refresh in {secs}s</span>
      {/* mini progress ring */}
      <svg width="24" height="24" className="-translate-y-0.5">
        <circle
          cx="12" cy="12" r="9"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="text-muted/20"
        />
        <circle
          cx="12" cy="12" r="9"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeDasharray={`${2 * Math.PI * 9}`}
          strokeDashoffset={`${2 * Math.PI * 9 * (1 - pct / 100)}`}
          strokeLinecap="round"
          className="text-primary transition-all duration-1000"
          transform="rotate(-90 12 12)"
        />
      </svg>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export default function IntradayMonitor() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<IntradayData | null>(null);
  const [soundEnabled, setSoundEnabled] = useState(false);
  const [desktopNotifs, setDesktopNotifs] = useState(false);
  const prevAlertCount = useRef(0);

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const [signalsResp, alertsResp, adjustmentsResp] = await Promise.all([
        fetch("/api/workflow/signals"),
        fetch("/api/workflow/alerts"),
        fetch("/api/workflow/adjustments"),
      ]);

      const [signals, alerts, adjustments] = await Promise.all([
        resolveSignals(signalsResp),
        resolveAlerts(alertsResp),
        resolveAdjustments(adjustmentsResp),
      ]);

      // Detect new bomb alerts for notifications
      if (alerts.length > prevAlertCount.current && alerts.length > 0) {
        if (soundEnabled) {
          const play = useSoundNotification(soundEnabled);
          play();
        }
        if (desktopNotifs) {
          sendDesktopNotification("🚨 Bomb Alert", `${alerts.length} active alert${alerts.length > 1 ? "s" : ""}`);
        }
      }
      prevAlertCount.current = alerts.length;

      setData({
        date: new Date().toISOString().split("T")[0],
        signals: signals as SignalItem[],
        alerts: alerts as AlertItem[],
        adjustments: adjustments as AdjustmentItem[],
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [soundEnabled, desktopNotifs]);

  // Initial load + 30 s interval
  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000);
    return () => clearInterval(interval);
  }, [loadData]);

  // ── Loading state ──
  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="盘中监控" subtitle="Intraday Monitor" />
        <Skeleton variant="rectangular" className="mb-4" />
        <SkeletonCard />
      </div>
    );
  }

  // ── Error state ──
  if (error) {
    return (
      <div className="space-y-6">
        <PageHeader title="盘中监控" subtitle="Intraday Monitor" />
        <GlassCard className="p-6">
          <div className="flex flex-col items-center gap-3 text-center">
            <ShieldAlert className="h-10 w-10 text-destructive" />
            <p className="text-lg font-medium text-destructive">加载失败</p>
            <p className="text-sm text-muted-foreground">{error}</p>
            <Button variant="primary" size="md" onClick={loadData}>
              <RefreshCw className="mr-1.5 h-4 w-4" />
              重试
            </Button>
          </div>
        </GlassCard>
      </div>
    );
  }

  // ── Empty state ──
  if (!data) {
    return (
      <div className="space-y-6">
        <PageHeader title="盘中监控" subtitle="Intraday Monitor" />
        <GlassCard className="p-6">
          <p className="text-muted-foreground">暂无盘中数据</p>
        </GlassCard>
      </div>
    );
  }

  const hasAlerts = data.alerts.length > 0;
  const hasSignals = data.signals.length > 0;
  const hasAdjustments = data.adjustments.length > 0;

  return (
    <div className="space-y-6">
      {/* ─── Header ─────────────────────────────────────────────────── */}
      <PageHeader
        title="盘中监控"
        subtitle={`${data.date} · 实时更新`}
        actions={
          <div className="flex items-center gap-3">
            {/* Sound toggle */}
            <button
              onClick={() => setSoundEnabled((v) => !v)}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/20 transition-colors"
              aria-label={soundEnabled ? "关闭提示音" : "开启提示音"}
              title={soundEnabled ? "关闭提示音" : "开启提示音"}
            >
              {soundEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
            </button>

            {/* Desktop notification toggle */}
            <button
              onClick={async () => {
                const granted = await requestDesktopNotificationPermission();
                setDesktopNotifs(granted);
              }}
              className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/20 transition-colors"
              aria-label="桌面通知"
              title={desktopNotifs ? "桌面通知已开启" : "点击请求桌面通知权限"}
            >
              <Bell className="h-4 w-4" />
            </button>

            {/* Countdown + manual refresh */}
            <CountdownClock targetMs={30_000} />
            <Button variant="ghost" size="sm" onClick={loadData}>
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              刷新
            </Button>
          </div>
        }
      />

      {/* ─── Layer 1 — Bomb Alerts (Critical) ───────────────────────── */}
      {hasAlerts && (
        <GlassCard
          className={`overflow-visible border-l-4 border-l-red-500 ${hasAlerts ? "ring-1 ring-red-500/20" : ""}`}
        >
          <div className="mb-4 flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-red-400" />
            <h3 className="text-lg font-bold text-red-400">炸板预警</h3>
            <Badge variant="danger" className="ml-auto">
              {data.alerts.length}
            </Badge>
          </div>

          <div className="space-y-3">
            {data.alerts.map((alert, idx) => {
              const levelColor = ALERT_LEVEL_COLORS[alert.alert_level?.toLowerCase() ?? alert.level?.toLowerCase() ?? ""] ?? "warning";
              return (
                <div
                  key={idx}
                  className="group relative overflow-hidden rounded-xl border border-red-500/20 bg-red-500/[0.06] p-4 transition-all hover:border-red-500/40 hover:bg-red-500/[0.10]"
                >
                  {/* Pulse bar on first/newest alert */}
                  {idx === 0 && (
                    <span className="absolute left-0 top-0 bottom-0 w-1 bg-red-500 animate-pulse" />
                  )}

                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-bold text-white/90">
                      {alert.code}
                    </span>
                    {alert.name && (
                      <span className="text-sm text-white/60">{alert.name}</span>
                    )}
                    <Badge variant={levelColor}>
                      {alert.alert_level ?? alert.level ?? "预警"}
                    </Badge>
                    {alert.time && (
                      <span className="ml-auto text-xs text-muted-foreground">
                        {timeAgo(alert.time)}
                      </span>
                    )}
                  </div>

                  {alert.condition ?? alert.message ? (
                    <p className="mt-2 pl-3 text-sm text-red-200/80">
                      {alert.condition ?? alert.message}
                    </p>
                  ) : null}
                </div>
              );
            })}
          </div>
        </GlassCard>
      )}

      {/* ─── Layer 2 — Trading Signals ──────────────────────────────── */}
      {hasSignals && (
        <GlassCard glow>
          <div className="mb-4 flex items-center gap-2">
            <Activity className="h-5 w-5 text-primary" />
            <h3 className="text-lg font-bold text-primary">交易信号</h3>
            <Badge variant="primary" className="ml-auto">
              {data.signals.length}
            </Badge>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {data.signals.map((signal, idx) => {
              const typeKey = signal.signal_type?.toLowerCase() ?? signal.type?.toLowerCase() ?? "";
              const color = SIGNAL_TYPE_COLORS[typeKey] ?? "info";
              return (
                <div
                  key={idx}
                  className="rounded-xl border border-border/40 bg-card/40 p-4 transition-colors hover:border-border/70"
                >
                  <div className="mb-2 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-bold text-white/90">
                        {signal.code}
                      </span>
                      {signal.name && (
                        <span className="text-sm text-muted-foreground">{signal.name}</span>
                      )}
                    </div>
                    <Badge variant={color}>
                      {typeKey || "signal"}
                    </Badge>
                  </div>
                  {(signal.reasoning ?? signal.description) && (
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {signal.reasoning ?? signal.description}
                    </p>
                  )}
                  {signal.time && (
                    <p className="mt-2 text-xs text-muted-foreground/60">
                      {timeAgo(signal.time)}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </GlassCard>
      )}

      {/* ─── Layer 3 — Position Adjustments ─────────────────────────── */}
      {hasAdjustments && (
        <GlassCard glow>
          <div className="mb-4 flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-success" />
            <h3 className="text-lg font-bold text-success">仓位调整</h3>
            <Badge variant="success" className="ml-auto">
              {data.adjustments.length}
            </Badge>
          </div>

          <div className="divide-y divide-border/30">
            {data.adjustments.map((adj, idx) => {
              const norm = normalizeAction(adj.action);
              const badgeVar = ACTION_BADGE_MAP[norm] ?? "default";
              const Icon = ACTION_ICON_MAP[norm] ?? Minus;
              return (
                <div
                  key={idx}
                  className="flex items-center gap-3 py-3 first:pt-0 last:pb-0"
                >
                  <Badge variant={badgeVar}>
                    <Icon className="mr-1 h-3 w-3" />
                    {adj.action}
                  </Badge>
                  <div className="min-w-0">
                    <span className="font-mono text-sm font-semibold text-white/90">
                      {adj.code}
                    </span>
                    {adj.name && (
                      <span className="ml-1.5 text-sm text-muted-foreground">
                        {adj.name}
                      </span>
                    )}
                  </div>
                  {adj.reason && (
                    <span className="ml-auto shrink-0 max-w-[40%] truncate text-xs text-muted-foreground">
                      {adj.reason}
                    </span>
                  )}
                  {adj.time && (
                    <span className="shrink-0 text-xs text-muted-foreground/60">
                      {timeAgo(adj.time)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </GlassCard>
      )}

      {/* ── No data at all ── */}
      {!hasAlerts && !hasSignals && !hasAdjustments && (
        <GlassCard className="p-6">
          <div className="flex flex-col items-center gap-2 py-8 text-muted-foreground">
            <Activity className="h-10 w-10 opacity-40" />
            <p>暂无盘中数据</p>
          </div>
        </GlassCard>
      )}
    </div>
  );
}

// ─── Shared skeleton used during initial load ────────────────────────────────

function SkeletonCard() {
  return (
    <div className="space-y-5">
      <Skeleton variant="rounded" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Skeleton variant="rounded" />
        <Skeleton variant="rounded" />
      </div>
    </div>
  );
}
