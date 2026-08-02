import { test, expect } from '@playwright/test';

test('backend /api/health 连通', async ({ request }) => {
  const res = await request.get('http://127.0.0.1:8900/api/health');
  expect(res.ok()).toBeTruthy();
  const body = await res.json();
  expect(body.ok).toBe(true);
  expect(body.service).toBe('vibe-research-api');
});

test('/daily-review 渲染并落位真实数据', async ({ page }) => {
  await page.goto('/daily-review');
  await expect(page.getByRole('heading', { name: /日度复盘|每日复盘|Daily Review/i })).toBeVisible({ timeout: 30000 });
  const rows = page.locator('table tbody tr');
  if ((await rows.count()) > 0) {
    await expect(rows.first()).toBeVisible();
  }
});

test('导航栏入口可用', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/daily-review/);
  const nav = page.locator('nav, aside, header');
  await expect(nav.first()).toBeVisible({ timeout: 30000 });
});
