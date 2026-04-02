/**
 * menu.ts — tx-menu service API (port 8002, accessed via gateway /api/v1/)
 */
import { txRequest } from '../utils/request'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MenuCategory {
  categoryId: string
  name: string
  imageUrl?: string
  sortOrder: number
  isActive: boolean
}

export type DishStatus = 'available' | 'sold_out' | 'off_shelf'

export interface DishSpec {
  specId: string
  specName: string
  /** Price in fen */
  priceFen: number
  stock?: number
}

export interface DishSpecGroup {
  groupId: string
  groupName: string
  /** Whether customer must pick exactly one option */
  required: boolean
  /** Min/max selections */
  minSelect: number
  maxSelect: number
  specs: DishSpec[]
}

export interface Dish {
  dishId: string
  storeId: string
  categoryId: string
  name: string
  description?: string
  imageUrl?: string
  /** Base price in fen (before spec selection) */
  basePriceFen: number
  status: DishStatus
  tags?: string[]
  salesCount?: number
  /** Whether this dish has spec groups */
  hasSpecs: boolean
  specGroups?: DishSpecGroup[]
  sortOrder: number
  isActive: boolean
}

export interface ComboItem {
  dishId: string
  dishName: string
  quantity: number
  specId?: string
  specName?: string
}

export interface Combo {
  comboId: string
  storeId: string
  name: string
  description?: string
  imageUrl?: string
  /** Combo price in fen */
  priceFen: number
  /** Original sum of items in fen */
  originalPriceFen: number
  items: ComboItem[]
  status: DishStatus
  validFrom?: string
  validUntil?: string
  isActive: boolean
}

export interface DishSearchResult {
  items: Dish[]
  keyword: string
  total: number
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

const BASE = '/api/v1'

/** Get all menu categories for a store */
export async function getCategories(storeId: string): Promise<MenuCategory[]> {
  return txRequest<MenuCategory[]>(`${BASE}/menu/categories?store_id=${encodeURIComponent(storeId)}`)
}

/** Get dishes for a store, optionally filtered by category */
export async function getDishes(storeId: string, categoryId?: string): Promise<Dish[]> {
  const params: Record<string, string> = { store_id: storeId }
  if (categoryId) params['category_id'] = categoryId
  const qs = buildQuery(params)
  return txRequest<Dish[]>(`${BASE}/menu/dishes${qs}`)
}

/** Get a single dish by ID */
export async function getDish(dishId: string): Promise<Dish> {
  return txRequest<Dish>(`${BASE}/menu/dishes/${encodeURIComponent(dishId)}`)
}

/** Get a combo by ID */
export async function getCombo(comboId: string): Promise<Combo> {
  return txRequest<Combo>(`${BASE}/menu/combos/${encodeURIComponent(comboId)}`)
}

/** Full-text search dishes by keyword */
export async function searchDishes(storeId: string, keyword: string): Promise<DishSearchResult> {
  const qs = buildQuery({ store_id: storeId, q: keyword })
  return txRequest<DishSearchResult>(`${BASE}/menu/dishes/search${qs}`)
}

/** Get spec groups for a dish */
export async function getDishSpecs(dishId: string): Promise<DishSpecGroup[]> {
  return txRequest<DishSpecGroup[]>(
    `${BASE}/menu/dishes/${encodeURIComponent(dishId)}/specs`,
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, string>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== '')
  if (entries.length === 0) return ''
  return '?' + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&')
}
