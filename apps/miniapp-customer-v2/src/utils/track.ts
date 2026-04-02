import Taro from '@tarojs/taro'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const IS_DEV = process.env.NODE_ENV !== 'production'
const ANALYTICS_ENDPOINT = '/api/v1/analytics/events'
const QUEUE_FLUSH_SIZE = 10
const QUEUE_MAX_SIZE = 20
const FLUSH_INTERVAL_MS = 10_000

// ---------------------------------------------------------------------------
// Platform detection
// ---------------------------------------------------------------------------

type Platform = 'weapp' | 'tt' | 'h5'

function detectPlatform(): Platform {
  const env = process.env.TARO_ENV as string | undefined
  if (env === 'tt') return 'tt'
  if (env === 'h5') return 'h5'
  return 'weapp'
}

// ---------------------------------------------------------------------------
// Session ID — generated once per app launch, lives in memory only
// ---------------------------------------------------------------------------

function generateSessionId(): string {
  const ts = Date.now().toString(36)
  const rand = Math.random().toString(36).slice(2, 9)
  return `${ts}-${rand}`
}

const SESSION_ID: string = generateSessionId()
const PLATFORM: Platform = detectPlatform()

// ---------------------------------------------------------------------------
// Event types
// ---------------------------------------------------------------------------

export interface PageViewProps {
  page_name: string
  params?: Record<string, unknown>
}

export interface ButtonClickProps {
  button_name: string
  page: string
  extra?: Record<string, unknown>
}

export interface AddToCartProps {
  dish_id: string
  dish_name: string
  price_fen: number
  quantity: number
}

export interface RemoveFromCartProps {
  dish_id: string
}

export interface BeginCheckoutProps {
  total_fen: number
  item_count: number
}

export interface PurchaseProps {
  order_id: string
  total_fen: number
  payment_method: string
  item_count: number
}

export interface CouponApplyProps {
  coupon_id: string
  discount_fen: number
}

export interface MemberLoginProps {
  method: 'wechat'
}

export interface SearchProps {
  keyword: string
  results_count: number
}

export interface PageErrorProps {
  page: string
  error_message: string
}

// ---------------------------------------------------------------------------
// Event envelope — what is queued and sent
// ---------------------------------------------------------------------------

interface EventEnvelope {
  event: string
  props: Record<string, unknown>
  user_id: string | null
  tenant_id: string | null
  timestamp: number
  platform: Platform
  session_id: string
}

// ---------------------------------------------------------------------------
// In-memory queue
// ---------------------------------------------------------------------------

let eventQueue: EventEnvelope[] = []
let flushTimer: ReturnType<typeof setTimeout> | null = null

function getIdentity(): { user_id: string | null; tenant_id: string | null } {
  const user_id = (Taro.getStorageSync<string>('tx_user_id') as string) || null
  const tenant_id = (Taro.getStorageSync<string>('tx_tenant_id') as string) || null
  return { user_id, tenant_id }
}

function buildEnvelope(event: string, props: Record<string, unknown>): EventEnvelope {
  const { user_id, tenant_id } = getIdentity()
  return {
    event,
    props,
    user_id,
    tenant_id,
    timestamp: Date.now(),
    platform: PLATFORM,
    session_id: SESSION_ID,
  }
}

// ---------------------------------------------------------------------------
// Flush logic
// ---------------------------------------------------------------------------

/**
 * Flush all queued events to the analytics gateway.
 * On failure the events are kept in the queue to be retried on the next flush.
 * Call this manually on `onHide` to avoid losing events when the app is backgrounded.
 */
export async function flushEvents(): Promise<void> {
  if (eventQueue.length === 0) return

  // Snapshot the current queue and clear it optimistically
  const batch = eventQueue.slice()
  eventQueue = []

  if (IS_DEV) {
    // eslint-disable-next-line no-console
    console.log('[track:flush]', batch)
    return
  }

  const apiBase =
    (Taro.getStorageSync<string>('tx_api_base') as string) || 'http://localhost:8000'
  const token = (Taro.getStorageSync<string>('tx_token') as string) || ''
  const tenantId = (Taro.getStorageSync<string>('tx_tenant_id') as string) || ''

  const url = `${apiBase.replace(/\/$/, '')}${ANALYTICS_ENDPOINT}`
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Tenant-ID': tenantId,
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  try {
    await Taro.request({
      url,
      method: 'POST',
      data: { events: batch },
      header: headers,
      timeout: 10_000,
    })
  } catch {
    // Flush failed — put events back at the front of the queue.
    // Cap total queue size to QUEUE_MAX_SIZE to avoid unbounded growth.
    const merged = [...batch, ...eventQueue]
    eventQueue = merged.slice(0, QUEUE_MAX_SIZE)
  }
}

function scheduleFlush(): void {
  if (flushTimer !== null) return
  flushTimer = setTimeout(() => {
    flushTimer = null
    flushEvents().catch(() => {
      /* background flush; errors already handled inside flushEvents */
    })
  }, FLUSH_INTERVAL_MS)
}

function enqueue(event: string, props: Record<string, unknown>): void {
  const envelope = buildEnvelope(event, props)

  if (IS_DEV) {
    // eslint-disable-next-line no-console
    console.log('[track]', envelope)
    return
  }

  // Drop oldest event if we're at the hard cap
  if (eventQueue.length >= QUEUE_MAX_SIZE) {
    eventQueue.shift()
  }

  eventQueue.push(envelope)

  // Flush immediately when we hit the soft threshold
  if (eventQueue.length >= QUEUE_FLUSH_SIZE) {
    if (flushTimer !== null) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
    flushEvents().catch(() => {
      /* errors handled inside flushEvents */
    })
    return
  }

  scheduleFlush()
}

// ---------------------------------------------------------------------------
// Generic track — public escape hatch
// ---------------------------------------------------------------------------

export function track(event: string, props: Record<string, unknown> = {}): void {
  enqueue(event, props)
}

// ---------------------------------------------------------------------------
// Named typed helpers
// ---------------------------------------------------------------------------

export function trackPageView(props: PageViewProps): void {
  enqueue('page_view', props as unknown as Record<string, unknown>)
}

export function trackClick(props: ButtonClickProps): void {
  enqueue('button_click', props as unknown as Record<string, unknown>)
}

export function trackAddToCart(props: AddToCartProps): void {
  enqueue('add_to_cart', props as unknown as Record<string, unknown>)
}

export function trackRemoveFromCart(props: RemoveFromCartProps): void {
  enqueue('remove_from_cart', props as unknown as Record<string, unknown>)
}

export function trackBeginCheckout(props: BeginCheckoutProps): void {
  enqueue('begin_checkout', props as unknown as Record<string, unknown>)
}

export function trackPurchase(props: PurchaseProps): void {
  enqueue('purchase', props as unknown as Record<string, unknown>)
}

export function trackCouponApply(props: CouponApplyProps): void {
  enqueue('coupon_apply', props as unknown as Record<string, unknown>)
}

export function trackMemberLogin(props: MemberLoginProps): void {
  enqueue('member_login', props as unknown as Record<string, unknown>)
}

export function trackSearch(props: SearchProps): void {
  enqueue('search', props as unknown as Record<string, unknown>)
}

export function trackError(props: PageErrorProps): void {
  enqueue('page_error', props as unknown as Record<string, unknown>)
}
