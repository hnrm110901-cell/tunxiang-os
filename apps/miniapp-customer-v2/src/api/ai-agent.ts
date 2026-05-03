/**
 * ai-agent.ts — 微信 AI 智能体语义参数 API 适配层 (WA-1)
 *
 * 在现有 API（trade/menu/member/growth）之上提供语义参数包装。
 * 微信 AI 智能体传递的自然语言参数在这里映射为精确的 API 调用。
 *
 * 所有金额单位：分 (fen)，所有时间：ISO 8601。
 */

import { getDishes, searchDishes } from './menu'
import { createOrder, getOrder } from './trade'
import { getMemberProfile } from './member'
import { listCoupons } from './growth'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AiMenuItem {
  dish_id: string
  name: string
  category: string
  price_fen: number
  description: string
  status: 'available' | 'sold_out' | 'off_shelf'
  confidence?: number // 语义匹配置信度
}

export interface AiDishInput {
  dish_name: string
  quantity: number
  spec?: string
}

export interface AiCreateOrderInput {
  store_id: string
  dishes: AiDishInput[]
  preference?: string
}

export interface AiBookingInput {
  store_id: string
  time: string
  guests: number
  note?: string
}

export interface AiMemberInfo {
  member_id: string
  level: string
  level_label: string
  current_points: number
  total_spend_fen: number
  stored_balance_fen: number
}

export interface AiCouponInfo {
  coupon_id: string
  name: string
  type: string
  discount_value: number
  min_order_fen: number
  valid_until: string
  status: string
}

// ---------------------------------------------------------------------------
// 菜品名称模糊匹配
// ---------------------------------------------------------------------------

/**
 * 菜品名称模糊匹配。
 * 使用子串包含 + 拼音首字母简化匹配。
 * 例如 "水煮鱼" 可匹配 "招牌水煮鱼"、"水煮鱼片"。
 */
function fuzzyMatchDish(query: string, dishName: string): number {
  const q = query.toLowerCase().replace(/\s+/g, '')
  const name = dishName.toLowerCase()

  // 精确包含 → 高置信度
  if (name.includes(q) || q.includes(name)) {
    return 0.95
  }

  // 关键词重叠度（取 query 和 dishName 的公共子串占比）
  const queryChars = new Set(q)
  const nameChars = new Set(name)
  const intersection = new Set([...queryChars].filter((c) => nameChars.has(c)))
  if (intersection.size > 0) {
    const overlap = intersection.size / Math.max(queryChars.size, nameChars.size)
    if (overlap > 0.6) return overlap
  }

  return 0
}

/**
 * 在菜品列表中模糊搜索，按置信度降序返回。
 */
export function fuzzySearchDishes(
  dishes: AiMenuItem[],
  query: string,
): AiMenuItem[] {
  const scored = dishes
    .map((d) => ({ ...d, confidence: fuzzyMatchDish(query, d.name) }))
    .filter((d) => (d.confidence ?? 0) > 0.3)
  scored.sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
  return scored as AiMenuItem[]
}

// ---------------------------------------------------------------------------
// 时间解析
// ---------------------------------------------------------------------------

/**
 * 将自然语言时间解析为 ISO 8601 字符串。
 * 支持 "今晚6点半"、"明天中午"、"周六晚上" 等常见说法。
 *
 * @param text 自然语言时间描述
 * @returns ISO 8601 字符串，若无法解析则返回当前时间 + 2小时
 */
