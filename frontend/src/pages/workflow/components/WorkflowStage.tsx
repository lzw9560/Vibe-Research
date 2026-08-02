/** WorkflowStage - 三页共享骨架 */
import { GlassCard } from "@/components/ui/GlassCard";
import { Skeleton } from "@/components/ui/Skeleton";
import { PageHeader } from "@/components/ui/PageHeader";
import { RefreshCw } from "lucide-react";

interface Props {
  title: string;
  subtitle: string;
  loading: boolean;
  onRefresh?: () => void;
  children: React.ReactNode;
}

export function WorkflowStage({ title, subtitle, loading, onRefresh, children }: Props) {
  return (
    <div>
      <PageHeader 
        title={title} 
        subtitle={subtitle}
        actions={onRefresh ? (
          <button onClick={onRefresh} className="text-muted-foreground hover:text-primary" title="刷新">
            <RefreshCw className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
          </button>
        ) : undefined}
      />
      
      {loading ? (
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
