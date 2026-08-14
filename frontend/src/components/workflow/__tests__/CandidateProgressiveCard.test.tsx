// S066 §11.1 CandidateProgressiveCard L0-L3 渐进式披露测试。
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CandidateProgressiveCard, type CandidateCardData } from "@/components/workflow/CandidateProgressiveCard";

const baseCandidate: CandidateCardData = {
  code: "003032",
  name: "传智教育",
  strategy_code: "consecutive_relay",
  strategy_name: "连板接力",
  strategy_score: 85.0,
  one_line_reason: "连板接力+封板强",
  position_pct: 4.5,
  risk_label: "中风险",
};

function renderCard(overrides: Partial<CandidateCardData> = {}) {
  const candidate = { ...baseCandidate, ...overrides };
  return render(
    <MemoryRouter>
      <CandidateProgressiveCard candidate={candidate} />
    </MemoryRouter>,
  );
}

describe("CandidateProgressiveCard (S066 §11.1)", () => {
  it("L0 默认渲染一行（代码/名称/分/理由/仓位/风险）", () => {
    renderCard();
    expect(screen.getByText("003032")).toBeInTheDocument();
    expect(screen.getByText("传智教育")).toBeInTheDocument();
    expect(screen.getByText(/85.0/)).toBeInTheDocument();
    expect(screen.getByText("连板接力+封板强")).toBeInTheDocument();
    expect(screen.getByText("4.5%")).toBeInTheDocument();
    expect(screen.getByText("中风险")).toBeInTheDocument();
  });

  it("点击 L0 → 展开 L1 摘要", () => {
    renderCard({
      sector_phase: "发酵",
      sector_modifier: 1.0,
      calendar_factor: 0.7,
      hot_money_risk: "中风险",
      sector_rank: 3,
    });
    // 初始 L1 不可见
    expect(screen.queryByText("板块阶段")).not.toBeInTheDocument();
    // 点击展开
    fireEvent.click(screen.getByText("连板接力+封板强"));
    expect(screen.getByText("板块阶段")).toBeInTheDocument();
    expect(screen.getByText("发酵")).toBeInTheDocument();
    expect(screen.getByText("×0.7")).toBeInTheDocument();
    expect(screen.getByText("#3")).toBeInTheDocument();
  });

  it("再点 L0 → 收起 L1", () => {
    renderCard({ sector_phase: "发酵" });
    const trigger = screen.getByText("连板接力+封板强");
    fireEvent.click(trigger); // 展开
    expect(screen.getByText("板块阶段")).toBeInTheDocument();
    fireEvent.click(trigger); // 收起
    expect(screen.queryByText("板块阶段")).not.toBeInTheDocument();
  });

  it("L1 展开 → 点击「更多详情」展开 L2", () => {
    renderCard({
      factors: { factor_seal_rate: 90, factor_rebound_rate: 80 },
      quality_standards: [{ name: "连板数≥2", passed: true, required: true, detail: "连板数=3" }],
    });
    fireEvent.click(screen.getByText("连板接力+封板强")); // L1
    fireEvent.click(screen.getByText("更多详情")); // L2
    expect(screen.getByText("完整因子分解")).toBeInTheDocument();
    expect(screen.getByText("factor_seal_rate")).toBeInTheDocument();
    expect(screen.getByText("质量标准检查")).toBeInTheDocument();
  });

  it("无风险标签不渲染（避免噪音）", () => {
    renderCard({ risk_label: "无风险" });
    expect(screen.queryByText("无风险")).not.toBeInTheDocument();
  });

  it("策略分构成 L1 展示", () => {
    renderCard({
      score_breakdown: { factor_seal_rate: 29.8, factor_rebound_rate: 46.3 },
    });
    fireEvent.click(screen.getByText("连板接力+封板强"));
    expect(screen.getByText("策略分构成")).toBeInTheDocument();
    expect(screen.getByText(/factor_seal_rate/)).toBeInTheDocument();
  });

  it("资讯雷达 L2 展示三层标签", () => {
    renderCard({
      news_radar: { heat_label: "真热", catalyst_label: "双催化", risk_label: "赛道风险" },
    });
    fireEvent.click(screen.getByText("连板接力+封板强"));
    fireEvent.click(screen.getByText("更多详情"));
    expect(screen.getByText("资讯雷达")).toBeInTheDocument();
    expect(screen.getByText(/热度：真热/)).toBeInTheDocument();
    expect(screen.getByText("双催化")).toBeInTheDocument();
    expect(screen.getByText("赛道风险")).toBeInTheDocument();
  });

  it("游资席位明细 L2 展示占比", () => {
    renderCard({
      hot_money_detail: { day_trip_ratio: 0.6, relay_ratio: 0.3 },
    });
    fireEvent.click(screen.getByText("连板接力+封板强"));
    fireEvent.click(screen.getByText("更多详情"));
    expect(screen.getByText("游资席位明细")).toBeInTheDocument();
    expect(screen.getByText(/60%/)).toBeInTheDocument();
  });

  it("L3 因子子页跳转链接存在", () => {
    renderCard();
    fireEvent.click(screen.getByText("连板接力+封板强"));
    fireEvent.click(screen.getByText("更多详情"));
    expect(screen.getByText("查看因子详情")).toBeInTheDocument();
  });

  it("板块广度 L2 展示 + 健康判定", () => {
    renderCard({ sector_breadth: 0.8 });
    fireEvent.click(screen.getByText("连板接力+封板强"));
    fireEvent.click(screen.getByText("更多详情"));
    expect(screen.getByText(/板块广度/)).toBeInTheDocument();
    expect(screen.getByText(/普涨健康/)).toBeInTheDocument();
  });

  it("板块广度低 → 标注无板块效应", () => {
    renderCard({ sector_breadth: 0.2 });
    fireEvent.click(screen.getByText("连板接力+封板强"));
    fireEvent.click(screen.getByText("更多详情"));
    expect(screen.getByText(/个股行情无板块效应/)).toBeInTheDocument();
  });
});
