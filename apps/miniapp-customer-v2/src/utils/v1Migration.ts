/**
 * v1Migration.ts — v1 原生小程序 → v2 Taro 数据迁移工具
 *
 * 读取 v1 小程序遗留在 wx.storage 中的数据，转换为 v2 Zustand store 格式，
 * 一次性写入 v2 的存储。迁移完成后标记 TX_V2_MIGRATED=true，不再重复执行。
 *
 * 调用时机：app.tsx 的 useEffect 中调用 migrateFromV1IfNeeded()
 *
 * v1 存储 key 对照：
 *   tx_token         → tx_token (保留)
 *   tx_user_id       → tx_user_id (保留)
 *   tx_tenant_id     → tx_tenant_id (保留)
 *   tx_cart           → useCartStore (JSON: CartItem[])
 *   tx_user_profile   → useUserStore (JSON: {nickname,avatarUrl,phone,...})
 *   tx_settings       → 用户偏好 (JSON: {spicy,sweet,allergies,...})
 *   tx_store_id       → useStoreInfo.storeId
 *   tx_api_base       → tx_api_base (保留)
 */

import Taro from '@tarojs/taro'
import { useCartStore, type CartItem } from '../store/useCartStore'
import { useUserStore, type MemberLevel, type UserPreferences } from '../store/useUserStore'
import { useStoreInfo } from '../store/useStoreInfo'

// ─── Migration flag ──────────────────────────────────────────────────────────

const MIGRATION_FLAG = 'TX_V2_MIGRATED'

/**
 * Check if v1 → v2 migration has already been performed.
 */
export function isMigrated(): boolean {
  try {
    return Taro.getStorageSync(MIGRATION_FLAG) === true
  } catch (_) {
    return false
  }
}

// ─── Safe storage read helpers ───────────────────────────────────────────────

function readString(key: string): string {
  try {
    const val = Taro.getStorageSync<string>(key)
    return typeof val === 'string' ? val : ''
  } catch (_) {
    return ''
  }
}

function readJSON<T>(key: string): T | null {
  try {
    const raw = Taro.getStorageSync<string>(key)
    if (!raw) return null
    if (typeof raw === 'object') return raw as T
    return JSON.parse(raw) as T
  } catch (_) {
    return null
  }
}

// ─── v1 data shapes ──────────────────────────────────────────────────────────

interface V1CartItem {
  dish_id?: string
  dishId?: string
  dish_name?: string
  name?: string
  unitPriceFen?: number
  price_fen?: number
  priceFen?: number
  quantity?: number
  qty?: number
  specs?: Record<string, string>
  remark?: string
}

interface V1UserProfile {
  nickname?: string
  avatarUrl?: string
  avatar_url?: string
  phone?: string
  level?: string
  member_level?: string
  points_balance?: number
  pointsBalance?: number
  balance_fen?: number
  balanceFen?: number
  stored_value_fen?: number
}

interface V1Settings {
  spicy?: string
  sweet?: string
  allergies?: string[]
  allergens?: string[]
}

// ─── Converters ──────────────────────────────────────────────────────────────

function convertCartItems(v1Items: V1CartItem[]): CartItem[] {
  return v1Items
    .filter((item) => (item.dish_id || item.dishId) && (item.quantity || item.qty))
    .map((item) => ({
      dishId: item.dish_id || item.dishId || '',
      name: item.dish_name || item.name || '',
      price_fen: item.unitPriceFen || item.price_fen || item.priceFen || 0,
      quantity: item.quantity || item.qty || 1,
      specs: item.specs,
      remark: item.remark,
    }))
}

function normalizeMemberLevel(v1Level: string | undefined): MemberLevel {
  const levelMap: Record<string, MemberLevel> = {
    normal: 'bronze',
    bronze: 'bronze',
    silver: 'silver',
    gold: 'gold',
    diamond: 'diamond',
  }
  return levelMap[(v1Level || '').toLowerCase()] || 'bronze'
}

