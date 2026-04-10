/**
 * personalization.ts — 千人千面动态布局引擎
 *
 * 根据用户RFM分层+偏好+订阅状态，动态返回：
 * - 首页快捷入口排列
 * - Banner定向策略
 * - 菜单排序模式
 * - 价格展示策略
 *
 * 数据来源:
 * - useUserStore (memberLevel, preferences, pointsBalance)
 * - useStoreInfo (brandId, storeId)
 * - txRequest('/member/recommend/...') 在线推荐
 */

import { txRequest } from '../utils/request'

// ─── Types ────────────────────────────────────────────────────────────────────

export type UserSegment = 'S1' | 'S2' | 'S3' | 'S4' | 'S5' | 'guest'

export type PriceMode = 'standard' | 'member' | 'corporate'

export interface QuickEntry {
  id: string
  icon: string
  label: string
  path: string
  badge?: string  // "新" / "热" / 数字
}

export interface BannerConfig {
  id: string
  title: string
  subtitle: string
  color: string
  link?: string
  segment?: string  // 目标人群
}

export interface PersonalizedLayout {
  segment: UserSegment
  quickEntries: QuickEntry[]
  banners: BannerConfig[]
  priceMode: PriceMode
  menuSortMode: 'personalized' | 'default'
  showReorderBanner: boolean
  showAiAssistant: boolean
  greeting: string
}

// ─── Segment Detection ────────────────────────────────────────────────────────

export function detectSegment(
  memberLevel: string,
  pointsBalance: number,
  isSubscriber: boolean,
  daysSinceLastVisit: number,
): UserSegment {
  if (!memberLevel || memberLevel === 'none') return 'guest'

  // S1 Champion: 高频+高消费 (diamond/platinum + 付费会员)
  if ((memberLevel === 'diamond' || memberLevel === 'platinum') && isSubscriber) return 'S1'

  // S2 High-value: gold级别 或 高积分
  if (memberLevel === 'gold' || pointsBalance > 5000) return 'S2'

  // S5 Dormant: 超过60天未到店
  if (daysSinceLastVisit > 60) return 'S5'

  // S4 Low-freq: 超过30天
  if (daysSinceLastVisit > 30) return 'S4'

  // S3 Medium: 其余
  return 'S3'
}

// ─── Quick Entries by Segment ─────────────────────────────────────────────────

const ALL_ENTRIES: Record<string, QuickEntry> = {
  scan:      { id: 'scan',      icon: '📱', label: '扫码点餐',  path: '/pages/menu/index' },
  preorder:  { id: 'preorder',  icon: '⏰', label: '预点餐',    path: '/subpages/pre-order/index', badge: '新' },
  delivery:  { id: 'delivery',  icon: '🛵', label: '外卖配送',  path: '/subpages/takeaway/index' },
  reserve:   { id: 'reserve',   icon: '📅', label: '预约订座',  path: '/subpages/reservation/index/index' },
  queue:     { id: 'queue',     icon: '🔢', label: '排号等位',  path: '/subpages/queue/index/index' },
  banquet:   { id: 'banquet',   icon: '🎊', label: '宴会预订',  path: '/subpages/special/banquet/index' },
  chef:      { id: 'chef',      icon: '👨‍🍳', label: '大厨到家',  path: '/subpages/special/chef-at-home/index' },
  corp:      { id: 'corp',      icon: '🏢', label: '企业团餐',  path: '/subpages/special/corporate/index' },
  coupon:    { id: 'coupon',    icon: '🎫', label: '领券中心',  path: '/subpages/marketing/coupon/index', badge: '惠' },
  groupbuy:  { id: 'groupbuy',  icon: '👥', label: '拼单',      path: '/subpages/social/group-order/index' },
  subscribe: { id: 'subscribe', icon: '👑', label: '开通会员',  path: '/subpages/member/subscription/index', badge: '省' },
  points:    { id: 'points',    icon: '⭐', label: '积分兑换',  path: '/subpages/marketing/points-mall/index' },
  game:      { id: 'game',      icon: '🎮', label: '等位乐园',  path: '/subpages/queue-game/index', badge: '玩' },
  review:    { id: 'review',    icon: '📝', label: '写评价',    path: '/subpages/review-reward/index' },
  family:    { id: 'family',    icon: '👶', label: '家庭服务',  path: '/subpages/family-mode/index' },
  video:     { id: 'video',     icon: '🎬', label: '视频探店',  path: '/subpages/dish-detail/index' },
}

const SEGMENT_ENTRIES: Record<UserSegment, string[]> = {
  S1: ['scan', 'preorder', 'reserve', 'banquet', 'chef', 'family'],       // VIP: 高端+家庭
  S2: ['scan', 'preorder', 'reserve', 'coupon', 'points', 'review'],      // 高价值: 留存+UGC
  S3: ['scan', 'preorder', 'coupon', 'delivery', 'game', 'groupbuy'],     // 中间: 性价比+游戏
  S4: ['scan', 'coupon', 'groupbuy', 'subscribe', 'video', 'preorder'],   // 低频: 拉回+视频
  S5: ['coupon', 'scan', 'subscribe', 'groupbuy', 'video', 'review'],     // 沉默: 召回+UGC
  guest: ['scan', 'delivery', 'queue', 'coupon', 'game', 'family'],       // 游客: 基础+体验
}

