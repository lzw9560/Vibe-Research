// 资金流向面板——调 /api/fund-flow?code={code} 渲染主力净流入 + 四档细分 + 近期趋势。
// 用于 RightPanel「资金」tab。数据单位元（东财 push2his 口径），展示时折算亿/万。
// 颜色：橙 text-primary=净流入，红 text-danger=净流出，灰 text-muted-foreground=持平/缺。
// 诚实空态：东财 push2his 对部分 IP 间歇风控可能返空，如实呈现不臆造。
import { useEffect, useState } from "react";
import { api, type FundFlowRow } from "@/lib/api";
import { HonestEmptyState } from "@/components/intraday/HonestEmptyState";

interface Props {
  code: string;
}

// 资金额格式化：元 → 亿/万/元，带正负号。
function formatFlow(v: number): string {
  const abs = Math.abs(v);
  const body =
    abs >= 1e8 ? `${(abs / 1e8).toFixed(2)}亿`
    : abs >= 1e4 ? `${(abs / 1e4).toFixed(2)}万`
    : `${abs.toFixed(0)}`;
  return v > 0 ? `+${body}` : v < 0 ? `-${body}` : body;
}

// 净流入色：橙=流入，红=流出，灰=持平/缺。
function flowColor(v: number): string {
  return v > 0 ? "text-primary" : v < 0 ? "text-danger" : "text-muted-foreground";
}

// 四档细分（特大→大→中→小），主力 = 超大 + 大单。
const BREAKDOWN: { key: "super_net" | "large_net" | "mid_net" | "small_net"; label: string }[] = [
  { key: "super_net", label: "特大单" },
  { key: "large_net", label: "大单" },
  { key: "mid_net", label: "中单" },
  { key: "small_net", label: "小单" },
];

const TREND_DAYS = 12;

export function FundFlowPanel({ code }: Props) {
  const [rows, setRows] = useState<FundFlowRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api
      .fundFlow(code)
      .then((r) => {
        if (!cancelled) setRows(Array.isArray(r) ? r : []);
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
    return <p className="text-xs text-muted-foreground">加载资金流向…</p>;
  }

  if (err) {
    return <p className="text-xs text-danger">加载失败：{err}</p>;
  }

  if (rows.length === 0) {
    return (
      <HonestEmptyState
        message="暂无资金流数据"
        hint={
          <span>
            东财 push2his 对部分 IP 间歇风控可能返空·
            <code className="font-mono">/api/fund-flow?code={code}</code>
          </span>
        }
      />
    );
  }

  // 数据升序（旧→新），最新在末尾。
  const latest = rows[rows.length - 1];
  const trend = rows.slice(-TREND_DAYS);

  return (
    <div className="space-y-3">
      {/* 主力净流入（最新日） */}
      <div className="rounded-lg border border-border/60 bg-muted/10 p-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">主力净流入</span>
          <span className="text-xs text-muted-foreground">{latest.date}</span>
        </div>
        <p className={`mt-1 font-mono text-lg font-semibold ${flowColor(latest.main_net)}`}>
          {formatFlow(latest.main_net)}
        </p>
      </div>

      {/* 四档细分（最新日） */}
      <div className="grid grid-cols-2 gap-2">
        {BREAKDOWN.map(({ key, label }) => (
          <div
            key={key}
            className="rounded-lg border border-border/60 bg-muted/10 p-2.5"
          >
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className={`mt-0.5 font-mono text-sm font-medium ${flowColor(latest[key])}`}>
              {formatFlow(latest[key])}
            </p>
          </div>
        ))}
      </div>

      {/* 近期趋势 */}
      <div className="rounded-lg border border-border/60 bg-muted/10 p-2.5">
        <p className="mb-1.5 text-xs text-muted-foreground">
          近 {trend.length} 日主力净流入
        </p>
        <div className="space-y-1">
          {trend.map((r) => (
            <div
              key={r.date}
              className="flex items-center justify-between gap-2 text-xs"
            >
              <span className="font-mono text-muted-foreground">{r.date}</span>
              <span className={`font-mono font-medium ${flowColor(r.main_net)}`}>
                {formatFlow(r.main_net)}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default FundFlowPanel;