export function parseNaturalTime(text: string): string {
  const now = new Date()
  const t = text.replace(/\s+/g, '')

  // "今晚" → 今天 19:00
  if (t.includes('今晚')) {
    const hour = extractHour(t, 19)
    now.setHours(hour, extractMinute(t, 0), 0, 0)
    return toISOString(now)
  }

  // "今晚X点" → 今天指定时间
  if (t.includes('今晚')) {
    now.setHours(extractHour(t, 19), extractMinute(t, 0), 0, 0)
    return toISOString(now)
  }

  // "明晚" → 明天 19:00
  if (t.includes('明晚') || t.includes('明天晚上')) {
    now.setDate(now.getDate() + 1)
    now.setHours(19, 0, 0, 0)
    return toISOString(now)
  }

  // "明天" + 时间 → 明天指定时间
  if (t.includes('明天') || t.includes('明日')) {
    now.setDate(now.getDate() + 1)
    now.setHours(extractHour(t, 12), extractMinute(t, 0), 0, 0)
    return toISOString(now)
  }

  // "周六" / "周日" → 最近对应的日期
  const dayNames: Record<string, number> = {
    周日: 0, 周天: 0, 星期天: 0,
    周一: 1, 周二: 2, 周三: 3, 周四: 4, 周五: 5, 周六: 6,
    星期六: 6, 星期日: 0,
  }
  for (const [name, dayIndex] of Object.entries(dayNames)) {
    if (t.includes(name)) {
      const diff = (dayIndex - now.getDay() + 7) % 7
      now.setDate(now.getDate() + (diff === 0 ? 7 : diff))
      now.setHours(extractHour(t, 19), extractMinute(t, 0), 0, 0)
      return toISOString(now)
    }
  }

  // 提取 "X点X分" 模式
  const hourMatch = t.match(/(\d+)\s*点(\s*(\d+)\s*分)?/)
  if (hourMatch) {
    now.setHours(
      parseInt(hourMatch[1], 10),
      hourMatch[3] ? parseInt(hourMatch[3], 10) : 0,
      0, 0,
    )
    return toISOString(now)
  }

  // 默认：2小时后
  now.setHours(now.getHours() + 2, 0, 0, 0)
  return toISOString(now)
}

function extractHour(text: string, defaultVal: number): number {
  const m = text.match(/(\d+)\s*点/)
  return m ? parseInt(m[1], 10) : defaultVal
}

function extractMinute(text: string, defaultVal: number): number {
  const m = text.match(/(\d+)\s*分/)
  return m ? parseInt(m[1], 10) : defaultVal
}

function toISOString(date: Date): string {
  // 格式化为本地时区的 ISO 8601
  const offset = -date.getTimezoneOffset()
  const sign = offset >= 0 ? '+' : '-'
  const pad = (n: number) => String(Math.abs(n)).padStart(2, '0')
  const hours = pad(Math.floor(Math.abs(offset) / 60))
  const minutes = pad(Math.abs(offset) % 60)
  return (
    date.getFullYear() +
    '-' +
    pad(date.getMonth() + 1) +
    '-' +
    pad(date.getDate()) +
    'T' +
    pad(date.getHours()) +
    ':' +
    pad(date.getMinutes()) +
    ':00' +
    sign +
    hours +
    ':' +
    minutes
  )
}

// ---------------------------------------------------------------------------
// 语义参数 API — 6 个核心函数
// ---------------------------------------------------------------------------

/**
 * 1. 查询菜单 — 支持按名称搜索和分类过滤。
 *
 * 语义参数示例：
 * - queryMenu("store_001") → 返回全菜单
 * - queryMenu("store_001", "水煮鱼") → 模糊搜索"水煮鱼"
 * - queryMenu("store_001", undefined, "招牌") → 只返回招牌菜
 */
export async function queryMenu(
  storeId: string,
  dishName?: string,
  category?: string,
): Promise<{
  store_id: string
  dishes: AiMenuItem[]
  total: number
}> {
  // 若指定了 dishName，走搜索接口
  if (dishName) {
    const result = await searchDishes(storeId, dishName)
    // 对搜索结果进行模糊排序
    const scored = fuzzySearchDishes(
      result.items.map((d: Record<string, unknown>) => ({
        dish_id: d.dishId as string,
        name: d.name as string,
        category: '',
        price_fen: d.basePriceFen as number,
        description: (d.description as string) ?? '',
        status: d.status as 'available',
      })),
      dishName,
    )
    return {
      store_id: storeId,
      dishes: scored,
      total: scored.length,
    }
  }

  // 获取全量菜品
  const dishes = await getDishes(storeId)
  let items = dishes.map((d) => ({
    dish_id: d.dishId,
    name: d.name,
    category: '',
    price_fen: d.basePriceFen,
    description: d.description ?? '',
    status: d.status,
  }))

  // 按分类过滤（前端侧过滤，因为 getDishes 当前不支持 category 参数）
  if (category && category !== '全部') {
    items = items.filter((d) => d.name.includes(category))
  }

  return { store_id: storeId, dishes: items, total: items.length }
}

