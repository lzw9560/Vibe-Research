/** WorkflowStage - 工作流页共享骨架
 * S036：加 notImplemented 横幅——为 true 时渲染未实现态替代 children/loading，
 * 三页（IntradayMonitor/PostMarketReview/BombAlertPanel）停止调用桩端点后统一呈现。
 */
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { PageHeader } from "@/components/ui/PageHeader";
import { RefreshCw } from "lucide-react";

interface Props {
  title: string;
  subtitle: string;
  loading?: boolean;
  onRefresh?: () => void;
  /** 额外操作按钮（如 AskAiButton），渲染在刷新按钮左侧 */
  actions?: React.ReactNode;
  notImplemented?: boolean;
  notImplementedMessage?: string;
  children?: React.ReactNode;
}

export function WorkflowStage({
  title,
  subtitle,
  loading,
  onRefresh,
  actions,
  notImplemented,
  notImplementedMessage,
  children,
}: Props) {
  return (
    <div>
      <PageHeader
        title={title}
        subtitle={subtitle}
        actions={
          <div className="flex items-center gap-2">
            {actions}
            {onRefresh ? (
              <button onClick={onRefresh} className="text-muted-foreground hover:text-primary" title="刷新">
                <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
              </button>
            ) : undefined}
          </div>
        }
      />

      {notImplemented ? (
        <GlassCard className="p-10">
          <div className="flex flex-col items-center gap-3 text-center">
            <span className="inline-flex items-center rounded-full bg-muted/30 px-3 py-1 text-xs font-medium text-muted-foreground">
              未实现
            </span>
            <p className="text-sm text-muted-foreground/70">
              {notImplementedMessage ?? "此功能尚未实现"}
            </p>
          </div>
        </GlassCard>
      ) : loading ? (
        <div className="space-y-4">
          <Skeleton variant="rectangular" className="h-32" />
          <Skeleton variant="rounded" className="h-24" />
          <Skeleton variant="rounded" className="h-24" />
        </div>
      ) : (
        <GlassCard className="p-6">{children}</GlassCard>
      )}
    </div>
  );
}
