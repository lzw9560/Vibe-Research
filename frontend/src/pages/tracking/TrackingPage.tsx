import { PageHeader } from "@/components/ui/PageHeader";
import { TrackingPanel } from "@/components/tracking/TrackingPanel";

export function TrackingPage() {
  return (
    <div className="space-y-4">
      <PageHeader
        title="多日跟踪"
        subtitle="S204 多日跟踪架构——活跃 track 池 + 指标快照演进（只读看板，escalation 自动 candidate→watching）"
      />
      <TrackingPanel />
    </div>
  );
}