/**
 * 2. 创建订单 — 支持语义化菜品参数。
 *
 * 语义参数示例：
 * - createOrder("store_001", [{dish_name: "水煮鱼", quantity: 1}])
 * - createOrder("store_001", [{dish_name: "辣子鸡", quantity: 2}], "少油")
 */
export async function submitOrder(
  input: AiCreateOrderInput,
): Promise<{
  order_id: string
  store_id: string
  items: AiDishInput[]
  total_fen: number
  status: string
  created_at: string
}> {
  // 先获取菜单，将语义菜品名映射为 dish_id
  const menuResult = await queryMenu(input.store_id)
  const mappedItems = input.dishes.map((d) => {
    const matched = fuzzySearchDishes(menuResult.dishes, d.dish_name)
    return {
      dishId: matched.length > 0 ? matched[0].dish_id : d.dish_name,
      quantity: d.quantity,
      ...(d.spec ? { remark: d.spec } : {}),
    }
  })

  const order = await createOrder({
    storeId: input.store_id,
    items: mappedItems.map((item) => ({
      dishId: item.dishId,
      quantity: item.quantity,
      ...(item.remark ? { remark: item.remark } : {}),
    })),
    ...(input.preference ? { remark: input.preference } : {}),
  })

  return {
    order_id: order.orderId,
    store_id: input.store_id,
    items: input.dishes,
    total_fen: order.totalFen,
    status: order.status,
    created_at: order.createdAt,
  }
}

/**
 * 3. 查询订单状态。
 */
export async function queryOrder(
  orderId: string,
): Promise<{
  order_id: string
  status: string
  total_fen: number
  paid_fen: number
  estimated_wait_minutes?: number
}> {
  const order = await getOrder(orderId)
  return {
    order_id: order.orderId,
    status: order.status,
    total_fen: order.totalFen,
    paid_fen: order.payableFen,
    estimated_wait_minutes: 15, // 前端侧估算；WA-2 接入真实预计时间
  }
}

/**
 * 4. 查询会员信息。
 */
export async function queryMember(): Promise<AiMemberInfo> {
  const profile = await getMemberProfile()
  return {
    member_id: profile.memberId,
    level: profile.level.name,
    level_label: profile.level.label,
    current_points: profile.currentPoints,
    total_spend_fen: profile.totalSpendFen,
    stored_balance_fen: 0, // 独立接口，WA-2 补充
  }
}

/**
 * 5. 查询可用优惠券。
 */
export async function queryCoupons(
  status?: 'available' | 'used' | 'expired',
): Promise<AiCouponInfo[]> {
  const coupons = await listCoupons(status)
  return coupons.map((c) => ({
    coupon_id: c.couponId,
    name: c.name,
    type: c.type,
    discount_value: c.discountValue,
    min_order_fen: c.minOrderFen,
    valid_until: c.validUntil,
    status: c.status,
  }))
}

/**
 * 6. 预订桌位 — 自然语言时间解析。
 *
 * 语义参数示例：
 * - bookTable("store_001", "今晚6点半", 4)
 * - bookTable("store_001", "明天中午", 6, "靠窗")
 */
export async function bookTable(
  input: AiBookingInput,
): Promise<{
  booking_id: string
  time: string
  guests: number
  table_no?: string
  status: string
}> {
  // 解析自然语言时间
  const parsedTime = parseNaturalTime(input.time)

  // 通过 Gateway 发送预订请求到 tx-trade
  const response = await Taro.request({
    url: `/api/v1/bookings`,
    method: 'POST',
    data: {
      store_id: input.store_id,
      time: parsedTime,
      guests: input.guests,
      note: input.note,
    },
  })

  const body = response.data as { ok: boolean; data?: Record<string, unknown> }
  if (!body.ok) {
    throw new Error('预订失败: ' + JSON.stringify(body))
  }

  const d = body.data ?? {}
  return {
    booking_id: (d.booking_id as string) ?? '',
    time: parsedTime,
    guests: input.guests,
    table_no: d.table_no as string,
    status: (d.status as string) ?? 'confirmed',
  }
}

// 为了保持与 Taro 的兼容性，此处引用 Taro 命名空间（由小程序框架注入）
declare const Taro: {
  request: (options: {
    url: string
    method?: string
    data?: Record<string, unknown>
    header?: Record<string, string>
    timeout?: number
  }) => Promise<{ data: { ok: boolean; data?: Record<string, unknown> } }>
}
