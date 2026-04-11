/**
 * 订单状态管理 — Zustand
 */
import { create } from 'zustand';

export interface OrderItem {
  id: string;
  dishId: string;
  name: string;
  quantity: number;
  priceFen: number;
  notes: string;
  kitchenStation: string;
}

interface OrderState {
  orderId: string | null;
  orderNo: string | null;
  tableNo: string;
  items: OrderItem[];
  totalFen: number;
  discountFen: number;

  // Actions
  setOrder: (orderId: string, orderNo: string, tableNo: string) => void;
  addItem: (item: Omit<OrderItem, 'id'>) => void;
  removeItem: (id: string) => void;
  updateQuantity: (id: string, qty: number) => void;
  applyDiscount: (fen: number) => void;
  clear: () => void;
}

let itemCounter = 0;

export const useOrderStore = create<OrderState>((set, _get) => ({
  orderId: null,
  orderNo: null,
  tableNo: '',
  items: [],
  totalFen: 0,
  discountFen: 0,

  setOrder: (orderId, orderNo, tableNo) => set({ orderId, orderNo, tableNo }),

  addItem: (item) => set((state) => {
    const newItem = { ...item, id: `item_${++itemCounter}` };
    const items = [...state.items, newItem];
    return { items, totalFen: items.reduce((s, i) => s + i.priceFen * i.quantity, 0) };
  }),

  removeItem: (id) => set((state) => {
    const items = state.items.filter((i) => i.id !== id);
    return { items, totalFen: items.reduce((s, i) => s + i.priceFen * i.quantity, 0) };
  }),

  updateQuantity: (id, qty) => set((state) => {
    const items = state.items.map((i) => i.id === id ? { ...i, quantity: qty } : i);
    return { items, totalFen: items.reduce((s, i) => s + i.priceFen * i.quantity, 0) };
  }),

  applyDiscount: (fen) => set({ discountFen: fen }),

  clear: () => set({ orderId: null, orderNo: null, tableNo: '', items: [], totalFen: 0, discountFen: 0 }),
}));
