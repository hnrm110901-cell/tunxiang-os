/**
 * Tier 1 测试：前端离线订单号生成（Sprint A3）
 *
 * 与后端 services/tx-trade/src/services/offline_order_id.py 契约对齐：
 *   order_id = `${device_id}:${ms_epoch}:${counter}`
 *   UUID v7 48-bit ms_epoch + 4-bit ver=7 + 2-bit var=10 + 74-bit rand
 *   idempotency_key = `settle:${order_id}`
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { generateOfflineOrderId, _resetOfflineOrderIdCounterForTest } from '../tradeApi';

describe('generateOfflineOrderId — A3 Tier1 徐记海鲜场景', () => {
  beforeEach(() => {
    _resetOfflineOrderIdCounterForTest();
    // 清空 localStorage 的 device_id 缓存
    try {
      localStorage.removeItem('tx.device_id');
    } catch {
      /* ignore */
    }
  });

  it('xujihaixian 断网 100 单 order_id 互不相同', () => {
    const ids = new Set<string>();
    const uuids = new Set<string>();
    for (let i = 0; i < 100; i += 1) {
      const { orderId, uuidV7 } = generateOfflineOrderId('pos-xuji-001');
      ids.add(orderId);
      uuids.add(uuidV7);
    }
    expect(ids.size).toBe(100);
    expect(uuids.size).toBe(100);
  });

  it('order_id 格式严格遵守 `device_id:ms_epoch:counter`（A1 锁定）', () => {
    const { orderId, deviceId, msEpoch, counter } = generateOfflineOrderId(
      'pos-xuji-002',
    );
    expect(deviceId).toBe('pos-xuji-002');
    expect(orderId).toBe(`${deviceId}:${msEpoch}:${counter}`);
    expect(counter).toBeGreaterThanOrEqual(1);
    expect(msEpoch).toBeGreaterThan(1_700_000_000_000);
  });

  it('UUID v7 version=7 且 variant=10xxxxxx（RFC 9562）', () => {
    const { uuidV7 } = generateOfflineOrderId('pos-xuji-003');
    const hex = uuidV7.replace(/-/g, '');
    const byte6 = parseInt(hex.slice(12, 14), 16);
    const byte8 = parseInt(hex.slice(16, 18), 16);
    expect(byte6 >> 4).toBe(0x7); // version 7
    expect(byte8 >> 6).toBe(0b10); // RFC 4122 variant
  });

  it('idempotency_key 格式 `settle:{order_id}` 与 A1/A2 共享', () => {
    const { orderId } = generateOfflineOrderId('pos-xuji-004');
    const ikey = `settle:${orderId}`;
    expect(ikey.startsWith('settle:')).toBe(true);
    expect(ikey.length).toBeLessThanOrEqual(128); // A2 SagaBuffer 入参上限
  });

  it('同毫秒连续 3 次调用 counter 单调递增', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-04-24T12:00:00Z'));
    const a = generateOfflineOrderId('pos-xuji-005');
    const b = generateOfflineOrderId('pos-xuji-005');
    const c = generateOfflineOrderId('pos-xuji-005');
    expect(b.counter).toBe(a.counter + 1);
    expect(c.counter).toBe(a.counter + 2);
    expect(a.orderId).not.toBe(b.orderId);
    expect(b.orderId).not.toBe(c.orderId);
    vi.useRealTimers();
  });
});
