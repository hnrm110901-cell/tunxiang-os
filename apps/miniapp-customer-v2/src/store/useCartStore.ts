import { create } from 'zustand'
import Taro from '@tarojs/taro'

const CART_STORAGE_KEY = 'tx_cart'

// ─── Types ──────────────────────────────────────────────────────────────────

export interface CartItemSpecs {
  [key: string]: string
}

export interface CartItem {
  dishId: string
  name: string
  price_fen: number
  quantity: number
  specs?: CartItemSpecs
  remark?: string
}

interface CartState {
  items: CartItem[]
  storeId: string
  totalFen: number
  totalCount: number
  discountFen: number
}

interface CartActions {
  addItem: (
    dish: Pick<CartItem, 'dishId' | 'name' | 'price_fen'>,
    specs?: CartItemSpecs,
  ) => void
  removeItem: (dishId: string, specs?: CartItemSpecs) => void
  updateRemark: (dishId: string, remark: string) => void
  clearCart: () => void
  setDiscount: (fen: number) => void
  setStoreId: (id: string) => void
}

type CartStore = CartState & CartActions

// ─── Helpers ─────────────────────────────────────────────────────────────────

/** Stable key that identifies a unique cart line (dish + specs combo). */
function lineKey(dishId: string, specs?: CartItemSpecs): string {
  if (!specs || Object.keys(specs).length === 0) return dishId
  const sorted = Object.keys(specs)
    .sort()
    .map((k) => `${k}:${specs[k]}`)
    .join('|')
  return `${dishId}__${sorted}`
}

function isSameLine(item: CartItem, dishId: string, specs?: CartItemSpecs): boolean {
  return lineKey(item.dishId, item.specs) === lineKey(dishId, specs)
}

function computeTotals(items: CartItem[]): { totalFen: number; totalCount: number } {
  return items.reduce(
    (acc, item) => ({
      totalFen: acc.totalFen + item.price_fen * item.quantity,
      totalCount: acc.totalCount + item.quantity,
    }),
    { totalFen: 0, totalCount: 0 },
  )
}

function persist(items: CartItem[]): void {
  try {
    Taro.setStorageSync(CART_STORAGE_KEY, JSON.stringify(items))
  } catch (_e) {
    // storage errors must not crash the app
  }
}

function restore(): CartItem[] {
  try {
    const raw = Taro.getStorageSync(CART_STORAGE_KEY)
    if (typeof raw === 'string' && raw.length > 0) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed as CartItem[]
    }
  } catch (_e) {
    // corrupted storage — start fresh
  }
  return []
}

// ─── Initial state from storage ──────────────────────────────────────────────

const restoredItems = restore()
const { totalFen: initTotalFen, totalCount: initTotalCount } = computeTotals(restoredItems)

// ─── Store ───────────────────────────────────────────────────────────────────

export const useCartStore = create<CartStore>()((set, _get) => ({
  // state
  items: restoredItems,
  storeId: '',
  totalFen: initTotalFen,
  totalCount: initTotalCount,
  discountFen: 0,

  // actions
  addItem(dish, specs) {
    set((state) => {
      const existing = state.items.find((i) => isSameLine(i, dish.dishId, specs))
      let nextItems: CartItem[]

      if (existing) {
        nextItems = state.items.map((i) =>
          isSameLine(i, dish.dishId, specs) ? { ...i, quantity: i.quantity + 1 } : i,
        )
      } else {
        nextItems = [
          ...state.items,
          { dishId: dish.dishId, name: dish.name, price_fen: dish.price_fen, quantity: 1, specs },
        ]
      }

      persist(nextItems)
      return { items: nextItems, ...computeTotals(nextItems) }
    })
  },

  removeItem(dishId, specs) {
    set((state) => {
      const existing = state.items.find((i) => isSameLine(i, dishId, specs))
      if (!existing) return state

      let nextItems: CartItem[]
      if (existing.quantity <= 1) {
        nextItems = state.items.filter((i) => !isSameLine(i, dishId, specs))
      } else {
        nextItems = state.items.map((i) =>
          isSameLine(i, dishId, specs) ? { ...i, quantity: i.quantity - 1 } : i,
        )
      }

      persist(nextItems)
      return { items: nextItems, ...computeTotals(nextItems) }
    })
  },

  updateRemark(dishId, remark) {
    set((state) => {
      const nextItems = state.items.map((i) =>
        i.dishId === dishId ? { ...i, remark } : i,
      )
      persist(nextItems)
      return { items: nextItems }
    })
  },

  clearCart() {
    persist([])
    set({ items: [], totalFen: 0, totalCount: 0, discountFen: 0 })
  },

  setDiscount(fen) {
    set({ discountFen: fen })
  },

  setStoreId(id) {
    set({ storeId: id })
  },
}))
