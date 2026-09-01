// S140 R6：标的 7 态常驻 rail——跨语境复用 StateMachineDashboard。
// 接 date prop（SelectionStageView 传 triplet.today）；useWorkflowStates 内 enabled:!!date 自带门控。
// date 空时返 null（防 IntradayMonitor 全零覆辙——rail 不在缺数据时空挂全零 grid）。
import { StateMachineDashboard } from "@/components/intraday/StateMachineDashboard";

export function CandidateStateRail({ date }: { date?: string }) {
  if (!date) return null;
  return <StateMachineDashboard date={date} />;
}