function convertUserPreferences(v1Settings: V1Settings | null): Partial<UserPreferences> {
  if (!v1Settings) return {}
  return {
    spicy: v1Settings.spicy || '',
    sweet: v1Settings.sweet || '',
    allergies: v1Settings.allergies || v1Settings.allergens || [],
  }
}

// ─── Main migration function ─────────────────────────────────────────────────

/**
 * Migrate v1 data to v2 stores. Call once during app startup.
 * Returns true if migration was performed, false if already migrated or no data.
 */
export function migrateFromV1IfNeeded(): boolean {
  // Skip if already migrated
  if (isMigrated()) {
    return false
  }

  let didMigrate = false

  // ─── 1. Cart ───────────────────────────────────────────────────────────────

  const v1Cart = readJSON<V1CartItem[]>('tx_cart')
  if (v1Cart && Array.isArray(v1Cart) && v1Cart.length > 0) {
    const v2Items = convertCartItems(v1Cart)
    if (v2Items.length > 0) {
      const cartStore = useCartStore.getState()
      for (const item of v2Items) {
        cartStore.addItem(item)
      }
      didMigrate = true
    }
  }

  // ─── 2. User profile ──────────────────────────────────────────────────────

  const v1Profile = readJSON<V1UserProfile>('tx_user_profile')
  const v1Token = readString('tx_token')
  const v1UserId = readString('tx_user_id')

  if (v1Profile || v1Token) {
    const userStore = useUserStore.getState()
    const level = normalizeMemberLevel(v1Profile?.level || v1Profile?.member_level)
    const points = v1Profile?.points_balance ?? v1Profile?.pointsBalance ?? 0
    const storedValue = v1Profile?.stored_value_fen ?? v1Profile?.balance_fen ?? v1Profile?.balanceFen ?? 0

    userStore.setUser({
      userId: v1UserId || '',
      nickname: v1Profile?.nickname || '',
      avatarUrl: v1Profile?.avatarUrl || v1Profile?.avatar_url || '',
      phone: v1Profile?.phone || '',
      memberLevel: level,
      pointsBalance: points,
      storedValueFen: storedValue,
    })
    didMigrate = true
  }

  // ─── 3. User preferences / settings ────────────────────────────────────────

  const v1Settings = readJSON<V1Settings>('tx_settings')
  if (v1Settings) {
    const prefs = convertUserPreferences(v1Settings)
    if (Object.keys(prefs).length > 0) {
      useUserStore.getState().updatePreferences(prefs)
      didMigrate = true
    }
  }

  // ─── 4. Store info ─────────────────────────────────────────────────────────

  const v1StoreId = readString('tx_store_id')
  if (v1StoreId) {
    const storeInfoState = useStoreInfo.getState()
    if (storeInfoState.setStoreId) {
      storeInfoState.setStoreId(v1StoreId)
    }
    didMigrate = true
  }

  // ─── 5. Auth tokens (keep as-is, v2 reads from same keys) ─────────────────
  // tx_token, tx_user_id, tx_tenant_id, tx_api_base are already in storage
  // and v2's request.ts reads them directly — no conversion needed.

  // ─── Mark migration complete ───────────────────────────────────────────────

  if (didMigrate) {
    try {
      Taro.setStorageSync(MIGRATION_FLAG, true)
    } catch (_) {
      // Storage write failure — migration will retry next launch
    }
  } else {
    // Even if no v1 data found, mark as migrated so we don't keep checking
    try {
      Taro.setStorageSync(MIGRATION_FLAG, true)
    } catch (_) {
      // noop
    }
  }

  return didMigrate
}

/**
 * Reset migration flag (for testing / debugging only).
 * Forces re-migration on next app launch.
 */
export function resetMigrationFlag(): void {
  try {
    Taro.removeStorageSync(MIGRATION_FLAG)
  } catch (_) {
    // noop
  }
}
