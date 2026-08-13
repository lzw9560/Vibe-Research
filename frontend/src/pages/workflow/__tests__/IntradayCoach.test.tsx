// S064 AC：盯盘教练页骨架渲染 + 模式选择 + 空态测试。
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const qMocks = vi.hoisted(() => ({
  useCoachStatus: vi.fn(),
  useCoachTimetable: vi.fn(),
  useCoachAttentionMode: vi.fn(),
  useSetCoachAttentionMode: vi.fn(),
}));

vi.mock("@/lib/query", () => ({
  useCoachStatus: qMocks.useCoachStatus,
  useCoachTimetable: qMocks.useCoachTimetable,
  useCoachAttentionMode: qMocks.useCoachAttentionMode,
  useSetCoachAttentionMode: qMocks.useSetCoachAttentionMode,
}));

import IntradayCoach from "@/pages/workflow/IntradayCoach";

const SLOTS = [
  { slot_id: "fake_auction", label: "假竞价", start: "09:15", end: "09:20", watch: "只看不动", judge: "挂单可撤", teaching: "别被虚假高开骗", mode_note: { A: "a", B: "b", C: "c" } },
  { slot_id: "auction_confirm", label: "竞价确认", start: "09:25", end: "09:30", watch: "对照区间", judge: "达标才算", teaching: "全天第一个决策点", mode_note: { A: "a", B: "b", C: "c" } },
];

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/workflow/coach"]}>
      <IntradayCoach />
    </MemoryRouter>,
  );
}

describe("IntradayCoach (S064)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    qMocks.useCoachStatus.mockReturnValue({ data: null, isLoading: false, refetch: vi.fn() });
    qMocks.useCoachTimetable.mockReturnValue({ data: null, isLoading: false, refetch: vi.fn() });
    qMocks.useCoachAttentionMode.mockReturnValue({ data: null, isLoading: false, refetch: vi.fn() });
    qMocks.useSetCoachAttentionMode.mockReturnValue({ mutate: vi.fn() });
  });

  it("AC：页面标题与四区块渲染", () => {
    renderPage();
    expect(screen.getByText("盯盘教练")).toBeInTheDocument();
    expect(screen.getByText("关注模式")).toBeInTheDocument();
    expect(screen.getByText("时刻表")).toBeInTheDocument();
    expect(screen.getByText("候选条件状态")).toBeInTheDocument();
  });

  it("AC：时刻表渲染槽位 + 当前高亮", () => {
    qMocks.useCoachTimetable.mockReturnValue({
      data: { slots: SLOTS, current_slot_id: "auction_confirm", current_time: "09:25", status: "active" },
      isLoading: false, refetch: vi.fn(),
    });
    qMocks.useCoachStatus.mockReturnValue({
      data: { date: "2026-08-13", current_time: "09:25", current_slot: SLOTS[1], slot_status: "active", attention_mode: "A", mode_rules: { label: "全程", desc: "完整" }, checklist: [], is_trading_day: true },
      isLoading: false, refetch: vi.fn(),
    });
    renderPage();
    expect(screen.getByText("假竞价")).toBeInTheDocument();
    // 竞价确认 出现在时刻表 + 教学点两处，用 getAllByText
    expect(screen.getAllByText("竞价确认").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("当前")).toBeInTheDocument();
  });

  it("AC：空候选清单显示 EmptyState", () => {
    qMocks.useCoachStatus.mockReturnValue({
      data: { date: "2026-08-13", current_time: "09:25", current_slot: null, slot_status: "active", attention_mode: "A", mode_rules: { label: "全程", desc: "完整" }, checklist: [], is_trading_day: true },
      isLoading: false, refetch: vi.fn(),
    });
    renderPage();
    expect(screen.getByText("暂无候选/持仓")).toBeInTheDocument();
  });

  it("AC：checklist 渲染逐只卡片", () => {
    qMocks.useCoachStatus.mockReturnValue({
      data: {
        date: "2026-08-13", current_time: "09:25", current_slot: null, slot_status: "active",
        attention_mode: "A", mode_rules: { label: "全程", desc: "完整" },
        checklist: [{
          code: "600001", name: "测试股", status: "holding", strategy: "first_plate",
          strategy_name: "首板挖掘", entry_condition: "首次涨停", stop_loss_condition: "破线",
          matched_triggers: ["竞价异动"], seal_amount: 50000000, bomb_alerts: [],
          data_status: "ok", max_hold_warning: null, attention_mode: "A",
        }],
        is_trading_day: true,
      },
      isLoading: false, refetch: vi.fn(),
    });
    renderPage();
    expect(screen.getByText("600001")).toBeInTheDocument();
    expect(screen.getByText("竞价异动")).toBeInTheDocument();
    expect(screen.getByText(/5000 万/)).toBeInTheDocument();
  });

  it("AC：attention_mode 三选项 + 切换调 mutate", () => {
    const mutate = vi.fn();
    qMocks.useSetCoachAttentionMode.mockReturnValue({ mutate });
    qMocks.useCoachAttentionMode.mockReturnValue({
      data: { date: "2026-08-13", attention_mode: "A", rules: { label: "全程", desc: "完整推送" } },
      isLoading: false, refetch: vi.fn(),
    });
    renderPage();
    expect(screen.getByText("A 全程")).toBeInTheDocument();
    expect(screen.getByText("B 关键节点")).toBeInTheDocument();
    expect(screen.getByText("C 缺席")).toBeInTheDocument();
    // 点击 C 切换
    fireEvent.click(screen.getByText("C 缺席"));
    expect(mutate).toHaveBeenCalledWith("C");
  });

  it("AC：C 档显示四条铁律", () => {
    qMocks.useCoachAttentionMode.mockReturnValue({
      data: { date: "2026-08-13", attention_mode: "C", rules: { label: "完全缺席", desc: "四条铁律：① 禁开新仓 ② 止损前置 ③ max_hold_days ④ 收盘复盘" } },
      isLoading: false, refetch: vi.fn(),
    });
    renderPage();
    expect(screen.getByText("C 档四条铁律")).toBeInTheDocument();
    // 禁开新仓 出现在 mode rules desc + C 档铁律两处，用 getAllByText
    expect(screen.getAllByText(/禁开新仓/).length).toBeGreaterThanOrEqual(1);
  });
});
