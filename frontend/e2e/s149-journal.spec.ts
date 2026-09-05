import { test, expect } from '@playwright/test';

// S149 P3-T6b：交易日志页 add→list→delete 全流程 e2e。
// 注：需 frontend (:5899) + backend (:8900) 运行。add 写入 VR_DATA_DIR/journal/trades.json，
// 用测试 code + 末尾 delete 清理（不污染用户真实账本）。
// 组件逻辑（表单校验/列表渲染）由 vitest 覆盖；此处冒烟路由 + 端到端 CRUD 契约。

const TEST_CODE = '600599';  // 测试代码（避免与真实持仓冲突；末尾清理）

test('S149 /journal 加载 + 记录→列表→删除 全流程', async ({ page }) => {
  await page.goto('/journal');
  // 页面加载
  await expect(page.getByText('交易日志').first()).toBeVisible({ timeout: 30000 });

  // ① 记录一笔：填表 + 点"记录"
  await page.fill('input[placeholder="代码 6 位"]', TEST_CODE);
  await page.fill('input[placeholder="名称"]', '测试交易-e2e');
  await page.fill('input[placeholder*="买入价"]', '10');
  await page.fill('input[placeholder*="买入股数"]', '100');
  await page.fill('input[placeholder*="计划止损价"]', '9');
  await page.getByRole('button', { name: '记录' }).click();

  // ② 列表出现该笔
  await expect(page.getByText(TEST_CODE).first()).toBeVisible({ timeout: 10000 });

  // ③ 删除（末尾清理——不污染真实账本）
  const row = page.locator('text=' + TEST_CODE).first().locator('xpath=ancestor::div[contains(@class,"flex items-center justify-between")]');
  await row.locator('button').last().click();

  // ④ 该笔消失
  await expect(page.getByText(TEST_CODE)).toHaveCount(0, { timeout: 10000 });
});
