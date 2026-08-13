/** 情绪详情页 - 下沉子页 */
import { useEmotion } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { AskAiButton } from "@/components/ui/AskAiButton";
import { cn } from "@/lib/utils";
import { Gauge } from "lucide-react";

const yi = (v: number | null) => (v == null ? "—" : `${(v / 1e8).toFixed(1)} 亿`);

export function EmotionDetail() {
  const { data: sentiment, isLoading, error } = useEmotion();

  const emo = sentiment?.emotion;
  const askAiContext = [
    `当前页面：市场情绪详情`,
    `日期：${sentiment?.date ?? "未取得"}`,
    emo
      ? `涨停${emo.limit_up_count ?? "--"}/跌停${emo.limit_down_count ?? "--"}/封板率${emo.seal_rate ?? "--"}%/炸板率${emo.broken_rate ?? "--"}%/晋级率${emo.advance_rate ?? "--"}%`
      : `情绪指标：未取得`,
    sentiment?.lianban_stocks && sentiment.lianban_stocks.length > 0
      ? `连板梯队：${sentiment.lianban_stocks.map((s) => `${s.boards}板×${s.code}`).join(" ")}`
      : `连板梯队：无`,
    sentiment?.lianban_count != null
      ? `连板数${sentiment.lianban_count}/炸板${sentiment.zb_count ?? "--"}/昨涨停${sentiment.yzt_count ?? "--"}`
      : ``,
  ].filter(Boolean).join("\n");

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Gauge className="h-5 w-5 text-muted-foreground" />
          <h2 className="text-lg font-semibold">市场情绪详情</h2>
          {sentiment?.date && <span className="text-sm text-muted-foreground/50">{sentiment.date}</span>}
        </div>
        <AskAiButton context={askAiContext} />
      </div>
      
      {isLoading && (
        <div className="py-8 text-center text-sm text-muted-foreground">加载中…</div>
      )}
      
      {error && (
        <div className="py-8 text-center text-sm text-destructive">加载失败</div>
      )}
      
      {sentiment && (
        <div className="space-y-4">
          {/* 关键指标 */}
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-4">
            <GlassCard className="p-4">
              <p className="text-xs text-muted-foreground">涨停</p>
              <p className="mt-1 text-2xl font-bold text-danger">{sentiment.emotion?.limit_up_count ?? "—"}</p>
            </GlassCard>
            <GlassCard className="p-4">
              <p className="text-xs text-muted-foreground">跌停</p>
              <p className="mt-1 text-2xl font-bold text-success">{sentiment.emotion?.limit_down_count ?? "—"}</p>
            </GlassCard>
            <GlassCard className="p-4">
              <p className="text-xs text-muted-foreground">最高连板</p>
              <p className="mt-1 text-2xl font-bold text-primary">{sentiment.emotion?.max_boards ?? "—"} 板</p>
            </GlassCard>
            <GlassCard className="p-4">
              <p className="text-xs text-muted-foreground">连板数（2板+）</p>
              <p className="mt-1 text-2xl font-bold text-primary">{sentiment.lianban_count ?? "—"}</p>
            </GlassCard>
          </div>
          
          {/* 情绪比率 */}
          {sentiment.emotion && (
            <GlassCard className="p-4">
              <h3 className="mb-3 text-sm font-semibold">情绪比率</h3>
              <div className="grid grid-cols-3 gap-4">
                <div className="text-center">
                  <p className="text-xs text-muted-foreground">封板率</p>
                  <p className={cn("mt-1 text-xl font-bold", "text-danger")}>
                    {sentiment.emotion.seal_rate != null ? `${(sentiment.emotion.seal_rate * 100).toFixed(1)}%` : "—"}
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-xs text-muted-foreground">炸板率</p>
                  <p className={cn("mt-1 text-xl font-bold", "text-success")}>
                    {sentiment.emotion.broken_rate != null ? `${(sentiment.emotion.broken_rate * 100).toFixed(1)}%` : "—"}
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-xs text-muted-foreground">晋级率</p>
                  <p className={cn("mt-1 text-xl font-bold", "text-danger")}>
                    {sentiment.emotion.advance_rate != null ? `${(sentiment.emotion.advance_rate * 100).toFixed(1)}%` : "—"}
                  </p>
                </div>
              </div>
            </GlassCard>
          )}
          
          {/* 连板股清单 */}
          {sentiment.lianban_stocks.length > 0 && (
            <GlassCard className="p-4">
              <h3 className="mb-3 text-sm font-semibold">连板股明细</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border/50 text-left text-xs text-muted-foreground">
                      <th className="whitespace-nowrap px-2 py-2">名称</th>
                      <th className="whitespace-nowrap px-2 py-2">连板</th>
                      <th className="whitespace-nowrap px-2 py-2">现价</th>
                      <th className="whitespace-nowrap px-2 py-2">涨停%</th>
                      <th className="whitespace-nowrap px-2 py-2">成交额</th>
                      <th className="whitespace-nowrap px-2 py-2">概念</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sentiment.lianban_stocks.map((s) => (
                      <tr key={s.code} className="border-b border-border/30">
                        <td className="px-2 py-2">
                          <span className="font-medium">{s.name}</span>
                          <span className="ml-1 text-xs text-muted-foreground/50">{s.code}</span>
                        </td>
                        <td className="whitespace-nowrap px-2 py-2 font-mono font-bold text-primary">{s.boards} 板</td>
                        <td className="px-2 py-2 font-mono">{s.price}</td>
                        <td className="px-2 py-2 font-mono text-danger">+{s.pct}%</td>
                        <td className="whitespace-nowrap px-2 py-2 font-mono text-muted-foreground">{yi(s.amount)}</td>
                        <td className="whitespace-nowrap px-2 py-2 text-xs text-muted-foreground">{s.industry}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </GlassCard>
          )}
        </div>
      )}
    </div>
  );
}
