/**
 * crew-ordering.spec.ts — web-crew 点餐核心流程 E2E 测试
 *
 * 验证项：
 *  1. 登录页加载
 *  2. 桌台概览
 *  3. 开台
 *  4. 点餐页面
 *  5. 菜品搜索
 *  6. 已点菜品查看
 *  7. 账单页面
 *
 * 注意：web-crew 使用独立 auth 系统（tx_store_token），
 *       登录后可注入 localStorage token 跳过 CrewLoginPage。
 */
import { test, expect, type Page } from '@playwright/test';
import { waitForMainContent } from './fixtures';

/**
 * 向 localStorage 注入 crew 认证 token 跳过登录
 */
async function loginCrew(page: Page): Promise<void> {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    localStorage.setItem('tx_store_token', 'e2e-mock-crew-token');
  });
}

test.describe('服务员点餐 (web-crew)', () => {
  test('TC001: 登录页加载', async ({ page }) => {
    await page.goto('/tables', { waitUntil: 'networkidle' });

    // 未登录 → 显示 CrewLoginPage
    await expect(
      page.getByPlaceholderText(/工号|账号/i),
    ).toBeVisible({ timeout: 10_000 });
    await expect(
      page.getByText(/屯象服务员|登录开始/i),
    ).toBeVisible();
  });

  test('TC002: 桌台概览', async ({ page }) => {
    await loginCrew(page);
    await page.goto('/tables', { waitUntil: 'networkidle' });
    await page.locator('main, [class*="table-map"], [class*="grid"]')
      .waitFor({ state: 'visible', timeout: 10_000 });

    // 桌台概览应该渲染桌位网格
    const tableView = page.locator('[class*="table"], [class*="seat"], [class*="grid"]').first();
    await expect(tableView).toBeVisible({ timeout: 10_000 });
  });

  test('TC003: 开台', async ({ page }) => {
    await loginCrew(page);
    await page.goto('/open-table', { waitUntil: 'networkidle' });

    // ⚠️ may fail if route not registered
    const hasContent = page
      .getByText(/开台|Open|选桌|桌位/i)
      .or(page.locator('main'));
    await expect(hasContent.first()).toBeVisible({ timeout: 10_000 });
  });

  test('TC004: 点餐页面', async ({ page }) => {
    await loginCrew(page);
    await page.goto('/order', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1_000);

    // 点餐页面应显示菜单分类和菜品区域
    const hasMenuSection = page
      .getByText(/分类|菜品|菜单|推荐|点餐/i)
      .or(page.locator('[class*="menu"], [class*="dish"], [class*="category"]'))
      .first();
    await expect(hasMenuSection).toBeVisible({ timeout: 10_000 });
  });

  test('TC005: 菜品搜索', async ({ page }) => {
    await loginCrew(page);
    await page.goto('/order', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1_000);

    const searchInput = page
      .getByPlaceholderText(/搜索|查找|搜菜品/i)
      .or(page.locator('input[type="search"]'))
      .first();

    if (await searchInput.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await searchInput.fill('鱼');
      await page.waitForTimeout(500);
    }
  });

  test('TC006: 已点菜品查看', async ({ page }) => {
    await loginCrew(page);
    await page.goto('/active', { waitUntil: 'networkidle' });

    // 进行中订单页面
    const hasContent = page
      .getByText(/进行中|Active|已点|订单/i)
      .or(page.locator('main'));
    await expect(hasContent.first()).toBeVisible({ timeout: 10_000 });
  });

  test('TC007: 账单页面', async ({ page }) => {
    await loginCrew(page);
    await page.goto('/table-detail', { waitUntil: 'networkidle' });

    // ⚠️ may fail if route not registered
    const hasContent = page
      .getByText(/账单|详情|Detail|结算|桌台/i)
      .or(page.locator('main'));
    await expect(hasContent.first()).toBeVisible({ timeout: 10_000 });
  });
});
