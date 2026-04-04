/**
 * 菜品菜单状态管理 — Zustand
 */
import { create } from 'zustand';

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

export interface DishItem {
  id: string;
  name: string;
  priceFen: number;
  category: string;
  kitchenStation: string;
  isAvailable: boolean;
  pricingMethod: string;
  imageUrl?: string;
}

interface MenuState {
  categories: string[];
  dishes: DishItem[];
  loading: boolean;
  error: string | null;

  // Actions
  fetchMenu: (storeId: string) => Promise<void>;
  getDishesByCategory: (category: string) => DishItem[];
  searchDishes: (query: string) => DishItem[];
  toggleSoldOut: (dishId: string) => void;
}

export const useMenuStore = create<MenuState>((set, get) => ({
  categories: [],
  dishes: [],
  loading: false,
  error: null,

  fetchMenu: async (storeId) => {
    set({ loading: true, error: null });
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
      };

      // Fetch dishes and categories in parallel
      const [dishResp, catResp] = await Promise.all([
        fetch(`${BASE}/api/v1/menu/dishes?store_id=${storeId}`, { headers }),
        fetch(`${BASE}/api/v1/menu/categories?store_id=${storeId}`, { headers }),
      ]);

      const dishJson = await dishResp.json();
      const catJson = await catResp.json();

      if (!dishJson.ok) throw new Error(dishJson.error?.message || 'Failed to fetch dishes');

      const rawItems: unknown[] = dishJson.data?.items || [];
      const dishes: DishItem[] = rawItems.map((d: any) => ({
        id: d.id || d.dish_id,
        name: d.dish_name || d.name,
        priceFen: d.price_fen || 0,
        category: d.category || '',
        kitchenStation: d.kitchen_station || 'default',
        isAvailable: d.is_available !== false,
        pricingMethod: d.pricing_method || 'fixed',
        imageUrl: d.image_url || undefined,
      }));

      const categories: string[] = catJson.ok
        ? (catJson.data?.categories || []).map((c: any) => c.name || c)
        : [...new Set(dishes.map((d) => d.category).filter(Boolean))];

      set({ dishes, categories, loading: false });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      set({ error: message, loading: false });
    }
  },

  getDishesByCategory: (category) => {
    return get().dishes.filter((d) => d.category === category && d.isAvailable);
  },

  searchDishes: (query) => {
    const q = query.toLowerCase();
    return get().dishes.filter(
      (d) => d.isAvailable && (d.name.toLowerCase().includes(q) || d.category.toLowerCase().includes(q)),
    );
  },

  toggleSoldOut: (dishId) => set((state) => ({
    dishes: state.dishes.map((d) =>
      d.id === dishId ? { ...d, isAvailable: !d.isAvailable } : d,
    ),
  })),
}));
