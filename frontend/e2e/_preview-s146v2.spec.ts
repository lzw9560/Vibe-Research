import { test } from '@playwright/test';
test('preview S146v2: 选股 tab 统一流（原始组件全保）', async ({ page }) => {
  await page.goto('/workflow?view=forward');
  await page.waitForTimeout(5000);
  await page.screenshot({ path: '/tmp/preview-s146v2.png', fullPage: true });
});
