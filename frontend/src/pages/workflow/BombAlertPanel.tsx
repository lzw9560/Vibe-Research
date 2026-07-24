import { useState, useEffect, useCallback, useMemo } from "react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { Badge } from "@/components/ui/Badge";
import {
  BadgeAlert,
  Search,
  Filter,
  RefreshCw,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
  History,
} from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────

interface BombAlert {
  timestamp: string;
  code: string;
  name: string;
  alert_level: "red" | "yellow";
  condition: string;
  current_seal_amount: number;
  seal_amount_change_5min: number;
  recommendation: string;
}

interface HandledAlert extends BombAlert {
  handledAt: string; // ISO timestamp when user clicked "Handle"
}

type AlertFilter = "all" | "red" | "yellow";

const ALERT_LEVEL_LABELS: Record<string, { label: string; variant: "danger" | "warning" }> = {
  red: { label: "红色预警", variant: "danger" },
  yellow: { label: "黄色预警", variant: "warning" },
};

const ALERT_LEVEL_ORDER: Record<string, number> = { red: 0, yellow: 1 };

const STORAGE_KEY_HANDLED = "bomb-alerts-handled";

// ─── Helpers ─────────────────────────────────────────────────────────

function loadHandled(): HandledAlert[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_HANDLED);
    if (!raw) return [];
    return JSON.parse(raw) as HandledAlert[];
  } catch {
    return [];
  }
}

function saveHandled(handled: HandledAlert[]) {
  localStorage.setItem(STORAGE_KEY_HANDLED, JSON.stringify(handled));
}

