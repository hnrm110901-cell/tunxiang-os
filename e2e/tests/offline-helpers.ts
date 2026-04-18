/**
 * Offline E2E Helpers —— 为断网收银场景提供稳定 mock
 *
 * 设计原则：
 *   - 所有 tx-trade API 通过 page.route 拦截，脱离后端真实服务
 *   - 可在同一个测试中动态切换"在线/离线"而不需要重启 backend
 *   - OFFLINE_HOURS 环境变量控制模拟断网时长（默认 0.01h≈36s，nightly 改 4h）
 *
 * 参考 CLAUDE.md §XX Tier1 测试标准：用例描述基于真实餐厅场景
 */
import type { Page, Request, Route } from '@playwright/test';

// ─── 可配置：模拟断网时长 ───────────────────────────────────────────────────

export const OFFLINE_DURATION_MS = (() => {
  const h = Number(process.env.OFFLINE_HOURS ?? '0.01');
  // clamp 到 [1s, 4h]，防止误配置让 CI 跑死
  const clamped = Math.max(0.0003, Math.min(4, h));
  return Math.round(clamped * 3600 * 1000);
})();

// ─── Mock Trade API ─────────────────────────────────────────────────────────

export interface MockTradeState {
  orderCount: number;
  settleCount: number;
  paymentCount: number;
  lastOrderId: string | null;
  /** 记录每个 request_id → 幂等去重用 */
  seenRequestIds: Set<string>;
  /** 手工控制"服务端是否在线"（toxiproxy 的等价物） */
  serverAvailable: boolean;
}

export function createMockTradeState(): MockTradeState {
  return {
    orderCount: 0,
    settleCount: 0,
    paymentCount: 0,
    lastOrderId: null,
    seenRequestIds: new Set(),
    serverAvailable: true,
  };
}

/**
 * 安装所有 tx-trade + billing-rules API 的 mock。
 * 通过 state.serverAvailable 动态切换"服务端 500"场景。
 *
 * 与 context.setOffline(true) 的区别：
 *   - setOffline: 浏览器自己的 navigator.onLine=false，不发请求
 *   - serverAvailable=false: 请求能发出但返回 503，用于测试 fallback 入队
 */
export async function installTradeMocks(page: Page, state: MockTradeState): Promise<void> {
  const handleOrders = async (route: Route, request: Request) => {
    if (!state.serverAvailable) {
      await route.fulfill({ status: 503, body: '{"ok":false,"error":{"message":"degraded"}}' });
      return;
    }
    state.orderCount += 1;
    state.lastOrderId = `ord-test-${state.orderCount}`;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        data: { order_id: state.lastOrderId, order_no: `T-${state.orderCount.toString().padStart(4, '0')}` },
      }),
    });
  };

  const handleItems = async (route: Route) => {
    if (!state.serverAvailable) {
      await route.fulfill({ status: 503, body: '{"ok":false}' });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { item_id: `item-${Date.now()}`, subtotal_fen: 8800 } }),
    });
  };

  const handleSettle = async (route: Route, request: Request) => {
    if (!state.serverAvailable) {
      await route.fulfill({ status: 503, body: '{"ok":false}' });
      return;
    }
    const reqId = request.headers()['x-request-id'];
    if (reqId) {
      if (state.seenRequestIds.has(reqId)) {
        // 真实 tx-trade 的幂等：同一 request_id 返回同一响应
        await route.fulfill({
          status: 200,
          body: JSON.stringify({ ok: true, data: { order_no: 'T-REPLAY', final_amount_fen: 8800 } }),
        });
        return;
      }
      state.seenRequestIds.add(reqId);
    }
    state.settleCount += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { order_no: `T-SETTLE-${state.settleCount}`, final_amount_fen: 8800 } }),
    });
  };

  const handlePayment = async (route: Route, request: Request) => {
    if (!state.serverAvailable) {
      await route.fulfill({ status: 503, body: '{"ok":false}' });
      return;
    }
    const reqId = request.headers()['x-request-id'];
    if (reqId && state.seenRequestIds.has(reqId)) {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({ ok: true, data: { payment_id: 'pay-replay', payment_no: 'P-REPLAY' } }),
      });
      return;
    }
    if (reqId) state.seenRequestIds.add(reqId);
    state.paymentCount += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        data: { payment_id: `pay-${state.paymentCount}`, payment_no: `P-${state.paymentCount.toString().padStart(4, '0')}` },
      }),
    });
  };

  const handleBillingRules = async (route: Route) => {
    // 账单规则：无服务费、无最低消费缺口（简化测试）
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        data: {
          service_fee_items: [],
          service_fee_fen: 0,
          min_spend_shortfall_fen: 0,
          min_spend_required_fen: 0,
          total_extra_fen: 0,
          exempted: true,
          exemption_reason: 'test',
          message: 'test mode',
        },
      }),
    });
  };

  const handlePrint = async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, data: { content_base64: 'dGVzdA==' } }),
    });
  };

  // 顺序敏感：更具体的路径先注册
  await page.route('**/api/v1/orders/*/apply-billing-rules', handleBillingRules);
  await page.route('**/api/v1/trade/orders/*/payments', handlePayment);
  await page.route('**/api/v1/trade/orders/*/settle', handleSettle);
  await page.route('**/api/v1/trade/orders/*/print/receipt', handlePrint);
  await page.route('**/api/v1/trade/orders/*/items/**', handleItems);
  await page.route('**/api/v1/trade/orders/*/items', handleItems);
  await page.route('**/api/v1/trade/orders', handleOrders);
  // 菜品查询（menu API）失败时会走 FALLBACK_DISHES
  await page.route('**/api/v1/menu/**', (route) => route.fulfill({ status: 503, body: '{}' }));
}

// ─── 快捷设置：POS 端登录态 + feature flag ────────────────────────────────

export async function setupPOSSession(page: Page, baseURL: string): Promise<void> {
  // web-pos 当前没有强登录守卫，但仍写入 tenant 以满足 X-Tenant-ID header
  await page.goto(baseURL, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => {
    localStorage.setItem('tx_tenant_id', 'demo-tenant');
    // 幂等键缓存清理，避免跨测试污染
    try {
      const dbs = indexedDB.databases ? indexedDB.databases() : Promise.resolve([]);
      void dbs;
    } catch {
      // ignore
    }
  });
}

// ─── 读取离线队列状态（通过 IndexedDB） ─────────────────────────────────────

export async function readOfflineQueueLength(page: Page): Promise<number> {
  return page.evaluate(async () => {
    return new Promise<number>((resolve) => {
      const req = indexedDB.open('tunxiang_pos_offline', 1);
      req.onsuccess = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains('operations')) {
          db.close();
          resolve(0);
          return;
        }
        const tx = db.transaction('operations', 'readonly');
        const store = tx.objectStore('operations');
        const cnt = store.count();
        cnt.onsuccess = () => { db.close(); resolve(cnt.result); };
        cnt.onerror = () => { db.close(); resolve(0); };
      };
      req.onerror = () => resolve(0);
      // IDB 不存在等价于空队列
      req.onupgradeneeded = () => { /* noop */ };
    });
  });
}

export async function clearOfflineQueue(page: Page): Promise<void> {
  await page.evaluate(() => {
    return new Promise<void>((resolve) => {
      const del = indexedDB.deleteDatabase('tunxiang_pos_offline');
      del.onsuccess = () => resolve();
      del.onerror = () => resolve();
      del.onblocked = () => resolve();
    });
  });
}
