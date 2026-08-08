// S036：盘中监控标灰——不调 useIntradayData（桩端点 /workflow/realtime 已返 not_implemented）。
// hook 定义保留在 lib/query/limitup.ts，将来补实现时改回 WorkflowStage loading+children 即可。
import { WorkflowStage } from "./components/WorkflowStage";

export default function IntradayMonitor() {
  return (
    <WorkflowStage
      title="盘中监控"
      subtitle="Intraday Monitor"
      notImplemented
      notImplementedMessage="盘中实时监控 / 信号 / 预警尚未实现。"
    />
  );
}
