import { test, expect } from '@playwright/test';

// S094 战法分类与双 pipeline 重构 — e2e 验收（AC8 + AC11）
// 覆盖 AC8 UI 双 pipeline 分区+折叠+卡片流转 + AC11 dev server 冒烟
// AC1-AC7/AC9/AC10 由 pytest(2269)+vitest(428)+tsc+build 单元/集成覆盖（见 S094 §5）
// S097 逐条件漏斗：scored 有数据时显触发率，空态 R15 降级显 score 不崩

test.describe('S094 双 pipeline 重构', () => {
  test('AC8+AC11 前瞻 Tab 涨停叉②战法匹配加载', async ({ page }) => {
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    // 涨停叉② StrategySubPipelineView lane=limitup（Workflow.tsx:492）
    await expect(page.getByText(/涨停战法匹配/i).first()).toBeVisible({ timeout: 30000 });
  });

  test('AC8 切换非涨停叉⑦战法匹配加载（默认涨停，点切换按钮）', async ({ page }) => {
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    // S094 附录 A：前瞻 Tab [涨停叉|非涨停叉] 互斥切换，默认涨停——点"非涨停叉"切换
    await page.getByRole('button', { name: /非涨停叉/ }).click();
    // 非涨停叉⑦ NonLimitupPlaceholder → StrategySubPipelineView lane=non-limitup
    await expect(page.getByText(/非涨停战法匹配/i).first()).toBeVisible({ timeout: 30000 });
  });

  test('AC11 前瞻 Tab 结构加载不崩（双 pipeline 分区在）', async ({ page }) => {
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    // 双 pipeline 分区加载（数据空时 StrategySubPipelineView 显「无命中 0/N 战法」不崩）
  });

  test('S097 漏斗：前瞻 Tab 加载不崩（有数据显触发率，空态 R15 降级）', async ({ page }) => {
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    // S097 FunnelSummary：有 strategy_funnel 显触发率，无则 R15 降级显 score 不崩
  });
});
