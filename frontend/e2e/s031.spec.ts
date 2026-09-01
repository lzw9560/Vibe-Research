import { test, expect } from '@playwright/test';

// S031 T29：盘前简报路由冒烟——加载 →（有数据时）战法反筛 → 候选直链渲染。
// 注：战法反筛/抽屉需 qualified!=0 日数据；recent 日 qualified≈0 时 L2/L3 空（B12 设计，
// 用户自行切日）。反筛/抽屉的组件逻辑由 vitest 覆盖（StrategyFilter/Sheet/
// CandidateDetailPanel）；此处只冒烟路由不白屏 + 直链渲染。
test('S031 /workflow/pre-market 加载 + 候选直链渲染', async ({ page }) => {
  // ① 盘前简报加载
  await page.goto('/workflow/pre-market');
  // S140 T3：/workflow/pre-market → 重定向 /workflow?view=today → PreMarketBriefing（盯盘执行台）。
  // S093 起 title 从「盘前简报」改「盯盘执行台」，此期望随 S140 路由重定向一并更新。
  await expect(page.getByText('盯盘执行台').first()).toBeVisible({ timeout: 60000 });
  // S140: 去掉 waitForLoadState('networkidle')——react-query SPA 后台 refetch 永不静默，
  // networkidle 对此类页出名 flaky；getByText 已确认渲染，后续 chipsAll 有 guarded isVisible 兜底。

  // ② 若因子漏斗已渲染且 L2 有战法 chips，点"全部"（恢复）冒烟反筛交互
  const chipsAll = page.getByRole('button', { name: '全部' });
  if (await chipsAll.first().isVisible({ timeout: 5000 }).catch(() => false)) {
    await chipsAll.first().click();
  }

  // ③ 候选直链 /workflow/candidates/:code 渲染（CandidateDetailPanel，路由页保留）
  await page.goto('/workflow/candidates/000001');
  await expect(page).toHaveURL(/\/workflow\/candidates\/000001/);
  await page.waitForLoadState('networkidle');
  await expect(page.locator('body')).not.toBeEmpty();
});
