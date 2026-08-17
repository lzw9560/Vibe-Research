// S075 077：FirstBoardPipeline 主视图测试。
// mock useFirstBoardCandidates，验证：
//   - 5 步闭环节点全部渲染
//   - 每步 input→output 数量
//   - 剔除原因展开
//   - §44 诚实标注
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

// mock HonestyBanner（避免 useForwardTestSummary 调真实 hook）
vi.mock("@/components/ui/HonestyBanner", () => ({
  HonestyBanner: () => <div data-testid="honesty-banner">§44 诚实标注</div>,
}));

import { FirstBoardPipeline } from "@/pages/workflow/components/FirstBoardPipeline";
import type { FirstBoardCandidatesResponse } from "@/lib/api";

const mockData: FirstBoardCandidatesResponse = {
  date: "2026-08-18",
  zt_pool_count: 106,
  first_board_count: 91,
  candidates: [
    {
      code: "001358", name: "兴欣新材", total: 63.4, rank: 1,
      scores: { sector: 60, hot_money: 70, seal_strength: 80, chip: 50, auction: 50, northbound: 50, institution: 50, theme: 50, event: 50 },
    },
    {
      code: "002567", name: "唐人神", total: 58.2, rank: 2,
      scores: { sector: 55, hot_money: 65, seal_strength: 70, chip: 50, auction: 50, northbound: 50, institution: 50, theme: 50, event: 50 },
    },
  ],
  excluded: [
    { code: "600001", layer: 1, reason: "炸板2次" },
    { code: "600002", layer: 1, reason: "首封14:30尾盘" },
    { code: "600003", layer: 2, reason: "换手30%筹码松动" },
    { code: "600004", layer: 3, reason: "同板块1家涨停无题材" },
  ],
  env_flags: { market_drop_pct: 1.41, high_risk: false, max_boards: 4, ladder_broken: false },
  note: "9维度评分§44未validated仅参考；阈值/权重待回测校准",
};

function renderPipeline(data: FirstBoardCandidatesResponse | null = mockData, isLoading = false) {
  return render(
    <MemoryRouter>
      <FirstBoardPipeline data={data} isLoading={isLoading} />
    </MemoryRouter>,
  );
}

describe("FirstBoardPipeline 主视图 (S075 077)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("5 步闭环节点全部渲染", () => {
    renderPipeline();
    // ① 筛选节点：涨停股池 + 首板过滤 + 三层剔除 + 候选池
    expect(screen.getByText("涨停股池")).toBeInTheDocument();
    expect(screen.getByText("首板过滤")).toBeInTheDocument();
    expect(screen.getByText("三层剔除")).toBeInTheDocument();
    expect(screen.getByText("候选池")).toBeInTheDocument();
    // ② 确认节点（节点标题 "② 确认"，ArrowDown label "② 确认" 也匹配 → getAllByText）
    expect(screen.getAllByText(/② 确认/).length).toBeGreaterThan(0);
    // ③ 建仓节点
    expect(screen.getAllByText(/③ 建仓/).length).toBeGreaterThan(0);
    // ④ 卖出节点
    expect(screen.getAllByText(/④ 卖出/).length).toBeGreaterThan(0);
    // ⑤ 结算节点
    expect(screen.getAllByText(/⑤ 结算/).length).toBeGreaterThan(0);
  });

  it("每步 input→output 数量正确（涨停池 106 / 首板 91 / 候选 2）", () => {
    renderPipeline();
    // 涨停股池数（节点内大数字 + 概览行 → getAllByText）
    expect(screen.getAllByText("106").length).toBeGreaterThan(0);
    // 首板数（节点内大数字 + 概览行多处 → getAllByText）
    expect(screen.getAllByText("91").length).toBeGreaterThan(0);
    // 候选数（节点内大数字 "2"，其他 "2" 可能在多处 → getAllByText）
    expect(screen.getAllByText("2").length).toBeGreaterThan(0);
  });

  it("三层剔除节点点击展开剔除原因", () => {
    renderPipeline();
    // 初始：剔除原因不可见（折叠态）
    expect(screen.queryByText("炸板2次")).not.toBeInTheDocument();
    // 点击展开
    fireEvent.click(screen.getByText("三层剔除"));
    // 展开后：剔除原因可见
    expect(screen.getByText("炸板2次")).toBeInTheDocument();
    expect(screen.getByText(/换手30%筹码松动/)).toBeInTheDocument();
    expect(screen.getByText(/同板块1家涨停无题材/)).toBeInTheDocument();
  });

  it("大盘3因素灯渲染（②确认节点内）", () => {
    renderPipeline();
    expect(screen.getByText("大盘跌")).toBeInTheDocument();
    expect(screen.getByText("连板梯队")).toBeInTheDocument();
    expect(screen.getByText("最高板")).toBeInTheDocument();
    expect(screen.getByText(/1.41%/)).toBeInTheDocument();
    expect(screen.getByText("正常")).toBeInTheDocument();
    expect(screen.getByText("4 板")).toBeInTheDocument();
  });

  it("③ 建仓节点显示前 3-5 只候选 + 评分", () => {
    renderPipeline();
    expect(screen.getByText(/001358/)).toBeInTheDocument();
    expect(screen.getByText(/兴欣新材/)).toBeInTheDocument();
    expect(screen.getByText(/002567/)).toBeInTheDocument();
    expect(screen.getByText(/唐人神/)).toBeInTheDocument();
    expect(screen.getByText("63.4")).toBeInTheDocument();
  });

  it("§44 诚实标注渲染（HonestyBanner + note 脚注）", () => {
    renderPipeline();
    expect(screen.getByTestId("honesty-banner")).toBeInTheDocument();
    expect(screen.getByText(/9维度评分§44未validated仅参考/)).toBeInTheDocument();
  });

  it("数据为 null 时不崩（占位态）", () => {
    renderPipeline(null);
    // 涨停股池节点占位 "—"
    const nodes = screen.getAllByText("—");
    expect(nodes.length).toBeGreaterThan(0);
  });

  it("isLoading 时显示加载态", () => {
    renderPipeline(null, true);
    expect(screen.getByText("加载中…")).toBeInTheDocument();
  });

  it("飞书通知状态栏渲染", () => {
    renderPipeline();
    expect(screen.getByText("飞书通知状态")).toBeInTheDocument();
    expect(screen.getByText("确认变化")).toBeInTheDocument();
    expect(screen.getByText("建仓提醒")).toBeInTheDocument();
    expect(screen.getByText("卖出提醒")).toBeInTheDocument();
    expect(screen.getByText("暴风雨预警")).toBeInTheDocument();
  });
});
