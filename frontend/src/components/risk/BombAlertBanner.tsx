// S055：炸板预警横幅 + 个股封单额 sparkline
// 在打板策略页顶部挂横幅（红/黄分级 + 时间 + 依据），个股抽屉挂封单额 sparkline。
import { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { api, type BombAlertItem } from "@/lib/api";
import { cn } from "@/lib/utils";

const LEVEL_STYLE: Record<string, string> = {
  red: "border-red-500/40 bg-red-500/10 text-red-600",
  yellow: "border-amber-500/40 bg-amber-500/10 text-amber-600",
};

export function BombAlertBanner() {
  const [alerts, setAlerts] = useState<BombAlertItem[]>([]);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let mounted = true;
    const load = () => {
      api.bombAlerts().then((res) => {
        if (mounted && !dismissed) setAlerts(res.alerts);
      }).catch(() => {});
    };
    load();
    const timer = setInterval(load, 60_000);  // 每分钟刷新（与采集节奏一致）
    return () => { mounted = false; clearInterval(timer); };
  }, [dismissed]);

  if (alerts.length === 0 || dismissed) return null;

  const hasRed = alerts.some((a) => a.alert_level === "red");
  const topAlert = hasRed ? alerts.find((a) => a.alert_level === "red")! : alerts[0];

  return (
    <div className={cn(
      "mb-4 flex items-start gap-2 rounded-lg border p-3 text-sm",
      LEVEL_STYLE[topAlert.alert_level] ?? LEVEL_STYLE.yellow,
    )}>
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="flex-1">
        <div className="font-medium">
          {hasRed ? "炸板红色预警" : "炸板黄色预警"}
          <span className="ml-2 text-xs opacity-70">（{alerts.length} 条）</span>
        </div>
        <div className="mt-1 text-xs opacity-80">
          {topAlert.ts.slice(11, 16)} · {topAlert.name}({topAlert.code}) · {topAlert.condition}
        </div>
        {alerts.length > 1 && (
          <div className="mt-1 text-xs opacity-60">
            其余 {alerts.length - 1} 条：{alerts.slice(1, 4).map((a) => `${a.name}(${a.rule_id})`).join("、")}
            {alerts.length > 4 ? "…" : ""}
          </div>
        )}
        <div className="mt-1 text-[11px] opacity-50">
          炸板预警属风险标注，历史统计特征，市场有风险，不构成交易指令
        </div>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="shrink-0 opacity-50 hover:opacity-100"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// 简易封单额 sparkline（纯 SVG，无第三方依赖）
export function SealAmountSparkline({ code, date }: { code: string; date?: string }) {
  const [points, setPoints] = useState<number[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api.sealSnapshots(code, date).then((res) => {
      if (mounted) {
        const seals = res.snapshots
          .map((s) => s.seal_amount ?? 0)
          .filter((v) => v > 0);
        setPoints(seals);
      }
    }).catch(() => {}).finally(() => mounted && setLoading(false));
    return () => { mounted = false; };
  }, [code, date]);

  if (loading) return <div className="text-xs text-muted-foreground">加载封单时序…</div>;
  if (points.length < 2) return <div className="text-xs text-muted-foreground/60">封单时序不足</div>;

  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const w = 100, h = 24;
  const path = points.map((v, i) => {
    const x = (i / (points.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${i === 0 ? "M" : "L"}${x},${y}`;
  }).join(" ");

  return (
    <div className="flex items-center gap-2">
      <svg viewBox={`0 0 ${w} ${h}`} className="h-6 w-24">
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" className="text-primary" />
      </svg>
      <span className="text-[11px] text-muted-foreground">
        {(max / 1e4).toFixed(0)}万 → {(points[points.length - 1] / 1e4).toFixed(0)}万
      </span>
    </div>
  );
}
