import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StrategySubPipelineView } from "../StrategySubPipelineView";
import type { ScoredCandidate, StrategyFunnelSummary } from "@/lib/api";

// S097 D（R12/R13/R15）前端：逐条件漏斗渲染 + 候选三态标记 + 历史快照兼容。

/** 同一 first_plate 战法的漏斗（两候选、两条件、含三态 + data_unavailable）。 */
const funnel: StrategyFunnelSummary = {
  strategy_code: "first_plate",
  strategy_name: "首板挖掘",
  fired_count: 2,
  total_count: 5,
  conditions: [
    {
      condition_id: "first_plate.c1",
      condition_name: "基因得分合格",
      factor: "total_score",
      threshold: ">= 60",
      input_count: 5,
      passed_count: 3,
      data_unavailable_count: 0,
      pass_rate: 0.6,
    },
    {
      condition_id: "first_plate.c2",
      condition_name: "量比≥1.5",
      factor: "vol_ratio",
      threshold: ">= 1.5",
      input_count: 3,
      passed_count: 2,
      data_unavailable_count: 1,
      pass_rate: 0.667,
    },
  ],
  candidates: [
    {
      code: "000001",
      name: "平安银行",
      fired: true,
      conditions: [
        { condition_id: "first_plate.c1", state: "hit" },
        { condition_id: "first_plate.c2", state: "hit" },
      ],
    },
    {
      code: "000002",
      name: "万科A",
      fired: false,
      conditions: [
        { condition_id: "first_plate.c1", state: "miss" },
        { condition_id: "first_plate.c2", state: "data_unavailable" },
      ],
    },
  ],
};

function makeCandidate(code: string, name: string, score: number): ScoredCandidate {
  return {
    code,
    name,
    strategy_code: "first_plate",
    strategy_name: "首板挖掘",
    strategy_score: score,
    strategy_funnel: funnel,
  };
}

const candidatesWithFunnel: ScoredCandidate[] = [
  makeCandidate("000001", "平安银行", 72.5),
  makeCandidate("000002", "万科A", 58.0),
];

describe("StrategySubPipelineView · S097 漏斗渲染", () => {
  it("渲染漏斗摘要：触发率 + 逐条件 input→passed + pass_rate", () => {
    render(
      <StrategySubPipelineView
        scoredCandidates={candidatesWithFunnel}
        lane="limitup"
      />,
    );

    // 触发率 2/5 → 40%
    expect(screen.getByText(/触发率/)).toBeInTheDocument();
    expect(screen.getByText(/2\/5/)).toBeInTheDocument();
    expect(screen.getByText(/40%/)).toBeInTheDocument();

    // 条件 1：基因得分合格 5→3 60%（data_unavailable=0 不显黄条纹）
    expect(screen.getByText("基因得分合格")).toBeInTheDocument();
    expect(screen.getByText(/5→3.*60%/)).toBeInTheDocument();

    // 条件 2：量比≥1.5 3→2 67% + 数据缺失 1（F2：黄条纹段 title 标注）
    expect(screen.getByText("量比≥1.5")).toBeInTheDocument();
    expect(screen.getByText(/3→2.*67%/)).toBeInTheDocument();
    expect(screen.getByTitle("数据缺失 1")).toBeInTheDocument();
  });

  it("候选行渲染三态命中标记（hit ✓ / miss ✗ / data_unavailable —）", () => {
    render(
      <StrategySubPipelineView
        scoredCandidates={candidatesWithFunnel}
        lane="limitup"
      />,
    );

    // 平安银行：c1 hit + c2 hit
    expect(screen.getByTitle("first_plate.c1: hit")).toBeInTheDocument();
    expect(screen.getByTitle("first_plate.c2: hit")).toBeInTheDocument();
    // 万科A：c1 miss + c2 data_unavailable
    expect(screen.getByTitle("first_plate.c1: miss")).toBeInTheDocument();
    expect(screen.getByTitle("first_plate.c2: data_unavailable")).toBeInTheDocument();
  });

  it("无 strategy_funnel（历史快照 R15）不崩且显 score，不渲染漏斗摘要", () => {
    const legacyCandidates: ScoredCandidate[] = [
      { code: "000001", name: "平安银行", strategy_code: "first_plate", strategy_name: "首板挖掘", strategy_score: 72.5 },
      { code: "000002", name: "万科A", strategy_code: "first_plate", strategy_name: "首板挖掘", strategy_score: 58.0 },
    ];

    render(
      <StrategySubPipelineView
        scoredCandidates={legacyCandidates}
        lane="limitup"
      />,
    );

    // 候选名 + 分仍正常显示
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getByText("72.5")).toBeInTheDocument();
    expect(screen.getByText("58.0")).toBeInTheDocument();
    // 漏斗摘要不渲染（无 strategy_funnel → FunnelSummary 返 null）
    expect(screen.queryByText(/触发率/)).not.toBeInTheDocument();
    expect(screen.queryByTitle("first_plate.c1: hit")).not.toBeInTheDocument();
  });

  it("无候选时显空态标题 + 副标题（0 战法命中），不崩", () => {
    render(
      <StrategySubPipelineView scoredCandidates={[]} lane="limitup" />,
    );
    // 空态折叠默认收起，但标题 + 副标题（含"无命中 0/7"）始终可见
    expect(screen.getByText("涨停战法匹配")).toBeInTheDocument();
    expect(screen.getByText(/无命中（0\/7 战法）/)).toBeInTheDocument();
  });
});
