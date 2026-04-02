/**
 * useCartStore tests
 *
 * The store module calls Taro.getStorageSync at import-time (to restore the
 * cart) and persists to Taro.setStorageSync on every mutation.  We reset the
 * Zustand store between tests to guarantee isolation.
 */

import Taro from '@tarojs/taro'

// ─── helpers ─────────────────────────────────────────────────────────────────

/** Re-import the store fresh so the module-level restore() call picks up the
 *  mocked storage value that was set before this helper runs. */
function freshStore() {
  jest.resetModules()
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { useCartStore } = require('../../store/useCartStore') as typeof import('../../store/useCartStore')
  return useCartStore
}

const MAPO = { dishId: 'dish-1', name: '麻婆豆腐', price_fen: 2800 }
const GONG  = { dishId: 'dish-2', name: '宫保鸡丁', price_fen: 3600 }

// ─── tests ───────────────────────────────────────────────────────────────────

describe('useCartStore', () => {
  beforeEach(() => {
    // Reset all mock state and return values before every test
    jest.clearAllMocks()
    ;(Taro.getStorageSync as jest.Mock).mockReturnValue('')
  })

  // ── addItem ────────────────────────────────────────────────────────────────

  describe('addItem', () => {
    it('adds a new dish as a single cart line with quantity 1', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)

      const { items, totalCount, totalFen } = store.getState()
      expect(items).toHaveLength(1)
      expect(items[0]).toMatchObject({
        dishId: 'dish-1',
        name: '麻婆豆腐',
        price_fen: 2800,
        quantity: 1,
      })
      expect(totalCount).toBe(1)
      expect(totalFen).toBe(2800)
    })

    it('increments quantity when the same dish (no specs) is added again', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      store.getState().addItem(MAPO)

      const { items, totalCount, totalFen } = store.getState()
      expect(items).toHaveLength(1)
      expect(items[0].quantity).toBe(2)
      expect(totalCount).toBe(2)
      expect(totalFen).toBe(5600)
    })

    it('creates a separate line item when the same dish has different specs', () => {
      const store = freshStore()
      store.getState().addItem(MAPO, { spicy: 'mild' })
      store.getState().addItem(MAPO, { spicy: 'hot' })

      const { items, totalCount } = store.getState()
      expect(items).toHaveLength(2)
      expect(totalCount).toBe(2)
      // each line has qty 1
      expect(items.every((i) => i.quantity === 1)).toBe(true)
    })

    it('increments the matching spec line rather than creating a third', () => {
      const store = freshStore()
      store.getState().addItem(MAPO, { spicy: 'mild' })
      store.getState().addItem(MAPO, { spicy: 'hot' })
      store.getState().addItem(MAPO, { spicy: 'mild' }) // same as first

      const { items, totalCount } = store.getState()
      expect(items).toHaveLength(2)
      expect(totalCount).toBe(3)
      const mildLine = items.find((i) => i.specs?.spicy === 'mild')
      expect(mildLine?.quantity).toBe(2)
    })

    it('calls Taro.setStorageSync after every add', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      store.getState().addItem(GONG)

      expect(Taro.setStorageSync).toHaveBeenCalledTimes(2)
      // Second call should include both items in the JSON
      const lastCall = (Taro.setStorageSync as jest.Mock).mock.calls[1]
      expect(lastCall[0]).toBe('tx_cart')
      const saved = JSON.parse(lastCall[1] as string) as unknown[]
      expect(saved).toHaveLength(2)
    })
  })

  // ── removeItem ─────────────────────────────────────────────────────────────

  describe('removeItem', () => {
    it('decrements quantity when quantity > 1', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      store.getState().addItem(MAPO)
      store.getState().removeItem('dish-1')

      const { items, totalCount } = store.getState()
      expect(items).toHaveLength(1)
      expect(items[0].quantity).toBe(1)
      expect(totalCount).toBe(1)
    })

    it('removes the line entirely when quantity reaches 0', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      store.getState().removeItem('dish-1')

      const { items, totalCount, totalFen } = store.getState()
      expect(items).toHaveLength(0)
      expect(totalCount).toBe(0)
      expect(totalFen).toBe(0)
    })

    it('is a no-op when the dish is not in the cart', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      const before = store.getState().items

      store.getState().removeItem('dish-nonexistent')

      expect(store.getState().items).toBe(before) // reference unchanged
    })

    it('respects specs when removing — only removes the matching spec line', () => {
      const store = freshStore()
      store.getState().addItem(MAPO, { spicy: 'mild' })
      store.getState().addItem(MAPO, { spicy: 'hot' })
      store.getState().removeItem('dish-1', { spicy: 'mild' })

      const { items } = store.getState()
      expect(items).toHaveLength(1)
      expect(items[0].specs?.spicy).toBe('hot')
    })

    it('calls Taro.setStorageSync after remove', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      jest.clearAllMocks()
      store.getState().removeItem('dish-1')

      expect(Taro.setStorageSync).toHaveBeenCalledTimes(1)
    })
  })

  // ── clearCart ──────────────────────────────────────────────────────────────

  describe('clearCart', () => {
    it('empties all items and resets totals to zero', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      store.getState().addItem(GONG)
      store.getState().clearCart()

      const { items, totalFen, totalCount, discountFen } = store.getState()
      expect(items).toHaveLength(0)
      expect(totalFen).toBe(0)
      expect(totalCount).toBe(0)
      expect(discountFen).toBe(0)
    })

    it('persists empty array to storage', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      jest.clearAllMocks()
      store.getState().clearCart()

      expect(Taro.setStorageSync).toHaveBeenCalledWith('tx_cart', '[]')
    })
  })

  // ── totalFen ───────────────────────────────────────────────────────────────

  describe('totalFen', () => {
    it('computes the correct sum: price × quantity across all lines', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)        // 1 × 2800 = 2800
      store.getState().addItem(MAPO)        // 2 × 2800 = 5600
      store.getState().addItem(GONG)        // 1 × 3600 = 3600
      store.getState().addItem(GONG)        // 2 × 3600 = 7200
      store.getState().addItem(GONG)        // 3 × 3600 = 10800

      expect(store.getState().totalFen).toBe(5600 + 10800) // 16400
    })
  })

  // ── totalCount ─────────────────────────────────────────────────────────────

  describe('totalCount', () => {
    it('is the sum of quantities across all lines', () => {
      const store = freshStore()
      store.getState().addItem(MAPO)
      store.getState().addItem(MAPO)
      store.getState().addItem(GONG)

      expect(store.getState().totalCount).toBe(3)
    })

    it('is 0 for an empty cart', () => {
      const store = freshStore()
      expect(store.getState().totalCount).toBe(0)
    })
  })

  // ── setDiscount ────────────────────────────────────────────────────────────

  describe('setDiscount', () => {
    it('updates discountFen', () => {
      const store = freshStore()
      store.getState().setDiscount(500)
      expect(store.getState().discountFen).toBe(500)
    })

    it('can be set to 0 to clear the discount', () => {
      const store = freshStore()
      store.getState().setDiscount(500)
      store.getState().setDiscount(0)
      expect(store.getState().discountFen).toBe(0)
    })
  })

  // ── Persistence / restore ──────────────────────────────────────────────────

  describe('persistence', () => {
    it('restores items from storage on module init when storage contains valid JSON', () => {
      const savedItems = [
        { dishId: 'dish-1', name: '麻婆豆腐', price_fen: 2800, quantity: 3 },
      ]
      ;(Taro.getStorageSync as jest.Mock).mockReturnValue(JSON.stringify(savedItems))

      const store = freshStore()
      const { items, totalFen, totalCount } = store.getState()

      expect(items).toHaveLength(1)
      expect(items[0].quantity).toBe(3)
      expect(totalFen).toBe(8400)
      expect(totalCount).toBe(3)
    })

    it('starts with an empty cart when storage contains corrupted JSON', () => {
      ;(Taro.getStorageSync as jest.Mock).mockReturnValue('not-valid-json{{{')

      const store = freshStore()
      expect(store.getState().items).toHaveLength(0)
    })

    it('starts with an empty cart when storage contains a non-array value', () => {
      ;(Taro.getStorageSync as jest.Mock).mockReturnValue(JSON.stringify({ items: [] }))

      const store = freshStore()
      expect(store.getState().items).toHaveLength(0)
    })
  })
})
