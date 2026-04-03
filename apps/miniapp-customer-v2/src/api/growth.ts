/**
 * growth.ts — tx-growth service API (port 8004, accessed via gateway /api/v1/)
 *
 * Covers: coupons, stamp cards, group-buy, points mall, referral, activities.
 */
import { txRequest } from '../utils/request'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type CouponStatus = 'available' | 'used' | 'expired'

export type CouponType = 'discount_percent' | 'discount_fen' | 'free_item' | 'free_shipping'

export interface Coupon {
  couponId: string
  memberId: string
  name: string
  description?: string
  type: CouponType
  /** For discount_percent: e.g. 85 = 85折 (15% off). For discount_fen: amount in fen */
  discountValue: number
  /** Minimum order amount in fen required to use this coupon */
  minOrderFen: number
  status: CouponStatus
  claimedAt: string
  validFrom: string
  validUntil: string
  usedAt?: string
  usedOrderId?: string
}

export interface ClaimCouponResult {
  coupon: Coupon
  /** Remaining claims available for this activity */
  remainingClaims?: number
}

export type StampStatus = 'in_progress' | 'completed' | 'expired' | 'redeemed'

export interface Stamp {
  stampIndex: number
  earnedAt?: string
  isEarned: boolean
}

export interface StampCardReward {
  rewardId: string
  description: string
  /** Coupon granted on completion, if any */
  couponId?: string
  freeItemDishId?: string
}

export interface StampCard {
  cardId: string
  activityId: string
  activityName: string
  memberId: string
  totalStamps: number
  earnedStamps: number
  stamps: Stamp[]
  status: StampStatus
  reward: StampCardReward
  validUntil: string
  startedAt: string
  completedAt?: string
  redeemedAt?: string
}

export type GroupBuyStatus = 'recruiting' | 'full' | 'success' | 'failed' | 'cancelled'

export interface GroupBuyGroup {
  groupId: string
  activityId: string
  activityName: string
  initiatorId: string
  currentParticipants: number
  requiredParticipants: number
  status: GroupBuyStatus
  /** Group buy price per person in fen */
  groupPriceFen: number
  /** Original price in fen */
  originalPriceFen: number
  expiresAt: string
  createdAt: string
}

export interface JoinGroupBuyResult {
  groupId: string
  memberId: string
  orderId: string
  status: GroupBuyStatus
  currentParticipants: number
  requiredParticipants: number
}

export type PointsMallItemType = 'physical' | 'coupon' | 'stored_value' | 'free_item'

export interface PointsMallItem {
  itemId: string
  name: string
  description?: string
  imageUrl?: string
  type: PointsMallItemType
  pointsCost: number
  stock?: number
  /** For stored_value type: amount in fen */
  storedValueFen?: number
  validUntil?: string
  isActive: boolean
}

export interface RedeemPointsResult {
  redemptionId: string
  itemId: string
  itemName: string
  pointsSpent: number
  pointsBalanceAfter: number
  /** Coupon granted if type=coupon */
  coupon?: {
    couponId: string
    name: string
    validUntil: string
  }
  createdAt: string
}

export interface ReferralCode {
  memberId: string
  code: string
  shareUrl: string
  totalReferrals: number
  successfulReferrals: number
  /** Points earned from referrals so far */
  earnedPoints: number
}

export type ActivityType =
  | 'limited_time_offer'
  | 'group_buy'
  | 'stamp_card'
  | 'points_double'
  | 'new_member'
  | 'flash_sale'

export interface Activity {
  activityId: string
  name: string
  description?: string
  imageUrl?: string
  type: ActivityType
  /** Discount or promotion summary for display */
  badgeText?: string
  validFrom: string
  validUntil: string
  isActive: boolean
  /** Whether the current member has already participated */
  hasParticipated?: boolean
  /** Stores this activity applies to; empty = all stores */
  storeIds?: string[]
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const BASE = '/api/v1'

/** List coupons for the authenticated member, optionally filtered by status */
export async function listCoupons(status?: CouponStatus): Promise<Coupon[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return txRequest<Coupon[]>(`${BASE}/coupons${qs}`)
}

/** Claim a coupon from a promotion activity */
export async function claimCoupon(activityId: string): Promise<ClaimCouponResult> {
  return txRequest<ClaimCouponResult>(`${BASE}/coupons/claim`, 'POST', { activityId })
}

/** Get a stamp card for a given activity */
export async function getStampCard(activityId: string): Promise<StampCard> {
  return txRequest<StampCard>(`${BASE}/stamp-cards/${encodeURIComponent(activityId)}`)
}

/** Join an existing group-buy group */
export async function joinGroupBuy(groupId: string): Promise<JoinGroupBuyResult> {
  return txRequest<JoinGroupBuyResult>(
    `${BASE}/group-buy/${encodeURIComponent(groupId)}/join`,
    'POST',
  )
}

/** Get all items available in the points mall */
export async function getPointsMall(): Promise<PointsMallItem[]> {
  return txRequest<PointsMallItem[]>(`${BASE}/points-mall/items`)
}

/** Redeem points for a points mall item */
export async function redeemPoints(
  itemId: string,
  points: number,
): Promise<RedeemPointsResult> {
  return txRequest<RedeemPointsResult>(`${BASE}/points-mall/redeem`, 'POST', {
    itemId,
    points,
  })
}

/** Get the authenticated member's referral code and stats */
export async function getReferralCode(): Promise<ReferralCode> {
  return txRequest<ReferralCode>(`${BASE}/referral/my-code`)
}

/** Get all currently active promotions and activities */
export async function getActivities(): Promise<Activity[]> {
  return txRequest<Activity[]>(`${BASE}/activities`)
}
