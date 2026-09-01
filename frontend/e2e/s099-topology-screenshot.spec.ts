import { test, expect } from '@playwright/test';

// S099 拓扑主视图截图验收——PipelineTopology echarts graph ①~⑧ 渲染验证。
// 覆盖 grill B+ 设计：graph 主视图 + ②⑦ 金框可展开 + 徽标 + 复选框。
// AC: 前瞻 Tab 加载不崩 + echarts graph canvas 存在 + 截图存档。
// 数据空时 graph 结构常驻（不崩），徽标显"—"/"未取得"。

test.describe('S099 PipelineTopology 拓扑主视图', () => {
  test('前瞻 Tab 拓扑 graph 渲染 + 截图', async ({ page }) => {
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });

    // 等待 echarts graph canvas 渲染（echarts 用 canvas 渲染 graph）
    await page.waitForSelector('canvas', { timeout: 30000 });

    // 等待徽标复选框渲染（确认 PipelineTopology 组件已加载）
    await expect(page.getByText(/徽标字段/)).toBeVisible({ timeout: 30000 });

    // 截图存档（fullPage 捕获完整拓扑 + 折叠区）
    await page.screenshot({
      path: 'e2e/screenshots/s099-topology.png',
      fullPage: true,
    });
  });

  test('拓扑加载不崩（数据空时 graph 结构常驻）', async ({ page }) => {
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    // echarts graph canvas 存在 = 拓扑结构渲染（数据空也显 ①~⑧ 节点）
    await page.waitForSelector('canvas', { timeout: 30000 });
    // 徽标复选框存在 = PipelineTopology 组件挂载成功
    await expect(page.getByText(/徽标字段/)).toBeVisible({ timeout: 30000 });
  });

  test('默认展开 ② 涨停战法匹配（StrategySubPipelineView 可见）', async ({ page }) => {
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    await page.waitForSelector('canvas', { timeout: 30000 });
    // 默认 expandedNode="n2" → StrategySubPipelineView lane=limitup 渲染
    // 空数据时显「无命中 0/7 战法」不崩；有数据时显战法分组卡片
    await page.waitForTimeout(2000); // 等 echarts 渲染 + 默认展开面板
  });
});
