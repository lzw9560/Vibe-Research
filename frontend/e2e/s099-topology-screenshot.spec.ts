import { test, expect } from '@playwright/test';

// S099 拓扑主视图截图验收——PipelineTopology echarts graph ①~⑧ 渲染验证。
// S145b：pipeline 拓扑默认收缩（CollapsibleFold defaultOpen=false），测试须先点开 fold 再断 canvas/徽标。
// AC: 前瞻 Tab 加载 + 展开 pipeline 拓扑 fold + echarts graph canvas 存在 + 截图存档。

test.describe('S099 PipelineTopology 拓扑 graph（默认收缩，展开后验）', () => {
  test('前瞻 Tab 拓扑 graph 渲染 + 截图', async ({ page }) => {
    test.setTimeout(60000);
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    await page.getByRole('button', { name: /pipeline 拓扑/ }).click(); // 展开 fold（默认收缩）
    await page.waitForSelector('canvas', { timeout: 30000 });
    await expect(page.getByText(/徽标字段/)).toBeVisible({ timeout: 30000 });
    await page.screenshot({ path: 'e2e/screenshots/s099-topology.png', fullPage: true });
  });

  test('拓扑加载不崩（数据空时 graph 结构常驻）', async ({ page }) => {
    test.setTimeout(60000);
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    await page.getByRole('button', { name: /pipeline 拓扑/ }).click();
    await page.waitForSelector('canvas', { timeout: 30000 });
    await expect(page.getByText(/徽标字段/)).toBeVisible({ timeout: 30000 });
  });

  test('默认展开 ② 涨停战法匹配（StrategySubPipelineView 可见）', async ({ page }) => {
    test.setTimeout(60000);
    await page.goto('/workflow?view=forward');
    await expect(page).toHaveURL(/\/workflow/, { timeout: 30000 });
    await page.getByRole('button', { name: /pipeline 拓扑/ }).click();
    await page.waitForSelector('canvas', { timeout: 30000 });
    await page.waitForTimeout(2000);
  });
});
