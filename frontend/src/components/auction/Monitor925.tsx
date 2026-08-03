// S025-E1 Monitor925：9:25 盘中监控。
// 消费 useAuctionMonitor；窗口内(9:15-9:30)渲染 monitor+watchlist 实时；
// 窗口外快照 + 下次窗口倒计时（setInterval 60s 筯到次日 9:15）。
// refetchInterval 由 useAuctionMonitor 按 isInAuctionWindow() 自驱（15s / false）。
import { useState, useEffect } from "react";
import { useAuctionMonitor, isInAuctionWindow } from "@/lib/query";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Radio, Clock, Activity, Eye, Info } from "lucide-react";

/** 窗口外倒计时轮询间隔（ms）—— 仅刷新显示，不影响 react-query refetchInterval。 */
const COUNTDOWN_TICK_MS = 60_000;
/** 竞价窗口开始：周一至五 9:15（分钟数）。 */
const AUCTION_START_MIN = 9 * 60 + 15;

/**
 * 计算下一个竞价窗口开始时刻（周一至五 9:15）。注入 now 便测。
 * 若今天工作日且当前在 9:15 前 → 今天 9:15；否则往后找下一个工作日 9:15。
 */
export function getNextAuctionWindow(now: Date): Date {
  const day = now.getDay();
  const minutesNow = now.getHours() * 60 + now.getMinutes();
  const isTodayWeekday = day >= 1 && day <= 5;
  if (isTodayWeekday && minutesNow < AUCTION_START_MIN) {
    const d = new Date(now);
    d.setHours(9, 15, 0, 0);
    return d;
  }
  const d = new Date(now);
  d.setHours(9, 15, 0, 0);
  d.setDate(d.getDate() + 1);
  while (d.getDay() === 0 || d.getDay() === 6) {
    d.setDate(d.getDate() + 1);
  }
  return d;
}

/** 格式化倒计时（天/时/分），ms <= 0 返回"即将开始"。 */
function formatCountdown(from: Date, to: Date): string {
  const ms = to.getTime() - from.getTime();
  if (ms <= 0) return "即将开始";
  const totalMin = Math.floor(ms / 60_000);
  const days = Math.floor(totalMin / (60 * 24));
  const hours = Math.floor((totalMin % (60 * 24)) / 60);
  const mins = totalMin % 60;
  const parts: string[] = [];
  if (days > 0) parts.push(`${days}天`);
  if (hours > 0 || days > 0) parts.push(`${hours}时`);
  parts.push(`${mins}分`);
  return parts.join("");
}

export function Monitor925() {
  const { data, isLoading, error } = useAuctionMonitor();
  const [now, setNow] = useState(() => new Date());

  // 窗口外 60s 轮询更新倒计时显示（窗口内不影响实时数据，仅刷新 now 用于判定边界）
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), COUNTDOWN_TICK_MS);
    return () => clearInterval(id);
  }, []);

  const inWindow = isInAuctionWindow(now);
  const signals = data?.[0];
  const watchlist = data?.[1];
  const errMsg = error instanceof Error ? error.message : error ? String(error) : null;

  if (isLoading && !data) {
    return (
      <div className="space-y-4">
        <SectionHeader title="9:25 盘中监控" />
        <GlassCard>
          <div className="py-8">
            <Skeleton className="mx-auto h-6 w-48" />
          </div>
        </GlassCard>
      </div>
    );
  }

  if (errMsg && !data) {
    return (
      <EmptyState
        icon={<Info className="h-8 w-8 text-destructive/40" />}
        title="加载失败"
        description={errMsg}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <SectionHeader title="9:25 盘中监控" />
        {inWindow ? (
          <span className="inline-flex items-center gap-1.5 rounded-md bg-danger/10 px-2.5 py-1 text-xs font-medium text-danger">
            <Radio className="h-3.5 w-3.5 animate-pulse" />
            实时监控中
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-md bg-muted/30 px-2.5 py-1 text-xs font-medium text-muted-foreground">
            <Clock className="h-3.5 w-3.5" />
            快照模式
          </span>
        )}
      </div>

      {!inWindow && (
        <div className="rounded-lg bg-muted/20 p-3 text-sm text-muted-foreground">
          距下次竞价窗口：
          <span className="ml-1 font-mono font-bold text-primary">
            {formatCountdown(now, getNextAuctionWindow(now))}
          </span>
        </div>
      )}

      {/* 监控信号 */}
      <GlassCard>
        <SectionHeader title="竞价信号" />
        {signals && signals.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/50 bg-muted/20 text-left text-xs text-muted-foreground">
                  <th className="whitespace-nowrap px-3 py-2.5 font-medium">代码</th>
                  <th className="whitespace-nowrap px-3 py-2.5 font-medium">名称</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-center font-medium">信号类型</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-center font-medium">置信度</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-center font-medium">开盘溢价(%)</th>
                  <th className="whitespace-nowrap px-3 py-2.5 text-center font-medium">量比</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/20">
                {signals.map((s) => (
                  <tr key={s.code} className="transition-colors hover:bg-muted/20">
                    <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted-foreground/60">
                      {s.code}
                    </td>
                    <td className="px-3 py-2.5 font-medium">{s.name}</td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-center">
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] text-primary">
                        {s.signal_type}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                      {(s.confidence * 100).toFixed(0)}%
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                      {s.open_premium > 0
                        ? `+${s.open_premium.toFixed(2)}`
                        : s.open_premium.toFixed(2)}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2.5 text-center font-mono text-xs">
                      {s.volume_ratio.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            icon={<Activity className="h-8 w-8 text-muted-foreground/40" />}
            title="暂无竞价信号"
          />
        )}
      </GlassCard>

      {/* 自选监控 */}
      <GlassCard>
        <SectionHeader title="自选监控列表" />
        {watchlist && watchlist.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {watchlist.map((code) => (
              <span
                key={code}
                className="rounded-md bg-muted/30 px-2 py-1 font-mono text-xs"
              >
                {code}
              </span>
            ))}
          </div>
        ) : (
          <EmptyState
            icon={<Eye className="h-8 w-8 text-muted-foreground/40" />}
            title="暂无自选监控"
          />
        )}
      </GlassCard>
    </div>
  );
}
