// S179 Phase 2: /review 复盘中心——行为模式 + 研报管理 + 研究记录三 tab。
// spec §5.3 R2.6：接现有 BehaviorLoop（行为闭环·影子对照）+ MyReports（研报归档）+ Notes（研究记录）。
// Standard layout 单焦点页，TabBar 切换；URL ?tab= 持久化可分享（S179 §5.1 L2 query param 范式，
// 不依赖 pathname hack）。旧 /behavior-loop + /my-reports + /notes 路由 Phase 3 redirect 到 /review?tab=。
//
// deferred：行为模式数据源（影子对照 winrate/胜率反馈闭环）深度整合待 Phase 3 组件拆分后细化——
// 当前直接嵌入现有整页组件（含各自 PageHeader/Disclaimer），Phase 3 拆为 review 子组件去重表头。
import { useSearchParams } from "react-router-dom";
import { type ReactNode } from "react";
import { Activity, FileText, NotebookPen } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { TabBar } from "@/components/ui/TabBar";
import BehaviorLoop from "@/pages/BehaviorLoop";
import { MyReports } from "@/pages/MyReports";
import { Notes } from "@/pages/Notes";

type ReviewTabKey = "behavior" | "reports" | "notes";

const REVIEW_TABS: { key: ReviewTabKey; label: string; icon: ReactNode }[] = [
  { key: "behavior", label: "行为模式", icon: <Activity className="h-3.5 w-3.5" /> },
  { key: "reports", label: "研报管理", icon: <FileText className="h-3.5 w-3.5" /> },
  { key: "notes", label: "研究记录", icon: <NotebookPen className="h-3.5 w-3.5" /> },
];

function isTabKey(v: string | null): v is ReviewTabKey {
  return v === "behavior" || v === "reports" || v === "notes";
}

export function ReviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get("tab");
  const active: ReviewTabKey = isTabKey(tabParam) ? tabParam : "behavior";

  // TabBar onChange 给 string；写回 URL ?tab=（replace 不入历史栈，避免后退栈污染）
  const switchTab = (k: string): void => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", k);
    setSearchParams(next, { replace: true });
  };

  const subtitle =
    active === "behavior"
      ? "影子对照·三桶算账·独立性基线——系统建议单 vs 感觉单 vs 漏掉候选"
      : active === "reports"
        ? "研报归档·按行业分类·只存本地不上传"
        : "AI 复盘/要点/问答沉淀本地·随时回看";

  return (
    <div>
      <PageHeader title="复盘中心" subtitle={subtitle} />

      <div className="mb-6">
        <TabBar tabs={REVIEW_TABS} activeKey={active} onChange={switchTab} />
      </div>

      {/* 嵌入现有整页组件：各带 PageHeader/Disclaimer，Phase 3 拆子组件去重 */}
      {active === "behavior" && <BehaviorLoop />}
      {active === "reports" && <MyReports />}
      {active === "notes" && <Notes />}
    </div>
  );
}
