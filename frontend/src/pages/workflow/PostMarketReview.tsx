// S036：盘后复盘标灰——不调 usePostMarketReview（桩端点 /workflow/post-market 已返 not_implemented）。
// 批量结算未实现；单股结算请用状态机流转 settled 触发（S034）。
// hook 定义保留在 lib/query/limitup.ts，将来补实现时改回 WorkflowStage loading+children 即可。
import { WorkflowStage } from "./components/WorkflowStage";

export default function PostMarketReview() {
  return (
    <WorkflowStage
      title="盘后复盘"
      subtitle="Post-Market Review"
      notImplemented
      notImplementedMessage="盘后批量结算 / LLM 复盘尚未实现；单股结算请用状态机流转 settled（S034）。"
    />
  );
}
