// M3 涨停池错误态诚实化测试（防回归：error 不伪装「暂无涨停股」）
// 7970e96 实现——端点挂了显「涨停池数据加载失败」非「暂无涨停股」
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { LianbanList } from "@/pages/intraday/IntradayCockpit";

const baseProps = {
  selectedCode: null,
  onSelect: () => {},
  isTradingDay: true,
};

describe("M3 LianbanList 错误态诚实化（7970e96）", () => {
  it("error=true → 显「涨停池数据加载失败」非「暂无涨停股」", () => {
    render(
      <MemoryRouter>
        <LianbanList stocks={[]} loading={false} error={true} {...baseProps} />
      </MemoryRouter>
    );
    expect(screen.getByText("涨停池数据加载失败")).toBeInTheDocument();
    expect(screen.queryByText("暂无涨停股")).not.toBeInTheDocument();
  });

  it("loading=true → 显「加载中…」", () => {
    render(
      <MemoryRouter>
        <LianbanList stocks={[]} loading={true} error={false} {...baseProps} />
      </MemoryRouter>
    );
    expect(screen.getByText("加载中…")).toBeInTheDocument();
  });

  it("空 + 非交易日 → 显「暂无涨停股」+ 非交易日 hint（非 error）", () => {
    render(
      <MemoryRouter>
        <LianbanList stocks={[]} loading={false} error={false} selectedCode={null} onSelect={() => {}} isTradingDay={false} />
      </MemoryRouter>
    );
    expect(screen.getByText("暂无涨停股")).toBeInTheDocument();
    expect(screen.getByText(/非交易日/)).toBeInTheDocument();
  });
});
