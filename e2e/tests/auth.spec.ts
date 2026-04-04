/**
 * auth.spec.ts — 登录 / 登出 / 认证守卫 E2E 测试
 *
 * 验证项：
 *  1. 未登录 → 显示登录页
 *  2. 输入用户名密码 → 登录成功 → 跳转首页
 *  3. 无效密码 → 显示错误提示
 *  4. 退出登录 → 返回登录页
 */
import { test, expect } from './fixtures';

test.describe('认证流程 (web-admin)', () => {
  test('未登录状态应显示登录页', async ({ unauthPage }) => {
    const page = unauthPage;

    // LoginPage 渲染时，应该能看到登录表单
    await expect(page.getByPlaceholderText(/用户名|账号/i)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByPlaceholderText(/密码/i)).toBeVisible();
  });

  test('输入凭据登录成功后跳转首页', async ({ unauthPage }) => {
    const page = unauthPage;

    // 填写登录表单（authStore 在后端不可达时会 Mock 降级，任意用户名密码即可）
    await page.getByPlaceholderText(/用户名|账号/i).fill('admin');
    await page.getByPlaceholderText(/密码/i).fill('any-password');

    // 点击登录按钮
    await page.getByRole('button', { name: /登录|登 录|Login/i }).click();

    // 登录成功后应该能看到 ShellHQ 布局（main 区域或侧边栏）
    await expect(page.locator('main')).toBeVisible({ timeout: 15_000 });
  });

  test('无效密码应显示错误提示', async ({ unauthPage, baseURL }) => {
    const page = unauthPage;

    // 拦截 login API 返回 401
    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, error: { message: '用户名或密码错误' } }),
      }),
    );

    await page.getByPlaceholderText(/用户名|账号/i).fill('admin');
    await page.getByPlaceholderText(/密码/i).fill('wrong-password');
    await page.getByRole('button', { name: /登录|登 录|Login/i }).click();

    // 应该显示错误信息
    await expect(page.getByText(/错误|失败|invalid|unauthorized/i)).toBeVisible({ timeout: 5_000 });
  });

  test('退出登录后返回登录页', async ({ adminPage }) => {
    const page = adminPage;

    // ShellHQ 已登录，查找登出按钮（TopbarHQ 中的用户菜单或直接登出按钮）
    // TopbarHQ 有 onLogout 回调，通常在用户头像下拉或直接按钮
    const logoutTrigger =
      page.getByRole('button', { name: /退出|登出|Logout/i }).or(
        page.getByText(/退出登录|注销/i),
      );

    // 如果登出按钮在下拉菜单中，先点击用户头像区域
    const userAvatar = page.locator('[data-testid="user-avatar"]').or(
      page.getByText(/admin|用户/i).first(),
    );
    if (await userAvatar.isVisible()) {
      await userAvatar.click();
    }

    await logoutTrigger.first().click({ timeout: 5_000 });

    // 登出后应该重新看到登录表单
    await expect(page.getByPlaceholderText(/用户名|账号/i)).toBeVisible({ timeout: 10_000 });
  });
});
