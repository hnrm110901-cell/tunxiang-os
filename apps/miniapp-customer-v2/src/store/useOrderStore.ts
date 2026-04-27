import { create } from 'zustand'

// ─── Types ──────────────────────────────────────────────────────────────────

export type OrderStatus =
  | 'pending'
  | 'paid'
  | 'preparing'
  | 'ready'
  | 'delivered'
  | 'cancelled'

export interface OrderItem {
  dishId: string
  name: string
  quantity: number
  price_fen: number
  specs?: Record<string, string>
  remark?: string
}

export interface Order {
  id: string
  status: OrderStatus
  items: OrderItem[]
  total_fen: number
  discount_fen: number
  final_fen: number
  created_at: string
  store_name: string
  table_no: string
}

/** Function signature for polling: receives orderId, returns Promise<Order | null> */
type FetchOrderFn = (orderId: string) => Promise<Order | null>

/** Terminal statuses — polling stops when one of these is reached. */
const TERMINAL_STATUSES: ReadonlySet<OrderStatus> = new Set(['delivered', 'cancelled'])

const POLL_INTERVAL_MS = 5_000

interface OrderState {
  currentOrder: Order | null
  orderList: Order[]
  isPolling: boolean
  pollTimer: ReturnType<typeof setInterval> | null
}

interface OrderActions {
  setCurrentOrder: (order: Order | null) => void
  setOrderList: (orders: Order[]) => void
  updateOrderStatus: (orderId: string, status: OrderStatus) => void
  startPolling: (orderId: string, fetchFn: FetchOrderFn) => void
  stopPolling: () => void
}

type OrderStore = OrderState & OrderActions

// ─── Store ───────────────────────────────────────────────────────────────────

export const useOrderStore = create<OrderStore>()((set, get) => ({
  // state
  currentOrder: null,
  orderList: [],
  isPolling: false,
  pollTimer: null,

  // actions
  setCurrentOrder(order) {
    set({ currentOrder: order })
  },

  setOrderList(orders) {
    set({ orderList: orders })
  },

  updateOrderStatus(orderId, status) {
    set((state) => {
      const currentOrder =
        state.currentOrder?.id === orderId
          ? { ...state.currentOrder, status }
          : state.currentOrder

      const orderList = state.orderList.map((o) =>
        o.id === orderId ? { ...o, status } : o,
      )

      return { currentOrder, orderList }
    })
  },

  startPolling(orderId, fetchFn) {
    // Clear any existing poll before starting a new one
    const { pollTimer: existingTimer, stopPolling } = get()
    if (existingTimer !== null) {
      stopPolling()
    }

    set({ isPolling: true })

    const tick = async (): Promise<void> => {
      try {
        const order = await fetchFn(orderId)
        if (order) {
          set((state) => {
            const currentOrder =
              state.currentOrder?.id === orderId ? order : state.currentOrder
            const orderList = state.orderList.map((o) =>
              o.id === orderId ? order : o,
            )
            return { currentOrder, orderList }
          })

          if (TERMINAL_STATUSES.has(order.status)) {
            get().stopPolling()
          }
        }
      } catch (_e) {
        // network errors during polling are non-fatal; the next tick will retry
      }
    }

    // Run first tick immediately, then on interval
    void tick()
    const timer = setInterval(() => { void tick() }, POLL_INTERVAL_MS)
    set({ pollTimer: timer })
  },

  stopPolling() {
    const { pollTimer } = get()
    if (pollTimer !== null) {
      clearInterval(pollTimer)
    }
    set({ isPolling: false, pollTimer: null })
  },
}))
