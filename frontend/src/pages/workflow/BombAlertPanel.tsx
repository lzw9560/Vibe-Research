// S036：炸板预警标灰——不调 useBombAlerts（桩端点 /workflow/alerts 已返 not_implemented）。
// check_bomb_alerts 桩有部分封单逻辑但 run_intraday 不调它，前端永远拿空——标灰。
// hook 定义保留在 lib/query/limitup.ts，将来补实现时改回 WorkflowStage loading+children 即可。
import { WorkflowStage } from "./components/WorkflowStage";

export default function BombAlertPanel() {
  return (
    <WorkflowStage
      title="炸板预警"
      subtitle="Bomb Alert Panel"
      notImplemented
      notImplementedMessage="炸板预警尚未实现。"
    />
  );
}
