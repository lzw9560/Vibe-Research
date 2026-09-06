// S165 R1/R5: DimensionValidationCard 单测——mock record 渲染 + honest_label + status 5 色码 + edge_type 主标签。
// v2: 5-value enum (not_validated) + edge_type label + IC/lift removed from window table + PBO distinct states + field source map。
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DimensionValidationCard } from "@/components/DimensionValidationCard";
import { dimensionValidationMocks } from "@/lib/__fixtures__/dimension-validation.mock";
import type { DimensionValidationRecord } from "@/lib/verifier-contract";

describe("DimensionValidationCard", () => {
  it("falsified 维度渲染红底 status + honest_label + edge_type 标签 + 防外推 note", () => {
    const geneScore = dimensionValidationMocks.find(
      (d) => d.dimension_id === "gene_score",
    )!;
    render(<DimensionValidationCard record={geneScore} />);

    // honest_label 文案
    expect(
      screen.getByText(/选股层无 validated 维度, edge 待盘中验证/),
    ).toBeInTheDocument();

    // status 标签（证否 = falsified）
    expect(screen.getByText(/证否（劣于随机）/)).toBeInTheDocument();

    // 外推禁令提示
    expect(screen.getByText(/该窗口无 edge ≠ 无 edge/)).toBeInTheDocument();

    // 红底色码 class（falsified → red）
    const statusPill = screen.getByText(/证否（劣于随机）/).closest("span");
    expect(statusPill?.className).toContain("bg-red-500/10");

    // R5: edge_type 主标签旁 status
    expect(screen.getByText("selection")).toBeInTheDocument();

    // R7: selection-falsified 防外推 note
    expect(
      screen.getByText(/selection falsified; population event edge may exist/),
    ).toBeInTheDocument();
  });

  it("not_validated 维度渲染灰底 + 弱信号非欠样本（非 underpowered）", () => {
    const breakout = dimensionValidationMocks.find(
      (d) => d.dimension_id === "breakout",
    )!;
    render(<DimensionValidationCard record={breakout} />);

    // v2: "未validated" → not_validated（非 underpowered——n=43691 不欠样本，是 lift 弱）
    expect(screen.getByText(/弱信号非欠样本/)).toBeInTheDocument();

    const statusPill = screen.getByText(/弱信号非欠样本/).closest("span");
    expect(statusPill?.className).toContain("bg-gray-400/10");

    // 不应出现 underpowered 文案
    expect(screen.queryByText(/待 live 60 天复验/)).not.toBeInTheDocument();
  });

  it("underpowered 渲染黄底 + 待 live 60 天复验", () => {
    // 无 REGISTRY dim 映射到 underpowered（"未validated"→not_validated, "待复验"→underpowered 但无 dim 用"待复验"）
    // 用合成 record 测 underpowered 色码（5-value enum 完整覆盖）
    const synthetic: DimensionValidationRecord = {
      ...dimensionValidationMocks[0],
      dimension_id: "synthetic_underpowered",
      label: "合成 underpowered",
      status: "underpowered",
    };
    render(<DimensionValidationCard record={synthetic} />);

    expect(screen.getByText(/待 live 60 天复验/)).toBeInTheDocument();

    const statusPill = screen.getByText(/待 live 60 天复验/).closest("span");
    expect(statusPill?.className).toContain("bg-amber-500/10");
  });

  it("overfit PBO selection 显 '待建 (not-yet-wired)'，其余待建", () => {
    const pathLift = dimensionValidationMocks.find(
      (d) => d.dimension_id === "path_lift",
    )!;
    render(<DimensionValidationCard record={pathLift} />);

    // R7: PBO for selection → "待建 (not-yet-wired)"
    expect(screen.getByText(/PBO: 待建/)).toBeInTheDocument();
    expect(screen.getByText(/CSCV: 待建/)).toBeInTheDocument();
    expect(screen.getByText(/DSR: 待建/)).toBeInTheDocument();
    expect(screen.getByText(/HAIRCUT: 待建/)).toBeInTheDocument();
    expect(screen.getByText(/MIN_TRL: 待建/)).toBeInTheDocument();
  });

  it("overfit PBO event 显 'N/A (single-strategy)' 区别 '待建'", () => {
    // 合成 event verdict 测 PBO distinct state
    const eventRecord: DimensionValidationRecord = {
      ...dimensionValidationMocks[0],
      dimension_id: "synthetic_event",
      label: "合成 event",
      edge_type: "event",
    };
    render(<DimensionValidationCard record={eventRecord} />);

    expect(screen.getByText(/N\/A \(single-strategy\)/)).toBeInTheDocument();
  });

  it("三窗口对比表渲染 S159 值，无 IC/lift 列", () => {
    const turnover = dimensionValidationMocks.find(
      (d) => d.dimension_id === "turnover",
    )!;
    render(<DimensionValidationCard record={turnover} />);

    // 隔夜 gap 胜率 54.3%
    expect(screen.getByText("54.3%")).toBeInTheDocument();
    // path 胜率 36.3%
    expect(screen.getByText("36.3%")).toBeInTheDocument();

    // v2: IC/lift 列已移除（S159 §5A: mean+中位+胜率+base_rate only）
    expect(screen.queryByText("IC/lift")).not.toBeInTheDocument();
  });

  it("R6 三层 reframe 标签：selection 展示终态", () => {
    const sectorHeat = dimensionValidationMocks.find(
      (d) => d.dimension_id === "sector_heat",
    )!;
    render(<DimensionValidationCard record={sectorHeat} />);

    expect(screen.getByText(/selection层 · 展示终态/)).toBeInTheDocument();
  });

  it("ci_low/ci_high null 显 '待 v2 verifier 跑出'（不臆造）", () => {
    const breakout = dimensionValidationMocks.find(
      (d) => d.dimension_id === "breakout",
    )!;
    render(<DimensionValidationCard record={breakout} />);

    expect(screen.getByText(/待 v2 verifier 跑出/)).toBeInTheDocument();
  });

  it("updated_commit/updated_at null 显 '待回溯 task 填充'", () => {
    const geneScore = dimensionValidationMocks.find(
      (d) => d.dimension_id === "gene_score",
    )!;
    render(<DimensionValidationCard record={geneScore} />);

    const placeholders = screen.getAllByText(/待回溯 task 填充/);
    expect(placeholders).toHaveLength(2); // updated_commit + updated_at
  });
});
