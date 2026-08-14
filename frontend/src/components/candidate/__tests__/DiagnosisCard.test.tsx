// S057：DiagnosisCard 八项标准三态判定 + 封顶标记前端测试
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { DiagnosisCard } from "@/lib/candidates";
import { DiagnosisCardView } from "@/components/candidate/DiagnosisCard";

const baseCard = {
  code: "000001", name: "测试股", as_of: "2026-08-11",
  indicators: { missing: {}, announcements: [], concepts: [] },
  activity: { tier: "活跃", rules_applied: [] },
  stabilization: { evidence: {} },
  risk_flags: [],
} as unknown as DiagnosisCard;

describe("DiagnosisCard 八项标准 (S057)", () => {
  it("八项标准三态渲染：通过/未过/缺失（—）", () => {
    const card = {
      ...baseCard,
      eight_standards: {
        items: [
          { key: "1", label: "流通市值 30-150 亿", status: "pass", actual: "80.00亿", expected: "30-150亿" },
          { key: "2", label: "换手 5-20%", status: "fail", actual: "3%", expected: "5-20%" },
          { key: "3", label: "量比≥1.5", status: "missing", actual: null, expected: "≥1.5", note: "量比未取得" },
        ],
        fail_count: 1,
        missing_count: 1,
      },
    } as unknown as DiagnosisCard;
    render(<MemoryRouter><DiagnosisCardView card={card} /></MemoryRouter>);
    expect(screen.getByText("八项标准：")).toBeInTheDocument();
    expect(screen.getByText(/80.00亿/)).toBeInTheDocument();
    // 通过 + 未过态正确渲染
    const passItem = screen.getByText("流通市值 30-150 亿").parentElement;
    expect(passItem?.querySelector(".text-emerald-600")).toBeTruthy();
    const failItem = screen.getByText("换手 5-20%").parentElement;
    expect(failItem?.querySelector(".text-red-600")).toBeTruthy();
    // missing 显「—」不显假值
    const missingItem = screen.getByText("量比≥1.5").parentElement;
    expect(missingItem?.textContent).toContain("—");
  });

  it("封顶标记：未过≥3 → 显示「封顶 55（3 项未过）」", () => {
    const card = {
      ...baseCard,
      eight_standards: {
        items: [
          { key: "1", label: "流通市值 30-150 亿", status: "fail", actual: "20亿", expected: "30-150亿" },
          { key: "2", label: "换手 5-20%", status: "fail", actual: "3%", expected: "5-20%" },
          { key: "3", label: "量比≥1.5", status: "fail", actual: "1.0", expected: "≥1.5" },
        ],
        fail_count: 3,
        missing_count: 0,
      },
      capped: true,
      cap_reason: "八项标准未过3项，得分封顶55",
    } as unknown as DiagnosisCard;
    render(<MemoryRouter><DiagnosisCardView card={card} /></MemoryRouter>);
    expect(screen.getByText(/封顶标记：/)).toBeInTheDocument();
    expect(screen.getByText(/得分封顶55/)).toBeInTheDocument();
  });

  it("未过<3 → 不显示封顶标记", () => {
    const card = {
      ...baseCard,
      eight_standards: {
        items: [
          { key: "1", label: "流通市值 30-150 亿", status: "fail", actual: "20亿", expected: "30-150亿" },
          { key: "2", label: "换手 5-20%", status: "pass", actual: "10%", expected: "5-20%" },
        ],
        fail_count: 1,
        missing_count: 0,
      },
      capped: false,
      cap_reason: null,
    } as unknown as DiagnosisCard;
    render(<MemoryRouter><DiagnosisCardView card={card} /></MemoryRouter>);
    expect(screen.queryByText(/封顶标记/)).not.toBeInTheDocument();
  });

  it("无 eight_standards → 不渲染八项标准区", () => {
    render(<MemoryRouter><DiagnosisCardView card={baseCard} /></MemoryRouter>);
    expect(screen.queryByText("八项标准：")).not.toBeInTheDocument();
  });
});
