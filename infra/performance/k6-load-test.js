/**
 * k6 Load Test - 屯象OS 200桌并发餐饮收银场景
 *
 * 对标 CLAUDE.md §22 Week 8 DEMO 验收门槛:
 *   - P99 延迟 < 200ms
 *   - 200 桌并发场景
 *
 * 用法:
 *   K6_BASE_URL=http://localhost:8000 k6 run k6-load-test.js
 */

import http from "k6/http";
import { check, sleep, group } from "k6";
import { Rate, Trend } from "k6/metrics";

// ---------------------------------------------------------------------------
// 环境变量
// ---------------------------------------------------------------------------
const BASE_URL = __ENV.K6_BASE_URL || "http://localhost:8000";
const TENANT_ID =
  __ENV.K6_TENANT_ID || "10000000-0000-0000-0000-000000001001";

// ---------------------------------------------------------------------------
// 自定义指标
// ---------------------------------------------------------------------------
const errorRate = new Rate("errors");
const dineInDuration = new Trend("dine_in_duration", true);
const menuQueryDuration = new Trend("menu_query_duration", true);
const memberLoyaltyDuration = new Trend("member_loyalty_duration", true);

// ---------------------------------------------------------------------------
// 公共 Headers
// ---------------------------------------------------------------------------
const HEADERS = {
  "Content-Type": "application/json",
  "X-Tenant-ID": TENANT_ID,
  Authorization: "Bearer demo-token",
};

// ---------------------------------------------------------------------------
// k6 配置
// ---------------------------------------------------------------------------
export const options = {
  scenarios: {
    // 60% — 堂食收银链路
    dine_in_checkout: {
      executor: "constant-vus",
      vus: 120,
      duration: "2m",
      exec: "dineInCheckout",
    },
    // 25% — 菜单查询
    menu_query: {
      executor: "constant-vus",
      vus: 50,
      duration: "2m",
      exec: "menuQuery",
    },
    // 15% — 会员 + 积分
    member_loyalty: {
      executor: "constant-vus",
      vus: 30,
      duration: "2m",
      exec: "memberLoyalty",
    },
  },
  thresholds: {
    http_req_duration: ["p(99)<200"],
    errors: ["rate<0.01"],
    dine_in_duration: ["p(99)<200"],
    menu_query_duration: ["p(99)<200"],
    member_loyalty_duration: ["p(99)<200"],
  },
};

// ---------------------------------------------------------------------------
// 辅助函数
// ---------------------------------------------------------------------------
function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function randomPhone() {
  return `138${String(randomInt(10000000, 99999999))}`;
}

function randomStoreId() {
  return `store-${String(randomInt(1, 20)).padStart(3, "0")}`;
}

// ---------------------------------------------------------------------------
// 场景 1: 堂食收银链路 (60%)
// POST /api/v1/tables/{id}/open
// POST /api/v1/orders
// POST /api/v1/orders/{id}/items
// POST /api/v1/orders/{id}/settle
// ---------------------------------------------------------------------------
export function dineInCheckout() {
  const tableId = randomInt(1, 200);
  const storeId = randomStoreId();

  group("堂食收银链路", function () {
    // 1. 开桌
    const openRes = http.post(
      `${BASE_URL}/api/v1/tables/${tableId}/open`,
      JSON.stringify({
        store_id: storeId,
        guest_count: randomInt(1, 10),
      }),
      { headers: HEADERS, tags: { name: "开桌" } }
    );
    check(openRes, { "开桌 status 2xx": (r) => r.status >= 200 && r.status < 300 }) || errorRate.add(1);
    dineInDuration.add(openRes.timings.duration);

    // 2. 创建订单
    const orderRes = http.post(
      `${BASE_URL}/api/v1/orders`,
      JSON.stringify({
        store_id: storeId,
        table_id: tableId,
        order_type: "dine_in",
      }),
      { headers: HEADERS, tags: { name: "创建订单" } }
    );
    check(orderRes, { "创建订单 status 2xx": (r) => r.status >= 200 && r.status < 300 }) || errorRate.add(1);
    dineInDuration.add(orderRes.timings.duration);

    let orderId = "unknown";
    try {
      const body = JSON.parse(orderRes.body);
      orderId = body.data && body.data.id ? body.data.id : `order-${randomInt(1, 99999)}`;
    } catch (_) {
      orderId = `order-${randomInt(1, 99999)}`;
    }

    // 3. 添加菜品（1-5 道）
    const itemCount = randomInt(1, 5);
    for (let i = 0; i < itemCount; i++) {
      const itemRes = http.post(
        `${BASE_URL}/api/v1/orders/${orderId}/items`,
        JSON.stringify({
          dish_id: `dish-${randomInt(1, 200)}`,
          quantity: randomInt(1, 3),
          spec: "standard",
        }),
        { headers: HEADERS, tags: { name: "添加菜品" } }
      );
      check(itemRes, { "添加菜品 status 2xx": (r) => r.status >= 200 && r.status < 300 }) || errorRate.add(1);
      dineInDuration.add(itemRes.timings.duration);
    }

    // 4. 结账
    const settleRes = http.post(
      `${BASE_URL}/api/v1/orders/${orderId}/settle`,
      JSON.stringify({
        payment_method: "wechat_pay",
        total_fen: randomInt(5000, 80000),
      }),
      { headers: HEADERS, tags: { name: "结账" } }
    );
    check(settleRes, { "结账 status 2xx": (r) => r.status >= 200 && r.status < 300 }) || errorRate.add(1);
    dineInDuration.add(settleRes.timings.duration);
  });

  sleep(randomInt(1, 3));
}

