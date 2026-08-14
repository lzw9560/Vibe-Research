// S066 §11.5 因子详情子页测试。
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { FactorDetailPage } from "@/pages/workflow/FactorDetailPage";

// 必须包 Routes + Route 让 useParams 取到 :factorId（MemoryRouter 单独不带路由匹配）
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/workflow/factor/:factorId" element={<FactorDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("FactorDetailPage (S066)", () => {
  it("渲染面包屑导航（盘前 / 策略组）", () => {
    renderAt("/workflow/factor/1");
    expect(screen.getAllByText("盘前").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("策略组").length).toBeGreaterThanOrEqual(1);
  });

  it("渲染因子定义卡片标题（封板时间早 #1）", () => {
    renderAt("/workflow/factor/1");
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading.textContent).toContain("封板时间早");
  });

  it("渲染返回按钮链接", () => {
    renderAt("/workflow/factor/1");
    const links = screen.getAllByRole("link");
    expect(links.some((l) => l.textContent?.includes("返回"))).toBe(true);
  });

  it("不存在的因子 ID → 显示未找到", () => {
    renderAt("/workflow/factor/9999");
    expect(screen.getByText(/未找到/)).toBeInTheDocument();
  });

  it("因子 #30 周五信号日渲染日历类", () => {
    renderAt("/workflow/factor/30");
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading.textContent).toContain("周五信号日");
    expect(screen.getByText("利空")).toBeInTheDocument();
  });

  it("因子 #29 周四逆势涨停显示已验证证据", () => {
    renderAt("/workflow/factor/29");
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading.textContent).toContain("周四逆势涨停");
    // 88.9% 可能出现在证据等级字段 + 因子说明区，用 getAllByText
    expect(screen.getAllByText(/88.9%/).length).toBeGreaterThanOrEqual(1);
  });

  it("因子定义卡片显示证据等级 + 数据源", () => {
    renderAt("/workflow/factor/1");
    expect(screen.getByText("证据等级")).toBeInTheDocument();
    expect(screen.getByText("数据源")).toBeInTheDocument();
    expect(screen.getByText("系统状态")).toBeInTheDocument();
  });
});