// ─── Banner by Segment ────────────────────────────────────────────────────────

const SEGMENT_BANNERS: Record<UserSegment, BannerConfig[]> = {
  S1: [
    { id: 'vip1', title: '尊享会员专属', subtitle: '新品抢先体验', color: '#1A2A3A', segment: 'S1' },
    { id: 'vip2', title: '宴会预订尊享', subtitle: '包间免费升级', color: '#2A1A3A', segment: 'S1' },
  ],
  S2: [
    { id: 'hv1', title: '储值满300送50', subtitle: '黄金会员专属', color: '#1A3A2A', segment: 'S2' },
    { id: 'hv2', title: '积分翻倍日', subtitle: '本周末消费积分×2', color: '#1A2A3A', segment: 'S2' },
  ],
  S3: [
    { id: 'md1', title: '新品上线', subtitle: '春季限定菜单', color: '#1A3A4A', segment: 'S3' },
    { id: 'md2', title: '满100减20', subtitle: '本周五至周日', color: '#1A2A3A', segment: 'S3' },
  ],
  S4: [
    { id: 'lf1', title: '好久不见', subtitle: '专属回归礼券已到账', color: '#3A1A2A', segment: 'S4' },
    { id: 'lf2', title: '首次拼单免运费', subtitle: '邀请好友一起点', color: '#1A2A3A', segment: 'S4' },
  ],
  S5: [
    { id: 'dm1', title: '我们想你了', subtitle: '专属50元无门槛券', color: '#3A1A1A', segment: 'S5' },
    { id: 'dm2', title: '菜单已更新', subtitle: '12道新品等你体验', color: '#1A3A2A', segment: 'S5' },
  ],
  guest: [
    { id: 'g1', title: '新客首单立减15', subtitle: '注册即享', color: '#1A3A4A', segment: 'guest' },
    { id: 'g2', title: '扫码点餐更方便', subtitle: '全店覆盖', color: '#1A2A3A', segment: 'guest' },
  ],
}

// ─── Greeting ─────────────────────────────────────────────────────────────────

function getGreeting(segment: UserSegment, nickname: string): string {
  const hour = new Date().getHours()
  const timeGreeting = hour < 11 ? '早上好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好'
  const name = nickname || '美食家'

  switch (segment) {
    case 'S1': return `${timeGreeting}，${name}！您的专属推荐已更新`
    case 'S2': return `${timeGreeting}，${name}！积分商城有新品`
    case 'S3': return `${timeGreeting}，${name}！今日有特惠活动`
    case 'S4': return `好久不见，${name}！为您准备了回归礼`
    case 'S5': return `想你了，${name}！新菜单已为您准备好`
    case 'guest': return `${timeGreeting}！欢迎光临`
    default: return `${timeGreeting}！欢迎光临`
  }
}

// ─── Main Engine ──────────────────────────────────────────────────────────────

export function getPersonalizedLayout(params: {
  memberLevel: string
  pointsBalance: number
  isSubscriber: boolean
  daysSinceLastVisit: number
  nickname: string
  isCorporate?: boolean
}): PersonalizedLayout {
  const segment = detectSegment(
    params.memberLevel,
    params.pointsBalance,
    params.isSubscriber,
    params.daysSinceLastVisit,
  )

  // 企业客户覆盖
  let entries = SEGMENT_ENTRIES[segment].map(id => ALL_ENTRIES[id]).filter(Boolean)
  if (params.isCorporate) {
    entries = [ALL_ENTRIES.corp, ALL_ENTRIES.scan, ALL_ENTRIES.reserve, ALL_ENTRIES.delivery, ALL_ENTRIES.banquet, ALL_ENTRIES.coupon]
  }

  const priceMode: PriceMode = params.isSubscriber ? 'member' : params.isCorporate ? 'corporate' : 'standard'

  return {
    segment,
    quickEntries: entries,
    banners: SEGMENT_BANNERS[segment] || SEGMENT_BANNERS.guest,
    priceMode,
    menuSortMode: segment !== 'guest' ? 'personalized' : 'default',
    showReorderBanner: segment !== 'guest' && segment !== 'S5',
    showAiAssistant: true,
    greeting: getGreeting(segment, params.nickname),
  }
}

// ─── API Helper ───────────────────────────────────────────────────────────────

export async function fetchPersonalizedMenu(storeId: string, customerId: string, cartItems: string[]) {
  return txRequest<{
    dishes: Array<{
      dish_id: string; name: string; category: string; price_fen: number
      member_price_fen: number | null; personal_score: number
      reason: string; reason_type: string
      allergen_warning: string | null; allergens: string[]
      is_recommended: boolean; is_sold_out: boolean; tags: string[]
    }>
    recommended_count: number
    filtered_count: number
    meal_period: string
    user_segment: string
  }>(
    `/menu/personalized?store_id=${storeId}&customer_id=${customerId}&cart_items=${cartItems.join(',')}`,
  )
}
