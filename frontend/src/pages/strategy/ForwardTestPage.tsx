// S090 战法 tab 404 修复：前向测试独立页（thin 包装 ForwardTestPanel）。
// Workflow.tsx EntryCard to="/strategy/funnel/forward-test" 原指向 404，补路由 + 包装页。
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { ForwardTestPanel } from "@/components/workflow/ForwardTestPanel";

export default function ForwardTestPage() {
  return (
    <div className="space-y-4 p-4">
      <Link
        to="/workflow"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" /> 返回战法
      </Link>
      <PageHeader
        title="前向测试"
        subtitle="每日推荐 vs 实际表现 · §44 60 日复验窗口"
      />
      <ForwardTestPanel />
    </div>
  );
}
