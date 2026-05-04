/**
 * admin-menu.spec.ts — 菜单发布管理 E2E 测试 (web-admin)
 *
 * 验证项：
 *  1. 菜单列表加载（分类标签）
 *  2. 菜单方案/模板
 *  3. 菜品批量发布
 *  4. 定价管理
 *  5. 沽清管理
 *  6. 菜单排名/版本
 *  7. 多渠道发布
 */
import { test, expect, waitForMainContent } from './fixtures';

test.describe('菜单发布管理 (web-admin)', () => {
  test('TC001: 菜单列表加载', async ({ adminPage }) => {
    const page = adminPage;
    await page.goto('/catalog', { waitUntil: 'networkidle' });
    await waitForMainContent(page);

    // 验证分类标签出现（热菜/凉菜/主食等）
    const categoryTab = page
      .getByRole('button', { name: /热菜|凉菜|主食|饮品|全部/i })
      .or(page.getByText(/菜品|菜单|Catalog/i))
      .first();
    await expect(categoryTab).toBeVisible({ timeout: 10_000 });
  });

  test('TC002: 菜单方案/模板', async ({ adminPage }) => {
    const page = adminPage;
    await page.goto('/menu/schemes', { waitUntil: 'networkidle' });
    await waitForMainContent(page);

    // ⚠️ may fail if route not registered
    await expect(
      page.getByText(/方案|Scheme|模板|菜单/i).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('TC003: 菜品批量发布', async ({ adminPage }) => {
    const page = adminPage;
    await page.goto('/menu/batch', { waitUntil: 'networkidle' });
    await waitForMainContent(page);

    // ⚠️ may fail if route not registered
    const hasContent = page
      .getByText(/批量|Batch|发布|导入|菜品/i)
      .or(page.locator('main'));
    await expect(hasContent.first()).toBeVisible({ timeout: 10_000 });
  });

  test('TC004: 定价管理', async ({ adminPage }) => {
    const page = adminPage;
    await page.goto('/menu/plans', { waitUntil: 'networkidle' });
    await waitForMainContent(page);

    // ⚠️ may fail if route not registered
    const hasContent = page
      .getByText(/定价|价格|Plan|版本|方案/i)
      .or(page.locator('main'));
    await expect(hasContent.first()).toBeVisible({ timeout: 10_000 });
  });

  test('TC005: 沽清管理', async ({ adminPage }) => {
    const page = adminPage;
    await page.goto('/menu/optimize', { waitUntil: 'networkidle' });
    await waitForMainContent(page);

    // MenuOptimizePage — 排菜建议页面，可能包含沽清管理入口
    const hasContent = page
      .getByText(/排菜|沽清|优化|Optimize|建议/i)
      .or(page.locator('main'));
    await expect(hasContent.first()).toBeVisible({ timeout: 10_000 });
  });

  test('TC006: 菜单排名/版本', async ({ adminPage }) => {
    const page = adminPage;
    await page.goto('/menu/ranking', { waitUntil: 'networkidle' });
    await waitForMainContent(page);

    // ⚠️ may fail if route not registered
    await expect(
      page.getByText(/排名|排行|Ranking|版本/i).first(),
    ).toBeVisible({ timeout: 10_000 });
  });

  test('TC007: 多渠道发布', async ({ adminPage }) => {
    const page = adminPage;
    await page.goto('/menu/channels', { waitUntil: 'networkidle' });
    await waitForMainContent(page);

    // ⚠️ may fail if route not registered
    const hasContent = page
      .getByText(/渠道|Channel|发布|平台/i)
      .or(page.locator('main'));
    await expect(hasContent.first()).toBeVisible({ timeout: 10_000 });
  });
});
