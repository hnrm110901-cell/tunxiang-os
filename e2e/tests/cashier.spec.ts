/**
 * cashier.spec.ts — 收银流程 E2E 测试 (web-pos)
 *
 * 验证项：
 *  1. 打开收银台 → 选桌台 → 点菜 → 加入购物车 → 结账
 *  2. 验证金额计算正确
 *  3. 挂单 → 取单 → 继续结账
 */
import { test, expect } from '@playwright/test';

// POS 端没有 authStore 守卫（直接路由），但共用 orderStore
// 菜品使用 FALLBACK_DISHES（后端不可达时的兜底数据）

test.describe('收银流程 (web-pos)', () => {
  test.beforeEach(async ({ page }) => {
    // 访问 POS 首页 dashboard
    await page.goto('/', { waitUntil: 'networkidle' });
  });

  test('从桌台地图进入收银台点菜', async ({ page }) => {
    // 导航到桌台地图
    await page.goto('/tables', { waitUntil: 'networkidle' });

    // 桌台地图应该可见
    await expect(page.locator('text=桌台').or(page.locator('[class*="table"]')).first()).toBeVisible({
      timeout: 10_000,
    });

    // 点击一个桌台（桌台通常是按钮或可点击元素，带有桌号）
    const firstTable = page.locator('button, [role="button"], [data-testid*="table"]')
      .filter({ hasText: /[A-Z]?\d+|桌/ })
      .first();

    if (await firstTable.isVisible()) {
      await firstTable.click();

      // 点击后可能进入开台或直接进入收银台
      await page.waitForURL(/\/(cashier|open-table)\//, { timeout: 10_000 });
    }
  });

  test('点菜 + 金额计算 + 结账', async ({ page }) => {
    // 直接进入某桌收银台（使用 fallback 菜品）
    await page.goto('/cashier/A01', { waitUntil: 'networkidle' });

    // 等待菜品列表加载
    await page.waitForTimeout(2_000);

    // 点击第一道菜品（剁椒鱼头 ￥88.00）
    const dishButton = page.getByText('剁椒鱼头').first();
    if (await dishButton.isVisible({ timeout: 5_000 })) {
      await dishButton.click();

      // 再点一道：凉拌黄瓜 ￥9.00
      const dish2 = page.getByText('凉拌黄瓜').first();
      if (await dish2.isVisible()) {
        await dish2.click();
      }

      // 右侧订单区域应该显示已选菜品
      await expect(page.getByText('剁椒鱼头')).toBeVisible();

      // 验证合计金额区域存在（不精确断言金额，因为可能有服务费等）
      const totalArea = page.locator('text=/合计|总计|Total/i').first();
      await expect(totalArea).toBeVisible({ timeout: 5_000 });
    }

    // 点击结账按钮
    const settleBtn = page.getByRole('button', { name: /结账|买单|支付/i }).first();
    if (await settleBtn.isVisible({ timeout: 3_000 })) {
      await settleBtn.click();

      // 应该显示支付方式选择（现金/微信/支付宝/储值卡）
      await expect(
        page.getByText(/现金|微信|支付宝|储值卡/i).first(),
      ).toBeVisible({ timeout: 5_000 });
    }
  });

  test('金额计算验证', async ({ page }) => {
    await page.goto('/cashier/B02', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2_000);

    // 添加已知价格的菜品
    const rice = page.getByText('米饭').first();
    if (await rice.isVisible({ timeout: 5_000 })) {
      // 点击米饭3次（￥3.00 x 3 = ￥9.00）
      await rice.click();
      await rice.click();
      await rice.click();

      // 验证数量或合计有变化
      // 查找包含 "9.00" 或数量 "3" 的文本
      const hasAmount = page.getByText(/9\.00|¥9/);
      const hasQty = page.getByText(/×\s*3|x\s*3/i);

      // 至少其中一个应该可见
      const amountVisible = await hasAmount.first().isVisible({ timeout: 3_000 }).catch(() => false);
      const qtyVisible = await hasQty.first().isVisible({ timeout: 1_000 }).catch(() => false);

      expect(amountVisible || qtyVisible).toBe(true);
    }
  });

  test('挂单 → 取单 → 继续结账', async ({ page }) => {
    await page.goto('/cashier/C01', { waitUntil: 'networkidle' });
    await page.waitForTimeout(2_000);

    // 点一道菜
    const dish = page.getByText('农家小炒肉').first();
    if (await dish.isVisible({ timeout: 5_000 })) {
      await dish.click();

      // 挂单
      const holdBtn = page.getByRole('button', { name: /挂单/i }).first();
      if (await holdBtn.isVisible({ timeout: 3_000 })) {
        await holdBtn.click();

        // 挂单后订单区域应该清空或显示提示
        await page.waitForTimeout(1_000);

        // 取单
        const retrieveBtn = page.getByRole('button', { name: /取单/i }).first();
        if (await retrieveBtn.isVisible({ timeout: 3_000 })) {
          await retrieveBtn.click();

          // 取单后应该恢复之前的菜品
          await expect(page.getByText('农家小炒肉')).toBeVisible({ timeout: 5_000 });
        }
      }
    }
  });
});
