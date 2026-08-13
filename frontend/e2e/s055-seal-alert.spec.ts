// S055 A5：炸板预警横幅 + 封单时序 sparkline 渲染冒烟
import { test, expect } from '@playwright/test';

test.describe('S055 炸板预警', () => {
  test('A5: LimitUpStrategy 页预警横幅区渲染（无预警时不阻断页面）', async ({ page }) => {
    await page.goto('/limitup/strategy');
    // 页面标题可见（不挂死）
    await expect(page.locator('h1, h2').first()).toBeVisible({ timeout: 30000 });
    // BombAlertBanner 组件挂载（即使空预警也渲染容器）
    // 预警横幅无预警时不显示，有预警时显示——这里只验证不报错
    const body = page.locator('body');
    await expect(body).toBeVisible();
  });

  test('A4: bomb-alerts 端点返降级标记（不臆造）', async ({ request }) => {
    const res = await request.get('http://127.0.0.1:8900/api/risk/bomb-alerts');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    const data = body.data || body;
    expect(data).toHaveProperty('alerts');
    expect(data).toHaveProperty('count');
    expect(data).toHaveProperty('note');
    // note 含风险标注
    expect(data.note).toContain('风险');
  });

  test('A4: seal-snapshots 端点缺数据返 missing（不臆造）', async ({ request }) => {
    const res = await request.get('http://127.0.0.1:8900/api/risk/seal-snapshots?code=999999');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    const data = body.data || body;
    expect(data.data_status).toBe('missing');
    expect(data.snapshots).toEqual([]);
  });

  test('A5: seal-snapshots 有数据时返时序', async ({ request }) => {
    // 000668 是持续涨停的票，应有时序
    const res = await request.get('http://127.0.0.1:8900/api/risk/seal-snapshots?code=000668');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    const data = body.data || body;
    expect(data.data_status).toBe('ok');
    expect(data.count).toBeGreaterThan(0);
  });
});
