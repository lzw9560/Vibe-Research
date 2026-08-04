// S024-B DRY 抽公共：拓扑面板外壳。
// RelationGraph/FunnelFlow/BoardLadder 三组件重复同 JSX 骨架
//（GlassCard + SectionHeader + loading/error/children 三元）。本组件封装该骨架。
import { type ReactNode } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { LoadingState, ErrorState } from "@/components/ui/State";

interface TopologyPanelProps {
  title: ReactNode;
  icon?: ReactNode;
  subtitle?: string;
  isLoading: boolean;
  loadingLabel?: string;
  error: unknown;
  errorMessage: string;
  refetch?: () => void;
  children: ReactNode;
}

/**
 * 拓扑面板外壳：GlassCard + SectionHeader + 三态（loading/error/children）。
 * 三拓扑容器（关系网/漏斗流程/连板梯队）共用此骨架，各自只传 title/icon/数据接线。
 */
export function TopologyPanel({
  title,
  icon,
  subtitle,
  isLoading,
  loadingLabel,
  error,
  errorMessage,
  refetch,
  children,
}: TopologyPanelProps) {
  return (
    <GlassCard>
      <SectionHeader title={title} icon={icon} subtitle={subtitle} />
      {isLoading ? (
        <LoadingState variant="inline" label={loadingLabel} />
      ) : error ? (
        <ErrorState
          message={errorMessage}
          onRetry={refetch ? () => refetch() : undefined}
        />
      ) : (
        children
      )}
    </GlassCard>
  );
}
