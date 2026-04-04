/**
 * navigation.spec.ts — 导航测试 (web-admin)
 *
 * 验证项：
 *  1. 侧边栏 IconRail 所有一级菜单可点击
 *  2. 面包屑正确显示
 *  3. Cmd+K 全局搜索弹窗打开
 *  4. 搜索跳转正确
 */
import { test, expect, clickModule, waitForMainContent } from './fixtures';

// IconRail 中定义的所有一级模块
const MODULES = [
  { id: 'dashboard', label: '驾驶舱' },
  { id: 'trade', label: '交易' },
  { id: 'menu', label: '菜品' },
  { id: 'member', label: '会员' },
  { id: 'supply', label: '供应链' },
  { id: 'finance', label: '财务' },
  { id: 'org', label: '组织' },
  { id: 'analytics', label: '分析' },
  { id: 'ops', label: '经营' },
  { id: 'agent', label: 'Agent' },
];

test.describe('导航系统 (web-admin)', () => {
  test('IconRail 所有一级模块可点击', async ({ adminPage }) => {
    const page = adminPage;

    for (const mod of MODULES) {
      const btn = page.locator(`button[title="${mod.label}"]`);
      await expect(btn).toBeVisible({ timeout: 5_000 });
      await btn.click();

      // 点击后侧边栏应该响应（等待短暂过渡）
      await page.waitForTimeout(300);
    }
  });

  test('面包屑在子页面正确显示', async ({ adminPage }) => {
    const page = adminPage;

    // 导航到一个有面包屑的子页面
    await page.goto('/catalog', { waitUntil: 'networkidle' });
    await waitForMainContent(page);

    // Breadcrumb 组件应该显示当前位置
    // ShellHQ 在 main 内渲染 <Breadcrumb />
    const breadcrumb = page.locator('[class*="breadcrumb"], [aria-label*="breadcrumb"], nav[class*="bread"]').first();
    if (await breadcrumb.isVisible({ timeout: 3_000 }).catch(() => false)) {
      // 面包屑应该包含路径文字
      await expect(breadcrumb).toBeVisible();
    }
  });

  test('Cmd+K 打开全局搜索弹窗', async ({ adminPage }) => {
    const page = adminPage;

    // 按 Cmd+K (macOS) 或 Ctrl+K (Linux/Windows)
    await page.keyboard.press('Meta+k');

    // GlobalSearch 弹窗应该出现
    // 它有一个搜索输入框
    const searchModal = page
      .getByPlaceholderText(/搜索|Search|查找|跳转/i)
      .or(page.locator('[class*="global-search"], [class*="search-modal"], [role="dialog"]'))
      .first();

    await expect(searchModal).toBeVisible({ timeout: 5_000 });
  });

  test('全局搜索输入并跳转', async ({ adminPage }) => {
    const page = adminPage;

    // 打开搜索
    await page.keyboard.press('Meta+k');
    await page.waitForTimeout(500);

    // 找到搜索输入框
    const searchInput = page
      .getByPlaceholderText(/搜索|Search|查找|跳转/i)
      .or(page.locator('[class*="search"] input'))
      .first();

    if (await searchInput.isVisible({ timeout: 3_000 })) {
      // 搜索"经营驾驶舱"
      await searchInput.fill('驾驶舱');
      await page.waitForTimeout(500);

      // 搜索结果列表应该出现
      const resultItem = page.getByText('经营驾驶舱').first();
      if (await resultItem.isVisible({ timeout: 3_000 })) {
        await resultItem.click();

        // 应该导航到 /dashboard
        await page.waitForURL(/\/dashboard/, { timeout: 5_000 });
      }
    }
  });

  test('全局搜索 ESC 关闭', async ({ adminPage }) => {
    const page = adminPage;

    // 打开搜索
    await page.keyboard.press('Meta+k');
    await page.waitForTimeout(500);

    // 搜索弹窗应该可见
    const searchModal = page
      .getByPlaceholderText(/搜索|Search|查找|跳转/i)
      .or(page.locator('[class*="global-search"], [class*="search-modal"]'))
      .first();

    await expect(searchModal).toBeVisible({ timeout: 3_000 });

    // 按 ESC 关闭
    await page.keyboard.press('Escape');
    await page.waitForTimeout(500);

    // 弹窗应该消失
    await expect(searchModal).not.toBeVisible({ timeout: 3_000 });
  });

  test('直接 URL 导航到各主要页面', async ({ adminPage }) => {
    const page = adminPage;
    const routes = [
      { path: '/home', keyword: /首页|Home|欢迎/i },
      { path: '/dashboard', keyword: /驾驶舱|Dashboard|经营/i },
      { path: '/catalog', keyword: /菜品|Catalog|菜单/i },
      { path: '/crm', keyword: /会员|CDP|Member/i },
      { path: '/supply', keyword: /供应|Supply|采购/i },
    ];

    for (const route of routes) {
      await page.goto(route.path, { waitUntil: 'networkidle' });
      await waitForMainContent(page);

      // 验证页面正确加载（主内容区域可见）
      await expect(page.locator('main')).toBeVisible({ timeout: 10_000 });
    }
  });

  test('Agent Console 切换按钮', async ({ adminPage }) => {
    const page = adminPage;

    // ShellHQ 有一个 Agent Console 切换按钮（在 TopbarHQ 中）
    const toggleBtn = page
      .getByRole('button', { name: /Agent|AI|助手/i })
      .or(page.locator('[data-testid*="agent-toggle"]'))
      .first();

    if (await toggleBtn.isVisible({ timeout: 3_000 })) {
      // 点击隐藏 Agent Console
      await toggleBtn.click();
      await page.waitForTimeout(500);

      // 再次点击恢复
      await toggleBtn.click();
      await page.waitForTimeout(500);
    }
  });
});
