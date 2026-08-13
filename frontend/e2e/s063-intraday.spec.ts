// S063 AC19：盘中四层布局 + WeatherDecisionBar 渲染冒烟测试。
// 后端已在 :8900 运行（reuseExistingServer），前端 :5899 同。
import { test, expect } from '@playwright/test';

test.describe('S063 盘中辅助决策', () => {
  test('AC12: IntradayMonitor 四层纵向布局渲染', async ({ page }) => {
    await page.goto('/workflow/intraday');
    // PipelineProgressBar 5 节点标题
    await expect(page.getByText('盘中辅助')).toBeVisible({ timeout: 15000 });
    // 四层标题
    await expect(page.getByText('Layer 1 · 情绪走势')).toBeVisible();
    await expect(page.getByText('Layer 2 · 持仓×情绪联动')).toBeVisible();
    await expect(page.getByText('Layer 3 · 条件场景推演')).toBeVisible();
    await expect(page.getByText('Layer 4 · T+1 预判')).toBeVisible();
  });

  test('AC13: Layer 1 走势图渲染（有采样数据时）', async ({ page }) => {
    await page.goto('/workflow/intraday');
    // 走势图：echarts 渲染为 canvas，容器是固定高度 div。用 textcontent 锚定
    // "盘中情绪走势" 标题，然后取其后的 chart 容器。
    const trendTitle = page.getByText('盘中情绪走势');
    await expect(trendTitle).toBeVisible({ timeout: 15000 });
    // echarts canvas 存在性检查（不要求非空数据）
    const canvas = page.locator('canvas').first();
    await expect(canvas).toBeVisible({ timeout: 10000 });
  });

  test('AC17: /sentiment/weather 客户端重定向到 /workflow/intraday', async ({ page }) => {
    await page.goto('/sentiment/weather');
    await expect(page).toHaveURL(/\/workflow\/intraday/, { timeout: 10000 });
  });
});

test.describe('S063 盘前 WeatherDecisionBar', () => {
  test('AC11: PreMarketBriefing 顶部 WeatherDecisionBar 渲染', async ({ page }) => {
    await page.goto('/workflow/pre-market');
    // WeatherDecisionBar 的天气名（晴天/阴天/暴风雨/极端反弹/未取得 之一）
    const weatherNames = ['晴天', '阴天', '暴风雨', '极端反弹', '未取得'];
    const weatherLocator = page.locator('span.text-lg.font-semibold').first();
    await expect(weatherLocator).toBeVisible({ timeout: 30000 });
    const text = (await weatherLocator.textContent()) || '';
    expect(weatherNames.some((w) => text.includes(w))).toBeTruthy();
  });
});
