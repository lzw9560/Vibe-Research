// S066 §11.4 盘后页面——前向测试命中率 + 策略分追踪 + 衰减监控面板。
// spec §11.4：当日候选 vs 实际表现（命中率）/ 策略分排名 vs 实际收益 / 策略衰减监控（4 周滚动胜率）。
import { CheckCircle2, AlertTriangle, TrendingUp, TrendingDown, Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { useForwardTestSummary } from "@/lib/query/strategy";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { Badge } from "@/components/ui/Badge";

/** S066 §0e 前向测试命中率面板。
 * 显示：总交易日 / 已结算推荐 / 胜率 vs 基准×0.8 / 平均收益 / 连续亏损 / §44 60日复验窗口三态。
 */
export function ForwardTestPanel() {
  const { data, isLoading } = useForwardTestSummary();

  if (isLoading) {
    return <Skeleton className="h-48 w-full" />;
  }

  if (!data) {
    return (
      <GlassCard className="p-4">
        <p className="text-sm text-muted-foreground">前向测试数据未取得</p>
      </GlassCard>
    );
  }

  // §44 60日复验窗口四态判定（主显示），passed 字段向后兼容保留
  // 优先级：探索性（n<30）> 劣于随机（lift<1）> validated > 未 validated
  const validationStatus = data.validation_status ?? "未 validated";
  const isValidated = validationStatus === "validated";
  const isExploratory = validationStatus === "探索性";
  const isWorseThanRandom = validationStatus === "劣于随机";  // lift<1 硬底线
  const killAlert = data.consecutive_loss >= 5;  // 策略级 kill criteria 预警（仍走 destructive）
  const winRateLow = data.settled_count > 0 && data.win_rate < data.pass_threshold;
  const progress = Math.min(data.total_days / 20, 1) * 100;  // 20 交易日进度

  // 主状态文案：kill 预警优先，次 validation_status 四态
  const statusText = killAlert
    ? "Kill Criteria 预警"
    : isExploratory
      ? "§44 探索性（n<30）"
      : isWorseThanRandom
        ? "§44 硬底线（劣于随机，移除/权重0）"
        : isValidated
          ? "§44 validated"
          : "§44 未 validated（跑通中，60日后复验）";
  // 图标：kill 预警 AlertTriangle，劣于随机 TrendingDown（红），探索性 TrendingDown（灰），validated CheckCircle2，未 validated Activity
  const StatusIcon = killAlert
    ? AlertTriangle
    : isExploratory
      ? TrendingDown
      : isWorseThanRandom
        ? TrendingDown
        : isValidated
          ? CheckCircle2
          : Activity;

  return (
    <div className="space-y-4">
      <SectionHeader
        title="前向测试（Paper Trading）"
        subtitle="每日推荐 vs 实际表现 · 不投真金 · §44 60日复验窗口"
      />

      {/* §44 60日复验窗口四态状态横幅 */}
      <div
        className={cn(
          "flex items-center gap-3 rounded-lg border px-4 py-3",
          killAlert
            ? "border-destructive/40 bg-destructive/10 text-destructive"
            : isWorseThanRandom
              ? "border-destructive/40 bg-destructive/10 text-destructive"  // 劣于随机=硬底线，红色（移除/权重0）
              : isValidated
                ? "border-success/30 bg-success/5 text-success"
                : isExploratory
                  ? "border-muted-foreground/30 bg-muted/5 text-muted-foreground"
                  : "border-warning/30 bg-warning/5 text-warning",
        )}
      >
        <StatusIcon className="h-5 w-5 shrink-0" />
        <div className="flex-1">
          <p className="text-sm font-bold">{statusText}</p>
          <p className="text-xs opacity-80">{data.note}</p>
        </div>
        <Badge variant={killAlert || isWorseThanRandom ? "danger" : isValidated ? "success" : isExploratory ? "default" : "warning"}>
          {data.total_days}/20 日
        </Badge>
      </div>

      {/* 核心指标 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <GlassCard className="p-3">
          <p className="text-xs text-muted-foreground">已结算推荐</p>
          <p className="mt-1 font-mono text-xl font-bold">
            {data.settled_count}
            <span className="text-sm text-muted-foreground">/{data.total_recommendations}</span>
          </p>
        </GlassCard>
        <GlassCard className="p-3">
          <p className="text-xs text-muted-foreground">胜率</p>
          <p className={cn(
            "mt-1 font-mono text-xl font-bold",
            winRateLow ? "text-destructive" : "text-success",
          )}>
            {data.win_rate.toFixed(1)}%
          </p>
          <p className="text-xs text-muted-foreground">阈值 {data.pass_threshold.toFixed(1)}%</p>
        </GlassCard>
        <GlassCard className="p-3">
          <p className="text-xs text-muted-foreground">平均收益</p>
          <p className={cn(
            "mt-1 font-mono text-xl font-bold",
            data.avg_return > 0 ? "text-success" : "text-destructive",
          )}>
            {data.avg_return > 0 ? "+" : ""}{data.avg_return.toFixed(2)}%
          </p>
        </GlassCard>
        <GlassCard className="p-3">
          <p className="text-xs text-muted-foreground">连续亏损</p>
          <p className={cn(
            "mt-1 font-mono text-xl font-bold",
            killAlert ? "text-destructive" : "",
          )}>
            {data.consecutive_loss}
          </p>
          <p className="text-xs text-muted-foreground">kill 阈值 8</p>
        </GlassCard>
      </div>

      {/* 进度条 */}
      <GlassCard className="p-3">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>验证进度</span>
          <span>{data.total_days}/20 交易日</span>
        </div>
        <div className="mt-2 h-2 rounded-full bg-muted/30">
          <div
            className={cn(
              "h-2 rounded-full transition-all",
              isValidated ? "bg-success" : "bg-primary",
            )}
            style={{ width: `${progress}%` }}
          />
        </div>
      </GlassCard>

      {/* 基准对照 */}
      <GlassCard className="p-3">
        <div className="flex items-center gap-2">
          {data.win_rate >= data.benchmark_win_rate ? (
            <TrendingUp className="h-4 w-4 text-success" />
          ) : (
            <TrendingDown className="h-4 w-4 text-muted-foreground" />
          )}
          <span className="text-sm">
            策略胜率 {data.win_rate.toFixed(1)}% vs 基准 {data.benchmark_win_rate.toFixed(1)}%
            {data.win_rate >= data.benchmark_win_rate
              ? "（跑赢基准，alpha 存在）"
              : data.settled_count > 0
                ? "（未跑赢基准，策略分排序方向待优化）"
                : "（无已结算样本）"}
          </span>
        </div>
      </GlassCard>
    </div>
  );
}
