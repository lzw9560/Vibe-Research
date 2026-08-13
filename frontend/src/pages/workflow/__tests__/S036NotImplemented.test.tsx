import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { WorkflowStage } from "../components/WorkflowStage";
import BombAlertPanel from "../BombAlertPanel";

// S036 工作流标灰——WorkflowStage notImplemented prop + BombAlertPanel 未实现态。
// IntradayMonitor 已由 S063 去桩重写（真实四层布局），不再属 S036 未实现态，
// 其测试在 IntradayMonitor.test.tsx；PostMarketReview 已由 S054 去桩重写，
// 其测试在 PostMarketReview.test.tsx。

describe("S036 工作流标灰", () => {
  it("WorkflowStage notImplemented=true 渲染未实现横幅，不渲染 children", () => {
    render(
      <WorkflowStage
        title="t"
        subtitle="s"
        notImplemented
        notImplementedMessage="未实现说明"
      >
        <div data-testid="child">不应出现</div>
      </WorkflowStage>,
    );
    expect(screen.getByText("未实现")).toBeInTheDocument();
    expect(screen.getByText("未实现说明")).toBeInTheDocument();
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
  });

  it("WorkflowStage 未传 notImplemented 时正常渲染 children（回归 PreMarketBriefing 用法）", () => {
    render(
      <WorkflowStage title="t" subtitle="s">
        <div data-testid="child">内容</div>
      </WorkflowStage>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
    expect(screen.queryByText("未实现")).not.toBeInTheDocument();
  });

  it("BombAlertPanel 渲染未实现态（不调 hook）", () => {
    render(<BombAlertPanel />);
    expect(screen.getByText("未实现")).toBeInTheDocument();
    expect(screen.getByText(/炸板预警尚未实现/)).toBeInTheDocument();
  });
});
