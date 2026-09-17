// S215 通用技术指标评分卡——调 /api/stock/tech-score?code= 展示 6 维 100 分 + 信号。
// 不碰打板 scoring（§44 sizing），独立通用技术评分（参考 stock-analysis skill）。
import { useEffect, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

interface DimData {
  score: number;
  reason?: string;
  ma5?: number;
  ma10?: number;
  ma20?: number;
  ma60?: number;
  dif?: number;
  dea?: number;
  hist?: number;
  rsi6?: number;
  rsi12?: number;
  rsi24?: number;
  vol_ratio?: number;
  last_vol?: number;
  avg5?: number;
  bias_pct?: number;
  last_close?: number;
  support?: number;
  resistance?: number;
  dist_support_pct?: number;
  dist_resist_pct?: number;
}

interface TechScoreResponse {
  available: boolean;
  code?: string;
  total_score?: number;
  signal?: string;
  n_bars?: number;
  reason?: string;
  dimensions?: {
    ma: DimData;
    macd: DimData;
    rsi: DimData;
    volume: DimData;
    bias: DimData;
    support: DimData;
  };
}

const SIGNAL_STYLE: Record<string, string> = {
  强烈买入: "bg-emerald-500/10 text-emerald-600",
  买入: "bg-emerald-500/10 text-emerald-600",
  持有: "bg-gray-400/10 text-muted-foreground",
  观望: "bg-amber-500/10 text-amber-600",
  强烈卖出: "bg-red-500/10 text-red-600",
};

const DIM_LABEL: Record<string, string> = {
  ma: "均线 MA",
  macd: "MACD",
  rsi: "RSI",
  volume: "量能",
  bias: "乖离率",
  support: "支撑压力",
};

function dimDetail(k: string, d: DimData): string {
  switch (k) {
    case "ma":
      return d.ma5 != null ? `MA5=${d.ma5} MA20=${d.ma20}` : d.reason ?? "";
    case "macd":
      return d.dif != null ? `DIF=${d.dif} DEA=${d.dea}` : d.reason ?? "";
    case "rsi":
      return d.rsi6 != null ? `RSI6=${d.rsi6} RSI12=${d.rsi12}` : d.reason ?? "";
    case "volume":
      return d.vol_ratio != null ? `量比=${d.vol_ratio}` : d.reason ?? "";
    case "bias":
      return d.bias_pct != null ? `BIAS=${d.bias_pct}%` : d.reason ?? "";
    case "support":
      return d.support != null ? `支撑=${d.support} 压力=${d.resistance}` : d.reason ?? "";
    default:
      return "";
  }
}

interface Props {
  code: string;
}

export function TechScoreCard({ code }: Props) {
  const [data, setData] = useState<TechScoreResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api
      .techScore(code)
      .then((r) => {
        if (!cancelled) setData(r as TechScoreResponse);
      })
      .catch((e: unknown) => {
        if (!cancelled) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (loading) {
    return <div className="p-4 text-sm text-muted-foreground">加载技术评分…</div>;
  }
  if (err) {
    return <div className="p-4 text-sm text-red-600">加载失败: {err}</div>;
  }
  if (!data) return null;
  if (!data.available) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        技术评分不可用：{data.reason ?? "bars 不足（< 60）"}
      </div>
    );
  }

  const signal = data.signal ?? "观望";
  const dims: Record<string, DimData> = data.dimensions ?? {};
  const dimKeys = ["ma", "macd", "rsi", "volume", "bias", "support"] as const;

  return (
    <GlassCard className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">通用技术评分（S215）</h3>
        <span
          className={cn(
            "rounded px-2 py-0.5 text-xs font-medium",
            SIGNAL_STYLE[signal] ?? "bg-gray-400/10 text-muted-foreground",
          )}
        >
          {signal}
        </span>
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-3xl font-bold">{data.total_score}</span>
        <span className="text-xs text-muted-foreground">/ 100</span>
        <span className="ml-auto text-xs text-muted-foreground">{data.n_bars} bars</span>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {dimKeys.map((k) => {
          const d = dims[k];
          if (!d) return null;
          return (
            <div key={k} className="rounded border border-border/50 p-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{DIM_LABEL[k]}</span>
                <span className="text-sm font-semibold">{d.score}</span>
              </div>
              <div className="mt-1 text-[10px] text-muted-foreground">{dimDetail(k, d)}</div>
            </div>
          );
        })}
      </div>
      <p className="text-[10px] text-muted-foreground">
        通用技术面评分（MA/MACD/RSI/量能/乖离/支撑），不碰打板 §44 sizing。参考 stock-analysis。
      </p>
    </GlassCard>
  );
}

export default TechScoreCard;
