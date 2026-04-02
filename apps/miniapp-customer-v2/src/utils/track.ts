import Taro from '@tarojs/taro'
import { txRequest } from './request'

const IS_DEV = process.env.NODE_ENV !== 'production'

/** Analytics event payload */
interface TrackPayload {
  event: string
  props: Record<string, unknown>
  ts: number
  /** Populated server-side from X-Tenant-ID, but included client-side for log clarity */
  tenantId?: string
}

/**
 * Simple event tracking stub.
 * - In development: logs to console only.
 * - In production: fires-and-forgets to the tx-analytics endpoint via gateway.
 *   Failures are silently swallowed so tracking never breaks UI flows.
 */
export function track(event: string, props: Record<string, unknown> = {}): void {
  const payload: TrackPayload = {
    event,
    props,
    ts: Date.now(),
    tenantId: Taro.getStorageSync<string>('tx_tenant_id') ?? undefined,
  }

  if (IS_DEV) {
    // eslint-disable-next-line no-console
    console.log('[track]', payload)
    return
  }

  // Fire-and-forget — do not await, do not surface errors to the caller
  txRequest('/api/v1/analytics/events', 'POST', payload as unknown as Record<string, unknown>).catch(
    () => {
      /* intentionally swallowed */
    },
  )
}
