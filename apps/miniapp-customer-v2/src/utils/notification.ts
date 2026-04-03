/**
 * notification.ts — Subscription message management
 *
 * WeChat subscription messages let the mini-program push a one-time notification
 * to a user after they have given explicit consent.  Douyin and H5 do not support
 * this feature; all calls return false on those platforms.
 *
 * Preferences are persisted in Taro storage so the app remembers what the user
 * has already accepted without asking again every session.
 */

import Taro from '@tarojs/taro'
import { requestNotification } from './platform'

// ─── Template IDs ─────────────────────────────────────────────────────────────
// Replace placeholder strings with real IDs issued by the WeChat MP console.

export const NOTIFICATION_TEMPLATES = {
  ORDER_STATUS:        'order_status_template_id',       // 订单状态变更
  QUEUE_CALLED:        'queue_called_template_id',        // 叫号提醒
  COUPON_RECEIVED:     'coupon_received_template_id',     // 优惠到账
  RESERVATION_CONFIRM: 'reservation_confirm_template_id', // 预约确认
  GROUP_BUY_SUCCESS:   'group_buy_success_template_id',   // 拼单成功
} as const

export type NotificationTemplateKey = keyof typeof NOTIFICATION_TEMPLATES

// ─── Storage helpers ──────────────────────────────────────────────────────────

const STORAGE_PREFIX = 'tx_notify_'

function storageKey(type: NotificationTemplateKey): string {
  return `${STORAGE_PREFIX}${type}`
}

// ─── Permission requests ──────────────────────────────────────────────────────

/**
 * Request permission to send order status change notifications.
 * Returns true when the user accepts the subscription.
 */
export async function requestOrderNotification(): Promise<boolean> {
  const accepted = await requestNotification([NOTIFICATION_TEMPLATES.ORDER_STATUS])
  setNotificationEnabled('ORDER_STATUS', accepted)
  return accepted
}

/**
 * Request permission to send queue call-up notifications.
 * Returns true when the user accepts the subscription.
 */
export async function requestQueueNotification(): Promise<boolean> {
  const accepted = await requestNotification([NOTIFICATION_TEMPLATES.QUEUE_CALLED])
  setNotificationEnabled('QUEUE_CALLED', accepted)
  return accepted
}

/**
 * Request all template subscriptions in a single batch.
 *
 * WeChat allows up to 3 template IDs per requestSubscribeMessage call.
 * We make two calls to cover all 5 templates (3 + 2).
 * Returns a map of template key → whether the user accepted.
 */
export async function requestAllNotifications(): Promise<Record<NotificationTemplateKey, boolean>> {
  const keys = Object.keys(NOTIFICATION_TEMPLATES) as NotificationTemplateKey[]
  const ids = keys.map((k) => NOTIFICATION_TEMPLATES[k])

  // Batch 1: first 3
  const batch1Ids = ids.slice(0, 3)
  const batch1Keys = keys.slice(0, 3)
  // Batch 2: remaining
  const batch2Ids = ids.slice(3)
  const batch2Keys = keys.slice(3)

  const result = {} as Record<NotificationTemplateKey, boolean>

  try {
    const accepted1 = await requestNotification(batch1Ids)
    // requestNotification returns true if ANY was accepted; we need per-template
    // granularity. Re-implement the raw call for batch granularity when on WeChat.
    if (process.env.TARO_ENV === 'weapp') {
      const raw = await Taro.requestSubscribeMessage({ tmplIds: batch1Ids })
      batch1Keys.forEach((key, i) => {
        result[key] = (raw as Record<string, string>)[batch1Ids[i]] === 'accept'
        setNotificationEnabled(key, result[key])
      })
    } else {
      batch1Keys.forEach((key) => {
        result[key] = accepted1
        setNotificationEnabled(key, accepted1)
      })
    }
  } catch (_err) {
    batch1Keys.forEach((key) => {
      result[key] = false
    })
  }

  if (batch2Ids.length > 0) {
    try {
      if (process.env.TARO_ENV === 'weapp') {
        const raw = await Taro.requestSubscribeMessage({ tmplIds: batch2Ids })
        batch2Keys.forEach((key, i) => {
          result[key] = (raw as Record<string, string>)[batch2Ids[i]] === 'accept'
          setNotificationEnabled(key, result[key])
        })
      } else {
        const accepted2 = await requestNotification(batch2Ids)
        batch2Keys.forEach((key) => {
          result[key] = accepted2
          setNotificationEnabled(key, accepted2)
        })
      }
    } catch (_err) {
      batch2Keys.forEach((key) => {
        result[key] = false
      })
    }
  }

  return result
}

// ─── Preference cache ─────────────────────────────────────────────────────────

/**
 * Check whether the user has previously accepted a notification type.
 * Reads from Taro storage (synchronous).
 */
export function isNotificationEnabled(type: NotificationTemplateKey): boolean {
  try {
    const val = Taro.getStorageSync<string>(storageKey(type))
    return val === 'true'
  } catch (_err) {
    return false
  }
}

/**
 * Persist the user's notification preference for a given type.
 */
export function setNotificationEnabled(
  type: NotificationTemplateKey,
  enabled: boolean,
): void {
  try {
    Taro.setStorageSync(storageKey(type), enabled ? 'true' : 'false')
  } catch (_err) {
    // Storage errors must not crash the caller
  }
}
