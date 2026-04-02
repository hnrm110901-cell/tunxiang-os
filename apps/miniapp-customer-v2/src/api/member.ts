/**
 * member.ts — tx-member service API (port 8003, accessed via gateway /api/v1/)
 *
 * Endpoints operate on the authenticated member (identified by Bearer token).
 */
import { txRequest } from '../utils/request'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type MemberLevelName = 'bronze' | 'silver' | 'gold' | 'platinum' | 'diamond'

export interface MemberLevel {
  levelId: string
  name: MemberLevelName
  label: string
  /** Minimum points required to hold this level */
  minPoints: number
  /** Maximum points before the next level (null = no ceiling) */
  maxPoints: number | null
  /** Discount multiplier e.g. 0.95 = 5% off */
  discountRate: number
  /** Points multiplier e.g. 1.5 = earn 1.5x points */
  pointsMultiplier: number
}

export interface MemberProfile {
  memberId: string
  openid?: string
  nickname?: string
  avatarUrl?: string
  phone?: string
  gender?: 0 | 1 | 2 // 0=unknown, 1=male, 2=female
  level: MemberLevel
  totalPointsEarned: number
  currentPoints: number
  totalSpendFen: number
  registeredAt: string
  lastActiveAt: string
  preferences?: MemberPreferences
}

export interface MemberPreferences {
  spicyLevel?: 0 | 1 | 2 | 3
  dietaryRestrictions?: string[]
  favoriteCuisines?: string[]
  receivePromotions?: boolean
}

export interface PointsBalance {
  memberId: string
  currentPoints: number
  pendingPoints: number
  expiringSoonPoints: number
  expiringAt?: string
}

export type PointsTransactionType =
  | 'earn_order'
  | 'earn_signup'
  | 'earn_referral'
  | 'earn_activity'
  | 'spend_redeem'
  | 'spend_order'
  | 'expire'
  | 'admin_adjust'

export interface PointsTransaction {
  txId: string
  type: PointsTransactionType
  points: number
  /** Positive = earned, negative = spent */
  delta: number
  balanceAfter: number
  description: string
  orderId?: string
  createdAt: string
}

export interface PointsHistory {
  items: PointsTransaction[]
  total: number
  page: number
  size: number
}

export interface StoredValueCard {
  cardId: string
  memberId: string
  balanceFen: number
  totalRechargeFen: number
  totalConsumedFen: number
  status: 'active' | 'frozen' | 'closed'
  createdAt: string
  lastTransactionAt?: string
}

export interface WxLoginResult {
  accessToken: string
  refreshToken: string
  expiresIn: number
  memberId: string
  isNewMember: boolean
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const BASE = '/api/v1'

/** Get the authenticated member's full profile */
export async function getMemberProfile(): Promise<MemberProfile> {
  return txRequest<MemberProfile>(`${BASE}/members/me`)
}

/** Get the authenticated member's current level details */
export async function getMemberLevel(): Promise<MemberLevel> {
  return txRequest<MemberLevel>(`${BASE}/members/me/level`)
}

/** Get the authenticated member's points balance */
export async function getPointsBalance(): Promise<PointsBalance> {
  return txRequest<PointsBalance>(`${BASE}/members/me/points`)
}

/** Get the authenticated member's points transaction history */
export async function getPointsHistory(page = 1, size = 20): Promise<PointsHistory> {
  return txRequest<PointsHistory>(
    `${BASE}/members/me/points/history?page=${page}&size=${size}`,
  )
}

/** Get the authenticated member's stored-value card */
export async function getStoredValueCard(): Promise<StoredValueCard> {
  return txRequest<StoredValueCard>(`${BASE}/members/me/stored-value`)
}

/** Update member preferences */
export async function updatePreferences(prefs: MemberPreferences): Promise<MemberProfile> {
  return txRequest<MemberProfile>(
    `${BASE}/members/me/preferences`,
    'PUT',
    prefs as unknown as Record<string, unknown>,
  )
}

/**
 * WeChat mini-program login.
 * Sends the wx.login code to the gateway; the backend exchanges it for
 * an openid/session_key and returns tx tokens.
 */
export async function wxLogin(code: string): Promise<WxLoginResult> {
  return txRequest<WxLoginResult>(`${BASE}/auth/wx-login`, 'POST', { code })
}
