// M6 全球指数状态块诚实化测试（防回归：空数据时不消失，显状态）
// 7970e96 实现——globalIdx.length===0 时显 isLoading/error/暂无 而非消失
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { GlobalIndicesEmptyState } from "@/pages/market/MarketPage";

describe("M6 全球指数状态块诚实化（7970e96）", () => {
  it("error=true → 显「全球行情未接通」", () => {
    render(<GlobalIndicesEmptyState isLoading={false} error={true} />);
    expect(screen.getByText("全球行情未接通")).toBeInTheDocument();
  });

  it("isLoading=true → 显「加载中…」", () => {
    render(<GlobalIndicesEmptyState isLoading={true} error={false} />);
    expect(screen.getByText("加载中…")).toBeInTheDocument();
  });

  it("空 + 非 error/loading → 显「暂无数据」（非消失）", () => {
    render(<GlobalIndicesEmptyState isLoading={false} error={false} />);
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
  });
});