function formatSealAmount(yuan: number): string {
  const wan = yuan / 10000;
  if (wan >= 10000) return `${(wan / 10000).toFixed(2)}亿`;
  return `${wan.toFixed(0)}万`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// ─── Component ───────────────────────────────────────────────────────

export default function BombAlertPanel() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<BombAlert[]>([]);
  const [handled, setHandled] = useState<HandledAlert[]>(loadHandled);

  // UI state
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<AlertFilter>("all");
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [archivedOpen, setArchivedOpen] = useState(false);

  // ── Data loading ──────────────────────────────────────────────────

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const resp = await fetch("/api/workflow/alerts");
      const data = await resp.json();
      const payload = (data as { data?: BombAlert[] })?.data ?? data;
      setAlerts(Array.isArray(payload) ? (payload as BombAlert[]) : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    if (!autoRefresh) return;
    const id = setInterval(loadData, 10000);
    return () => clearInterval(id);
  }, [autoRefresh, loadData]);

  // ── Derived lists ─────────────────────────────────────────────────

  const handledCodes = useMemo(
    () => new Set(handled.map((h) => h.code)),
    [handled],
  );

  const activeAlerts = useMemo(
    () => alerts.filter((a) => !handledCodes.has(a.code)),
    [alerts, handledCodes],
  );

  // Sort: severity desc (red first), then newest first
  const sortedActive = useMemo(() => {
    const sorted = [...activeAlerts].sort((a, b) => {
      const levelDiff =
        (ALERT_LEVEL_ORDER[a.alert_level] ?? 2) -
        (ALERT_LEVEL_ORDER[b.alert_level] ?? 2);
      if (levelDiff !== 0) return levelDiff;
      return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
    });
    return sorted;
  }, [activeAlerts]);

  const filteredActive = useMemo(() => {
    let list = sortedActive;
    if (filter !== "all") {
      list = list.filter((a) => a.alert_level === filter);
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      list = list.filter(
        (a) =>
          a.code.toLowerCase().includes(q) ||
          a.name.toLowerCase().includes(q),
      );
    }
    return list;
  }, [sortedActive, filter, search]);

  // Archived = handled entries whose code still exists in current alerts
  const archivedAlerts = useMemo(
    () =>
      handled
        .filter((h) => alerts.some((a) => a.code === h.code))
        .sort(
          (a, b) =>
            new Date(b.handledAt).getTime() - new Date(a.handledAt).getTime(),
        ),
    [handled, alerts],
  );

  // ── Handlers ──────────────────────────────────────────────────────

  const handleMarkHandled = useCallback(
    (alert: BombAlert) => {
      const entry: HandledAlert = { ...alert, handledAt: new Date().toISOString() };
      setHandled((prev) => {
        const filtered = prev.filter((h) => h.code !== alert.code);
        saveHandled([...filtered, entry]);
        return filtered;
      });
    },
    [],
  );

  const handleUnhandle = useCallback(
    (code: string) => {
      setHandled((prev) => {
        const entry = prev.find((h) => h.code === code);
        if (!entry) return prev;
        const updated = prev.filter((h) => h.code !== code);
        saveHandled(updated);
        return updated;
      });
    },
    [],
  );

  // ── Render helpers ────────────────────────────────────────────────

  const renderBadge = (level: string) => {
    const info = ALERT_LEVEL_LABELS[level] ?? { label: level, variant: "default" };
    return <Badge variant={info.variant}>{info.label}</Badge>;
  };

  const renderChange = (change: number) => {
    const wan = change / 10000;
    const sign = wan <= 0 ? "" : "+";
    return (
      <span className={wan <= 0 ? "text-red-400" : "text-emerald-400"}>
        {sign}{wan.toFixed(0)}万
      </span>
    );
  };

  // ── Loading ───────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="炸板预警" subtitle="Bomb Alert Panel" />
        <Skeleton variant="rectangular" />
        <Skeleton variant="rectangular" />
        <Skeleton variant="rectangular" />
      </div>
    );
  }

  // ── Error ─────────────────────────────────────────────────────────

  if (error) {
    return (
      <div className="space-y-6">
        <PageHeader title="炸板预警" subtitle="Bomb Alert Panel" />
        <GlassCard className="p-6">
          <div className="flex flex-col items-center gap-3 text-center">
            <XCircle className="h-10 w-10 text-destructive" />
            <p className="text-lg font-medium text-destructive">加载失败</p>
            <p className="text-sm text-white/60">{error}</p>
            <Button variant="primary" size="sm" onClick={loadData}>
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              重试
            </Button>
          </div>
        </GlassCard>
      </div>
    );
  }

  // ── Main ──────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <PageHeader title="炸板预警" subtitle="Bomb Alert Panel" actions={
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAutoRefresh((v) => !v)}
            className={autoRefresh ? "text-primary" : ""}
          >
            <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${autoRefresh ? "animate-spin" : ""}`} style={{ animationDuration: autoRefresh ? "3s" : undefined }} />
            自动刷新
          </Button>
          <span
            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
              autoRefresh
                ? "bg-emerald-500/15 text-emerald-400"
                : "bg-muted/20 text-muted-foreground"
            }`}
          >
            {autoRefresh ? "ON" : "OFF"}
          </span>
        </div>
      } />

      {/* Toolbar */}
      <GlassCard className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px]">
            <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              placeholder="搜索股票代码或名称…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full rounded-lg border border-border/50 bg-black/20 py-2 pl-9 pr-3 text-sm text-foreground outline-none transition-colors placeholder:text-muted-foreground focus:border-primary/50 focus:ring-2 focus:ring-primary/20"
            />
          </div>

          {/* Filter */}
          <div className="flex items-center gap-1.5">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <select
              value={filter}
              onChange={(e) => setFilter(e.target.value as AlertFilter)}
              className="rounded-lg border border-border/50 bg-black/20 py-2 pl-2.5 pr-8 text-sm text-foreground outline-none transition-colors focus:border-primary/50 focus:ring-2 focus:ring-primary/20 appearance-none"
              style={{ paddingRight: "2rem" }}
            >
              <option value="all">全部 ({alerts.length})</option>
              <option value="red">红色 ({alerts.filter((a) => a.alert_level === "red").length})</option>
              <option value="yellow">黄色 ({alerts.filter((a) => a.alert_level === "yellow").length})</option>
            </select>
          </div>

          {/* Active count badge */}
          <Badge variant="primary" className="shrink-0">
            <BadgeAlert className="mr-1 h-3 w-3" />
            活跃 {filteredActive.length}
          </Badge>
        </div>
      </GlassCard>

      {/* Active Alerts */}
      {filteredActive.length === 0 ? (
        <GlassCard glow className="p-10 text-center">
          <CheckCircle className="mx-auto mb-3 h-10 w-10 text-emerald-400" />
          <p className="text-white/70">
            {search || filter !== "all"
              ? "没有匹配的预警"
              : "当前无炸板预警，一切正常"}
          </p>
        </GlassCard>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredActive.map((alert) => {
            const key = `${alert.code}-${alert.timestamp}`;
            return (
              <GlassCard
                key={key}
                glow
                className={`flex flex-col p-5 transition-all hover:-translate-y-0.5 ${
                  alert.alert_level === "red"
                    ? "border-l-4 border-l-red-500/70"
                    : "border-l-4 border-l-yellow-400/70"
                }`}
              >
                {/* Top row: code+name + badge */}
                <div className="mb-3 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span className="text-base font-bold tracking-tight text-foreground">
                        {alert.code}
                      </span>
                      <span className="text-sm text-muted-foreground truncate">
                        {alert.name}
                      </span>
                    </div>
                    <span className="mt-0.5 block text-xs tabular-nums text-white/40">
                      {formatTime(alert.timestamp)}
                    </span>
                  </div>
                  {renderBadge(alert.alert_level)}
                </div>

                {/* Condition */}
                <p className="mb-3 text-xs leading-relaxed text-white/50 line-clamp-2">
                  {alert.condition}
                </p>

                {/* Seal amount grid */}
                <div className="mb-3 grid grid-cols-2 gap-3 rounded-lg bg-black/20 p-2.5">
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                      当前封单额
                    </p>
                    <p className="text-sm font-semibold tabular-nums text-foreground">
                      {formatSealAmount(alert.current_seal_amount)}
                    </p>
                  </div>
                  <div>
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                      5分钟变化
                    </p>
                    <p className="text-sm font-semibold tabular-nums">
                      {renderChange(alert.seal_amount_change_5min)}
                    </p>
                  </div>
                </div>

                {/* Recommendation */}
                <p className="mb-3 flex-1 text-xs leading-relaxed text-white/60">
                  <span className="text-muted-foreground">建议：</span>
                  {alert.recommendation}
                </p>

                {/* Handle button */}
                <Button
                  variant="primary"
                  size="sm"
                  className="w-full"
                  onClick={() => handleMarkHandled(alert)}
                >
                  <CheckCircle className="mr-1.5 h-3.5 w-3.5" />
                  标记已处理
                </Button>
              </GlassCard>
            );
          })}
        </div>
      )}

      {/* Archived / Handled Section */}
      {archivedAlerts.length > 0 && (
        <GlassCard>
          <button
            onClick={() => setArchivedOpen((v) => !v)}
            className="flex w-full items-center justify-between gap-2 text-left"
          >
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <History className="h-4 w-4" />
              <span>已处理 ({archivedAlerts.length})</span>
            </div>
            {archivedOpen ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </button>

          {archivedOpen && (
            <div className="mt-4 space-y-3">
              {archivedAlerts.map((a) => (
                <div
                  key={`${a.code}-${a.handledAt}`}
                  className="flex items-center justify-between rounded-lg bg-black/10 px-4 py-3"
                >
                  <div className="flex items-center gap-3">
                    <CheckCircle className="h-4 w-4 text-emerald-400 shrink-0" />
                    <div>
                      <span className="text-sm font-medium text-foreground">
                        {a.code} {a.name}
                      </span>
                      <span className="ml-2 text-xs text-white/40">
                        处理于 {new Date(a.handledAt).toLocaleString("zh-CN")}
                      </span>
                    </div>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => handleUnhandle(a.code)}
                  >
                    <XCircle className="mr-1 h-3.5 w-3.5" />
                    撤销
                  </Button>
                </div>
              ))}
            </div>
          )}
        </GlassCard>
      )}
    </div>
  );
}
