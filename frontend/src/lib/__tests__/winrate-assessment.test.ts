// S054 R8：deriveAssessmentTips 派生纯函数单测。
// 从 BehaviorLoop._deriveAssessmentTips 抽取，行为须与原函数一致。
import { describe, it, expect } from "vitest";
import { deriveAssessmentTips } from "@/lib/winrate-assessment";
import type { ShadowComparison } from "@/lib/api/types";

function makeData(overrides: Partial<ShadowComparison> = {}): ShadowComparison {
  return {
    window_days: 28,
    follow: { n: 0, win_rate: null, avg_return: null },
    feeling: { n: 0, win_rate: null, avg_return: null },
    missed: { n: 0, win_rate: null, avg_return: null, missing_kline: 0, approx_note: "" },
    independence: { agreement_rate: null, feeling_win_rate: null },
    no_suggestion_days: 0,
    sufficient: false,
    disclaimer: "",
    ...overrides,
  };
}

describe("deriveAssessmentTips", () => {
  it("follow 显著高于 feeling → 建议多跟系统", () => {
    const data = makeData({
      follow: { n: 10, win_rate: 0.7, avg_return: 2.0 },
      feeling: { n: 10, win_rate: 0.3, avg_return: -1.0 },
      sufficient: true,
    });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("显著高于"))).toBe(true);
    expect(tips.some((t) => t.includes("多跟系统"))).toBe(true);
  });

  it("feeling 反超 follow → 建议倾向自主判断", () => {
    const data = makeData({
      follow: { n: 10, win_rate: 0.2, avg_return: -2.0 },
      feeling: { n: 10, win_rate: 0.6, avg_return: 3.0 },
      sufficient: true,
    });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("反而高于"))).toBe(true);
    expect(tips.some((t) => t.includes("自主判断"))).toBe(true);
  });

  it("follow 与 feeling 接近 → 两者表现相当", () => {
    const data = makeData({
      follow: { n: 10, win_rate: 0.5, avg_return: 1.0 },
      feeling: { n: 10, win_rate: 0.48, avg_return: 0.8 },
      sufficient: true,
    });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("接近"))).toBe(true);
  });

  it("一致率偏高 → 提醒保留独立判断", () => {
    const data = makeData({
      follow: { n: 10, win_rate: 0.5, avg_return: 1.0 },
      feeling: { n: 2, win_rate: 0.5, avg_return: 0.5 },
      independence: { agreement_rate: 0.85, feeling_win_rate: 0.5 },
      sufficient: true,
    });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("偏高"))).toBe(true);
  });

  it("一致率偏低 → 提醒关注 missed 桶", () => {
    const data = makeData({
      follow: { n: 2, win_rate: 0.5, avg_return: 1.0 },
      feeling: { n: 10, win_rate: 0.5, avg_return: 0.5 },
      independence: { agreement_rate: 0.15, feeling_win_rate: 0.5 },
      sufficient: true,
    });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("偏低"))).toBe(true);
  });

  it("missed 影子胜率高 → 建议多采纳候选", () => {
    const data = makeData({
      missed: { n: 10, win_rate: 0.6, avg_return: 1.5, missing_kline: 0, approx_note: "" },
      sufficient: true,
    });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("系统建议质量不错"))).toBe(true);
  });

  it("missed 影子胜率低 → 肯定自主筛选力", () => {
    const data = makeData({
      missed: { n: 10, win_rate: 0.2, avg_return: -1.0, missing_kline: 0, approx_note: "" },
      sufficient: true,
    });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("不跟可能是对的"))).toBe(true);
  });

  it("样本不足 → 压低研判权重", () => {
    const data = makeData({
      follow: { n: 3, win_rate: 0.7, avg_return: 1.0 },
      feeling: { n: 2, win_rate: 0.5, avg_return: 0.5 },
      sufficient: false,
    });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("样本不足"))).toBe(true);
  });

  it("全空 → 兜底提示无数据可研判", () => {
    const data = makeData({ sufficient: false });
    const tips = deriveAssessmentTips(data);
    expect(tips.some((t) => t.includes("暂无行为数据"))).toBe(true);
  });
});
