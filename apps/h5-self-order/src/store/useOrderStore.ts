import { create } from 'zustand';
import type { DishItem } from '@/api/menuApi';

/* ---- 购物车条目 ---- */
export interface CartItem {
  cartKey: string;        // dishId + customHash 组合唯一键
  dish: DishItem;
  quantity: number;
  customSelections: Record<string, string[]>; // groupName -> selected item ids
  remark: string;
  subtotal: number;
}

/* ---- Store 状态 ---- */
interface OrderState {
  // 门店信息（扫码后填入）
  storeId: string;
  storeName: string;
  tableNo: string;
  tenantId: string;
  templateType: 'hotpot' | 'quick' | 'tea' | 'default';

  // 购物车
  cart: CartItem[];
  remark: string;

  // AA分摊
  aaPeople: number;

  // 用户手机号
  phone: string;

  // Actions
  setStoreInfo: (info: { storeId: string; storeName: string; tableNo: string; tenantId: string; templateType?: 'hotpot' | 'quick' | 'tea' | 'default' }) => void;
  addToCart: (dish: DishItem, quantity: number, customSelections: Record<string, string[]>) => void;
  updateQuantity: (cartKey: string, quantity: number) => void;
  removeFromCart: (cartKey: string) => void;
  clearCart: () => void;
  setRemark: (remark: string) => void;
  setAaPeople: (count: number) => void;
  setPhone: (phone: string) => void;

  // Computed-like getters
  cartCount: () => number;
  cartTotal: () => number;
  perPersonAmount: () => number;
}

function buildCartKey(dishId: string, selections: Record<string, string[]>): string {
  const selStr = Object.entries(selections)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}:${v.sort().join(',')}`)
    .join('|');
  return `${dishId}__${selStr}`;
}

function calcSubtotal(dish: DishItem, quantity: number, selections: Record<string, string[]>): number {
  let unitPrice = dish.price;
  // 加价选项
  for (const opt of dish.customOptions) {
    const selected = selections[opt.groupName] ?? [];
    for (const item of opt.items) {
      if (selected.includes(item.id)) {
        unitPrice += item.priceAdjust;
      }
    }
  }
  return unitPrice * quantity;
}

export const useOrderStore = create<OrderState>()((set, get) => ({
  storeId: '',
  storeName: '',
  tableNo: '',
  tenantId: '',
  templateType: 'default',
  cart: [],
  remark: '',
  aaPeople: 1,
  phone: '',

  setStoreInfo: (info) => set({ ...info, templateType: info.templateType ?? 'default' }),

  addToCart: (dish, quantity, customSelections) => {
    const key = buildCartKey(dish.id, customSelections);
    const cart = [...get().cart];
    const idx = cart.findIndex((c) => c.cartKey === key);
    if (idx >= 0) {
      cart[idx] = {
        ...cart[idx],
        quantity: cart[idx].quantity + quantity,
        subtotal: calcSubtotal(dish, cart[idx].quantity + quantity, customSelections),
      };
    } else {
      cart.push({
        cartKey: key,
        dish,
        quantity,
        customSelections,
        remark: '',
        subtotal: calcSubtotal(dish, quantity, customSelections),
      });
    }
    set({ cart });
  },

  updateQuantity: (cartKey, quantity) => {
    if (quantity <= 0) {
      get().removeFromCart(cartKey);
      return;
    }
    set({
      cart: get().cart.map((c) =>
        c.cartKey === cartKey
          ? { ...c, quantity, subtotal: calcSubtotal(c.dish, quantity, c.customSelections) }
          : c,
      ),
    });
  },

  removeFromCart: (cartKey) => set({ cart: get().cart.filter((c) => c.cartKey !== cartKey) }),
  clearCart: () => set({ cart: [], remark: '' }),
  setRemark: (remark) => set({ remark }),
  setAaPeople: (count) => set({ aaPeople: Math.max(1, count) }),
  setPhone: (phone) => set({ phone }),

  cartCount: () => get().cart.reduce((sum, c) => sum + c.quantity, 0),
  cartTotal: () => get().cart.reduce((sum, c) => sum + c.subtotal, 0),
  perPersonAmount: () => {
    const total = get().cartTotal();
    const people = get().aaPeople;
    return people > 1 ? Math.ceil(total / people) : total;
  },
}));
