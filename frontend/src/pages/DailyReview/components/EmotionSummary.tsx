/** 市场情绪 + 短线情绪 + 成交额 TOP20 */
import { GlassCard } from "@/components/ui/GlassCard";
import { pctColor, cn } from "@/lib/utils";
import { Flame, BarChart3 } from "lucide-react";
import type { ShortTermEmotion, TurnoverTop } from "@/lib/api";

interface Props {
  sentiment: ShortTermEmotion | null;
  emoDone: boolean;
  turnover: TurnoverTop | null;
  toDone: boolean;
}
const fmt = (v: number) => v.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const yi = (v: number | null) => (v == null ? "—" : `${fmt(v / 1e8)} 亿`);
const pending = (done: boolean) => (
  <p className="py-4 text-center text-sm text-muted-foreground/60">
    {done ? "暂无数据：可能是非交易时段或数据源暂时不可用" : "加载中…"}
  </p>
);

export function EmotionSummary({ sentiment, emoDone, turnover, toDone }: Props) {
  return (
    <>
      {/* 短线情绪 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><Flame className="h-4 w-4" /> 短线情绪</h3>
        <span className="text-[11px] text-muted-foreground/50">连板股 · 打板情绪 · 客观公开榜单</span>
      </div>
      <GlassCard className="mb-6">
        {!sentiment?.emotion ? pending(emoDone) : (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {[
                { k: "涨停", v: `${sentiment.emotion.limit_up_count}`, cls: "text-danger" },
                { k: "跌停", v: `${sentiment.emotion.limit_down_count}`, cls: "text-success" },
                { k: "最高连板", v: `${sentiment.emotion.max_boards} 板`, cls: "text-primary" },
                { k: "连板（2板+）", v: `${sentiment.lianban_count} 家`, cls: "text-primary" },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/25 p-3 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-xl font-bold", c.cls)}>{c.v}</p>
                </div>
              ))}
            </div>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {[
                { k: "封板率", v: sentiment.emotion.seal_rate, hint: "封住 / 尝试涨停", strong: true },
                { k: "炸板率", v: sentiment.emotion.broken_rate, hint: "炸板 / 尝试涨停", strong: false },
                { k: "晋级率", v: sentiment.emotion.advance_rate, hint: "昨涨停今又停", strong: true },
              ].map((c) => (
                <div key={c.k} className="rounded-lg bg-muted/20 p-2.5 text-center">
                  <p className="text-[11px] text-muted-foreground">{c.k}</p>
                  <p className={cn("mt-0.5 font-mono text-sm font-bold", c.strong ? "text-danger" : "text-success")}>
                    {c.v == null ? "—" : `${(c.v * 100).toFixed(1)}%`}
                  </p>
                  <p className="mt-0.5 text-[10px] text-muted-foreground/50">{c.hint}</p>
                </div>
              ))}
            </div>
            {sentiment.lianban_stocks.length > 0 && (
              <div className="mt-3">
                <p className="mb-1.5 text-[11px] text-muted-foreground">连板股（2 板以上）· 客观公开榜单</p>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead><tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      {["名称", "连板", "现价", "涨停%", "成交额"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
                    </tr></thead>
                    <tbody>
                      {sentiment.lianban_stocks.map((s) => (
                        <tr key={s.code} className="border-b border-border/30">
                          <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono font-bold text-primary">{s.boards} 板</td>
                          <td className="px-2 py-2 font-mono">{s.price}</td>
                          <td className="px-2 py-2 font-mono text-danger">+{s.pct}%</td>
                          <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </GlassCard>

      {/* 成交额 TOP20 */}
      <div className="mb-3 flex items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-sm font-semibold text-muted-foreground"><BarChart3 className="h-4 w-4" /> 全市场成交额 TOP20</h3>
        <span className="text-[11px] text-muted-foreground/50">客观公开榜单</span>
        {turnover?.updated && <span className="ml-auto text-[11px] text-muted-foreground/50">{turnover.updated}</span>}
      </div>
      <GlassCard className="mb-6">
        {!turnover || turnover.stocks.length === 0 ? pending(toDone) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                {["#", "名称", "涨跌%", "成交额", "行业"].map((h) => <th key={h} className="whitespace-nowrap px-2 py-2 font-medium">{h}</th>)}
              </tr></thead>
              <tbody>
                {turnover.stocks.map((s, i) => (
                  <tr key={s.code} className="border-b border-border/30">
                    <td className="px-2 py-2 font-mono text-xs text-muted-foreground/50">{i + 1}</td>
                    <td className="px-2 py-2"><span className="font-medium">{s.name}</span> <span className="text-xs text-muted-foreground/50">{s.code}</span></td>
                    <td className={cn("px-2 py-2 font-mono", pctColor(s.pct))}>{s.pct != null ? `${s.pct > 0 ? "+" : ""}${s.pct}%` : "—"}</td>
                    <td className="whitespace-nowrap px-2 py-2 font-mono">{yi(s.amount)}</td>
                    <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>
    </>
  );
}
