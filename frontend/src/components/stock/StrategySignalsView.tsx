// 战法信号视图——调 /api/strategy/signals/{code} 渲染匹配的战法（首板涨停/反包/接力 等）。
// 共享于 StockCockpit 主区信号区（full）+ RightPanel 信号 panel（compact）。
// date 由页面级父组件持有 + 传入（本视图不管理 date state，避免多处日期选择器）。
// variant=full：宽卡片大字距；variant=compact：窄卡片紧凑（右侧 panel 用）。
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface StrategySignal {
  strategy_code: string;
  strategy_name: string;
  score: number;
  entry_condition?: string;
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  max_hold_days?: number;
  reasoning?: string[];
  risk_notes?: string[];
}

interface Props {
  code: string;
  /** 页面级日期（YYYY-MM-DD），空=最新交易日。由父组件持有传入。 */
  date: string;
  variant?: "full" | "compact";
}

export function StrategySignalsView({ code, date, variant = "full" }: Props) {
  const [signals, setSignals] = useState<StrategySignal[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    api
      .strategySignals(code, date || undefined)
      .then((r) => {
        if (!cancelled) setSignals(Array.isArray(r) ? (r as StrategySignal[]) : []);
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
  }, [code, date]);

  const compact = variant === "compact";
  const cardPad = compact ? "p-2.5" : "p-3.5";
  const cardGap = compact ? "space-y-2" : "space-y-3";
  const titleCls = compact ? "text-sm" : "text-base";
  const bodyCls = compact ? "text-xs" : "text-xs";

  return (
    <div className="space-y-3">
      {loading && (
        <p className="text-xs text-muted-foreground">加载战法匹配…</p>
      )}
      {err && <p className="text-xs text-danger">加载失败：{err}</p>}

      {!loading && !err && signals.length === 0 && (
        <p className="text-xs text-muted-foreground">
          该股当日无战法命中（非涨停 / 无板块共振 / 数据缺失）
        </p>
      )}

      <div className={cardGap}>
        {signals.map((s) => (
          <div
            key={s.strategy_code}
            className={`${cardPad} space-y-2 rounded-lg border border-border/60 bg-muted/10`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className={`${titleCls} font-semibold text-primary`}>
                {s.strategy_name}
              </span>
              <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                基因分 {s.score}
              </span>
            </div>

            {s.entry_condition && (
              <p className={`${bodyCls} leading-relaxed text-muted-foreground`}>
                {s.entry_condition}
              </p>
            )}

            {s.reasoning && s.reasoning.length > 0 && (
              <ul className="space-y-1">
                {s.reasoning.map((r, i) => (
                  <li
                    key={i}
                    className={`${bodyCls} flex gap-1.5 leading-relaxed text-foreground`}
                  >
                    <span className="text-primary">✓</span>
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
            )}

            {s.risk_notes && s.risk_notes.length > 0 && (
              <ul className="space-y-0.5 border-t border-border/30 pt-1.5">
                {s.risk_notes.map((r, i) => (
                  <li
                    key={i}
                    className="text-xs leading-relaxed text-muted-foreground"
                  >
                    ⚠ {r}
                  </li>
                ))}
              </ul>
            )}

            <div className="flex flex-wrap gap-x-3 gap-y-1 border-t border-border/30 pt-1.5 text-xs text-muted-foreground">
              {s.entry_price != null && (
                <span>
                  入场 <span className="font-mono text-foreground">{s.entry_price}</span>
                </span>
              )}
              {s.stop_loss != null && (
                <span>
                  止损 <span className="font-mono text-danger">{s.stop_loss}</span>
                </span>
              )}
              {s.take_profit != null && (
                <span>
                  止盈 <span className="font-mono text-primary">{s.take_profit}</span>
                </span>
              )}
              {s.max_hold_days != null && <span>持 {s.max_hold_days}日</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

