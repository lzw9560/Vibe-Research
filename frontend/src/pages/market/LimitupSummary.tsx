// S179 Phase 1: 涨停 / 炸板 / 连板摘要组件（客观公开榜单，非推荐）。
// 复用 ShortTermEmotion 数据源（useEmotion hook），从 DailyReview 抽出为独立组件。
import { Flame } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";
import type { ShortTermEmotion } from "@/lib/api";

interface Props {
  emotion: ShortTermEmotion | null;
  loading: boolean;
}

export function LimitupSummary({ emotion, loading }: Props) {
  const metrics = emotion?.emotion;

  return (
    <GlassCard className="p-4">
      <div className="mb-3 flex items-center gap-1.5">
        <Flame className="h-4 w-4 text-primary" />
        <h3 className="text-sm font-semibold">涨停 / 炸板 / 连板</h3>
        {emotion?.date && (
          <span className="ml-auto text-[11px] text-muted-foreground/50">
            {emotion.date}
          </span>
        )}
      </div>

      {/* honest banner: 客观公开榜单，非推荐 */}
      <div className="mb-3 rounded-md bg-muted/30 px-3 py-1.5 text-[11px] text-muted-foreground">
        客观公开榜单 · 非推荐 / 非预测
      </div>

      {!metrics || metrics.limit_up_count == null ? (
        <p className="py-4 text-center text-sm text-muted-foreground">
          {loading ? "加载中…" : "暂无数据（可能是非交易时段）"}
        </p>
      ) : (
        <>
          {/* 关键计数 */}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              {
                k: "涨停",
                v: `${metrics.limit_up_count}`,
                cls: "text-danger",
              },
              {
                k: "跌停",
                v: `${metrics.limit_down_count}`,
                cls: "text-success",
              },
              {
                k: "最高连板",
                v: `${metrics.max_boards} 板`,
                cls: "text-primary",
              },
              {
                k: "连板(2+)",
                v: `${emotion?.lianban_count ?? 0} 家`,
                cls: "text-primary",
              },
            ].map((c) => (
              <div
                key={c.k}
                className="rounded-lg bg-muted/25 p-2.5 text-center"
              >
                <p className="text-[11px] text-muted-foreground">{c.k}</p>
                <p className={cn("mt-0.5 font-mono text-lg font-bold", c.cls)}>
                  {c.v}
                </p>
              </div>
            ))}
          </div>

          {/* 打板情绪比率 */}
          <div className="mt-2 grid grid-cols-3 gap-2">
            {[
              {
                k: "封板率",
                v: metrics.seal_rate,
                hint: "封住 / 尝试涨停",
                cls: "text-danger",
              },
              {
                k: "炸板率",
                v: metrics.broken_rate,
                hint: "炸板 / 尝试涨停",
                cls: "text-success",
              },
              {
                k: "晋级率",
                v: metrics.advance_rate,
                hint: "昨涨停今又停",
                cls: "text-primary",
              },
            ].map((c) => (
              <div
                key={c.k}
                className="rounded-lg bg-muted/20 p-2.5 text-center"
              >
                <p className="text-[11px] text-muted-foreground">{c.k}</p>
                <p className={cn("mt-0.5 font-mono text-sm font-bold", c.cls)}>
                  {c.v == null ? "—" : `${(c.v * 100).toFixed(1)}%`}
                </p>
                <p className="mt-0.5 text-[10px] text-muted-foreground/50">
                  {c.hint}
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </GlassCard>
  );
}
