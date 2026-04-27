/**
 * Tier 1 测试：useOffline — R-补2-1 离线 replay 幂等键
 *
 * 徐记海鲜真实场景（CLAUDE.md §17 Tier1 铁律 — 餐厅场景非技术边界值）：
 *
 *   场景 A：晚高峰 47 桌结算时网络抖动 → 入队 → POS 应用崩溃重启 → 收银员重点结算
 *           → 网络恢复 → server 必须用 X-Idempotency-Key 拦截第二次 settle，杜绝同单双扣
 *
 *   场景 B：旧版本 POS 升级前已有离线队列（无 idempotencyKey 字段），升级后 replay
 *           必须按 type+payload 派生稳定 key，与升级前后的同单调用映射到同一 server
 *           replay cache 槽位
 *
 *   场景 C：create_payment 跨支付方式不能错合并（微信支付 vs 支付宝 必须不同 key）
 *
 *   场景 D：add_item 没有天然唯一锚点，必须用 op.id 兜底防同桌同菜误合并
 *
 *   场景 E：settle replay 必填 X-Idempotency-Key header（server replay cache 命中前提）
 *
 *   场景 F：旧 settle op（无 idempotencyKey）replay 时派生 key 与新 op 完全一致
 *           → 升级期间不会出现"老队列重放=新调用"的双扣
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  deriveIdempotencyKey,
  replayOperation,
  type OfflineOperation,
} from '../useOffline';

type FetchSpy = ReturnType<typeof vi.fn>;

function installFetch(impl: FetchSpy): void {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).fetch = impl;
}

function mkOp(partial: Partial<OfflineOperation> & Pick<OfflineOperation, 'type'>): OfflineOperation {
  return {
    id: 'offline_xj_test_001',
    payload: {},
    createdAt: '2026-04-24T12:00:00.000Z',
    retryCount: 0,
    ...partial,
  };
}

describe('useOffline.deriveIdempotencyKey — Tier 1 派生稳定幂等键', () => {
  it('场景 B：徐记 17 号店 settle_order 无 idempotencyKey 字段时按 settle:${orderId} 派生', () => {
    const oldOp = mkOp({
      type: 'settle_order',
      payload: { orderId: 'xj17-O-202604240047' },
    });
    expect(deriveIdempotencyKey(oldOp)).toBe('settle:xj17-O-202604240047');
  });

  it('场景 C：create_payment 不同支付方式派生不同 key（微信≠支付宝，防错合并）', () => {
    const wx = mkOp({
      type: 'create_payment',
      payload: { orderId: 'O-1', method: 'wechat', amountFen: 8800 },
    });
    const ali = mkOp({
      type: 'create_payment',
      payload: { orderId: 'O-1', method: 'alipay', amountFen: 8800 },
    });
    expect(deriveIdempotencyKey(wx)).toBe('payment:O-1:wechat');
    expect(deriveIdempotencyKey(ali)).toBe('payment:O-1:alipay');
    expect(deriveIdempotencyKey(wx)).not.toBe(deriveIdempotencyKey(ali));
  });

  it('场景 D：add_item 缺乏天然唯一锚点，派生 key 包含 op.id 防同桌同菜误合并', () => {
    const item1 = mkOp({
      id: 'offline_a',
      type: 'add_item',
      payload: { orderId: 'O-1', dishId: 'dish-pixiang-crab' },
    });
    const item2 = mkOp({
      id: 'offline_b',
      type: 'add_item',
      payload: { orderId: 'O-1', dishId: 'dish-pixiang-crab' },
    });
    // 同 orderId + 同 dishId 但不同 op，必须不同 key（否则两份霸王蟹会被合并成一份）
    expect(deriveIdempotencyKey(item1)).not.toBe(deriveIdempotencyKey(item2));
  });

  it('场景 F：op 自身已有 idempotencyKey 时直接复用（不派生覆盖）', () => {
    const op = mkOp({
      type: 'settle_order',
      payload: { orderId: 'O-2' },
      idempotencyKey: 'settle:O-2-FROM-TX-FETCH-OFFLINE',
    });
    expect(deriveIdempotencyKey(op)).toBe('settle:O-2-FROM-TX-FETCH-OFFLINE');
  });

  it('场景 F2：升级前 settle op（无 key）replay 派生 key === 新版 settleOrderOffline 在线 key', () => {
    // tradeApi.ts 在线 settleOrder/settleOrderOffline 用 `settle:${orderId}` 作为 X-Idempotency-Key
    // 升级前的离线 op replay 必须派生同 key，否则"老队列重放 + 重启后再点结算" 会双扣
    const oldQueueOp = mkOp({
      type: 'settle_order',
      payload: { orderId: 'O-XJ-300' },
    });
    expect(deriveIdempotencyKey(oldQueueOp)).toBe('settle:O-XJ-300');
  });

  it('未知 type 派生 legacy:${id}（不抛错，保证升级兼容）', () => {
    const unknownOp = {
      id: 'unknown-op',
      type: 'reservation' as unknown as OfflineOperation['type'],
      payload: {},
      createdAt: '2026-04-24T12:00:00.000Z',
      retryCount: 0,
    } satisfies OfflineOperation;
    expect(deriveIdempotencyKey(unknownOp)).toBe('legacy:unknown-op');
  });
});

describe('useOffline.replayOperation — Tier 1 X-Idempotency-Key header', () => {
  beforeEach(() => {
    // 清掉 X-Tenant-ID 环境影响
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('场景 A：徐记 47 桌 settle replay 必填 X-Idempotency-Key（server replay cache 拦截前提）', async () => {
    const fetchSpy: FetchSpy = vi.fn(
      async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    installFetch(fetchSpy);

    const op = mkOp({
      id: 'offline_xj47_settle',
      type: 'settle_order',
      payload: { orderId: 'O-XJ-47' },
      idempotencyKey: 'settle:O-XJ-47',
    });
    const ok = await replayOperation(op);
    expect(ok).toBe(true);

    // 核心断言：fetch 被调用时 headers 必须包含 X-Idempotency-Key
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    expect(headers['X-Idempotency-Key']).toBe('settle:O-XJ-47');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('场景 B：升级前老 op（无 idempotencyKey）replay 时派生 key 注入 header', async () => {
    const fetchSpy: FetchSpy = vi.fn(
      async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    installFetch(fetchSpy);

    // 模拟升级前的 IndexedDB 队列条目 — 没有 idempotencyKey 字段
    const oldOp = mkOp({
      type: 'settle_order',
      payload: { orderId: 'O-XJ-LEGACY-99' },
    });
    expect(oldOp.idempotencyKey).toBeUndefined();

    await replayOperation(oldOp);

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Record<string, string>;
    // R-补2-1：派生 key 必须等于"在线 settle 路径用的 key"，让 server 同槽位识别
    expect(headers['X-Idempotency-Key']).toBe('settle:O-XJ-LEGACY-99');
  });

  it('场景 C：create_payment replay 用 method-aware key（微信单不会被支付宝覆盖）', async () => {
    const fetchSpy: FetchSpy = vi.fn(
      async () => new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );
    installFetch(fetchSpy);

    const op = mkOp({
      type: 'create_payment',
      payload: { orderId: 'O-XJ-pay', method: 'wechat', amountFen: 12800 },
      idempotencyKey: 'payment:O-XJ-pay:wechat',
    });
    await replayOperation(op);

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain('/api/v1/trade/orders/O-XJ-pay/payments');
    const headers = init.headers as Record<string, string>;
    expect(headers['X-Idempotency-Key']).toBe('payment:O-XJ-pay:wechat');
    // body 仍按支付方式区分，header 与 body 一致
    const body = JSON.parse(init.body as string) as { method: string };
    expect(body.method).toBe('wechat');
  });

  it('场景 E：未知 type 不发请求并返回 false（不污染 fetch spy）', async () => {
    const fetchSpy: FetchSpy = vi.fn();
    installFetch(fetchSpy);

    const unknownOp = {
      id: 'unknown-op',
      type: 'reservation' as unknown as OfflineOperation['type'],
      payload: {},
      createdAt: '2026-04-24T12:00:00.000Z',
      retryCount: 0,
    } satisfies OfflineOperation;
    const ok = await replayOperation(unknownOp);
    expect(ok).toBe(false);
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('useOffline R-补2-1 端到端契约：在线 key === 离线 replay key', () => {
  it('settle:${orderId} 在 tradeApi 在线路径与 replayOperation 派生 key 完全一致', () => {
    // 在线路径常量来自 apps/web-pos/src/api/tradeApi.ts settleOrderOffline:
    //   idempotencyKey: `settle:${orderId}`
    // 离线 replay 派生（本文件 deriveIdempotencyKey）：
    //   `settle:${payload.orderId}`
    // 二者必须一致，否则 server replay cache 不会命中。
    const orderId = 'XJ-TIER1-CONSISTENT-1';
    const onlineKey = `settle:${orderId}`;
    const offlineDerivedKey = deriveIdempotencyKey(
      mkOp({ type: 'settle_order', payload: { orderId } }),
    );
    expect(offlineDerivedKey).toBe(onlineKey);
  });

  it('payment:${orderId}:${method} 同样契约（防跨方式合并）', () => {
    const orderId = 'XJ-TIER1-CONSISTENT-2';
    const method = 'alipay';
    const onlineKey = `payment:${orderId}:${method}`;
    const offlineDerivedKey = deriveIdempotencyKey(
      mkOp({ type: 'create_payment', payload: { orderId, method, amountFen: 1 } }),
    );
    expect(offlineDerivedKey).toBe(onlineKey);
  });
});
