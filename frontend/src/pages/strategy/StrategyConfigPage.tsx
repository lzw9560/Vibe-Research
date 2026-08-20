// S090 战法 tab 404 修复：战法阈值配置独立页（thin 包装 ThresholdPanel）。
// Workflow.tsx EntryCard to="/strategy/funnel/config" 原指向 404，补路由 + 包装页。
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { ThresholdPanel } from "@/components/candidate/ThresholdPanel";

export default function StrategyConfigPage() {
  return (
    <div className="space-y-4 p-4">
      <Link
        to="/workflow"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 返回战法
      </Link>
      <PageHeader
        title="战法阈值配置"
        subtitle="auto/suggest/manual 三模式 · S081 阈值 + funnel config"
      />
      <ThresholdPanel />
    </div>
  );
}