// ---------------------------------------------------------------------------
// 场景 2: 菜单查询 (25%)
// GET /api/v1/menus?store_id=xxx
// GET /api/v1/dishes?category_id=xxx
// ---------------------------------------------------------------------------
export function menuQuery() {
  const storeId = randomStoreId();

  group("菜单查询", function () {
    // 1. 查询菜单列表
    const menuRes = http.get(
      `${BASE_URL}/api/v1/menus?store_id=${storeId}`,
      { headers: HEADERS, tags: { name: "菜单列表" } }
    );
    check(menuRes, { "菜单列表 status 2xx": (r) => r.status >= 200 && r.status < 300 }) || errorRate.add(1);
    menuQueryDuration.add(menuRes.timings.duration);

    // 2. 按分类查询菜品
    const categoryId = `cat-${randomInt(1, 30)}`;
    const dishRes = http.get(
      `${BASE_URL}/api/v1/dishes?category_id=${categoryId}&page=1&size=20`,
      { headers: HEADERS, tags: { name: "菜品列表" } }
    );
    check(dishRes, { "菜品列表 status 2xx": (r) => r.status >= 200 && r.status < 300 }) || errorRate.add(1);
    menuQueryDuration.add(dishRes.timings.duration);
  });

  sleep(randomInt(1, 2));
}

// ---------------------------------------------------------------------------
// 场景 3: 会员 + 积分 (15%)
// GET  /api/v1/members/by-phone/{phone}
// POST /api/v1/loyalty/earn
// ---------------------------------------------------------------------------
export function memberLoyalty() {
  const phone = randomPhone();

  group("会员+积分", function () {
    // 1. 按手机号查询会员
    const memberRes = http.get(
      `${BASE_URL}/api/v1/members/by-phone/${phone}`,
      { headers: HEADERS, tags: { name: "会员查询" } }
    );
    check(memberRes, { "会员查询 status 2xx": (r) => r.status >= 200 && r.status < 300 }) || errorRate.add(1);
    memberLoyaltyDuration.add(memberRes.timings.duration);

    let memberId = "unknown";
    try {
      const body = JSON.parse(memberRes.body);
      memberId = body.data && body.data.id ? body.data.id : `member-${randomInt(1, 99999)}`;
    } catch (_) {
      memberId = `member-${randomInt(1, 99999)}`;
    }

    // 2. 积分获取
    const earnRes = http.post(
      `${BASE_URL}/api/v1/loyalty/earn`,
      JSON.stringify({
        member_id: memberId,
        order_id: `order-${randomInt(1, 99999)}`,
        points: randomInt(10, 500),
        source: "dine_in",
      }),
      { headers: HEADERS, tags: { name: "积分获取" } }
    );
    check(earnRes, { "积分获取 status 2xx": (r) => r.status >= 200 && r.status < 300 }) || errorRate.add(1);
    memberLoyaltyDuration.add(earnRes.timings.duration);
  });

  sleep(randomInt(1, 2));
}
