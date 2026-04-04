/**
 * E2E Test Fixtures — 登录 / 导航 / 截图 工具
 *
 * 使用方法：
 *   import { test, expect } from './fixtures';
 *   test('xxx', async ({ adminPage }) => { ... });
 */
import { test as base, expect, type Page } from '@playwright/test';

// ─── Mock 用户数据（与 authStore Mock 降级对齐） ───

const MOCK_USER = {
  user_id: 'mock-001',
  username: 'admin',
  display_name: 'admin',
  tenant_id: 'demo-tenant',
  role: 'admin',
  permissions: ['*'],
};

const MOCK_TOKEN = 'mock-jwt-token';

// ─── 工具函数 ───

/**
 * 向 localStorage 注入认证信息，模拟已登录状态。
 * 必须在 page.goto 之前调用（需要先访问一次 origin 才能写 localStorage）。
 */
async function injectAuth(page: Page, baseURL: string): Promise<void> {
  // 先访问 origin 让浏览器为该 domain 创建 localStorage context
  await page.goto(baseURL, { waitUntil: 'domcontentloaded' });

  await page.evaluate(
    ({ token, user }) => {
      localStorage.setItem('tx_token', token);
      localStorage.setItem('tx_user', JSON.stringify(user));
      localStorage.setItem('tx_tenant_id', user.tenant_id);
    },
    { token: MOCK_TOKEN, user: MOCK_USER },
  );
}

/**
 * 清除 localStorage 认证信息
 */
async function clearAuth(page: Page): Promise<void> {
  await page.evaluate(() => {
    localStorage.removeItem('tx_token');
    localStorage.removeItem('tx_user');
    localStorage.removeItem('tx_tenant_id');
  });
}

// ─── Fixtures 定义 ───

interface E2EFixtures {
  /** 已登录的 web-admin 页面 */
  adminPage: Page;
  /** 未登录的页面（用于测试登录流程） */
  unauthPage: Page;
}

export const test = base.extend<E2EFixtures>({
  adminPage: async ({ page, baseURL }, use) => {
    await injectAuth(page, baseURL ?? 'http://localhost:5173');
    // 刷新以让 authStore.restore() 读取注入的 token
    await page.goto(baseURL ?? 'http://localhost:5173', { waitUntil: 'networkidle' });
    await use(page);
  },

  unauthPage: async ({ page, baseURL }, use) => {
    // 确保 localStorage 干净
    await page.goto(baseURL ?? 'http://localhost:5173', { waitUntil: 'domcontentloaded' });
    await clearAuth(page);
    await page.reload({ waitUntil: 'networkidle' });
    await use(page);
  },
});

export { expect };

// ─── 导航辅助 ───

/**
 * 通过 IconRail 点击一级模块导航
 */
export async function clickModule(page: Page, label: string): Promise<void> {
  await page.locator(`button[title="${label}"]`).click();
}

/**
 * 等待页面主内容区域渲染完成
 */
export async function waitForMainContent(page: Page): Promise<void> {
  await page.locator('main').waitFor({ state: 'visible', timeout: 10_000 });
}

/**
 * 对当前视口截图并附加到测试报告
 */
export async function takeScreenshot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `test-results/screenshots/${name}.png`, fullPage: false });
}
