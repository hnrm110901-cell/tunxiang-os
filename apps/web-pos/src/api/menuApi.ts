/**
 * tx-menu API 客户端 — 菜品/分类/排名
 */

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

async function txFetch<T>(path: string): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { 'X-Tenant-ID': TENANT_ID },
  });
  const json = await resp.json();
  if (!json.ok) throw new Error(json.error?.message || 'API Error');
  return json.data;
}

export interface DishSpecification {
  spec_id: string;
  name: string;
  price_fen: number;
  is_half?: boolean;
}

export interface DishItem {
  id: string;
  name: string;
  priceFen: number;
  category: string;
  kitchenStation: string;
  isAvailable: boolean;
  specifications?: DishSpecification[];
}

export async function fetchDishes(storeId: string): Promise<DishItem[]> {
  try {
    const data = await txFetch<{ items: any[] }>(`/api/v1/menu/dishes?store_id=${storeId}`);
    return (data.items || []).map((d: any) => ({
      id: d.id || d.dish_id,
      name: d.dish_name || d.name,
      priceFen: d.price_fen || 0,
      category: d.category || '',
      kitchenStation: d.kitchen_station || 'default',
      isAvailable: d.is_available !== false,
      specifications: d.specifications || [],
    }));
  } catch {
    return []; // 离线模式返回空
  }
}

export async function fetchCategories(storeId: string): Promise<string[]> {
  try {
    const data = await txFetch<{ categories: any[] }>(`/api/v1/menu/categories?store_id=${storeId}`);
    return (data.categories || []).map((c: any) => c.name || c);
  } catch {
    return [];
  }
}

export async function fetchRanking(storeId: string): Promise<Array<{ dishId: string; dishName: string; rank: number; score: number }>> {
  try {
    const data = await txFetch<{ rankings: any[] }>(`/api/v1/menu/ranking?store_id=${storeId}`);
    return (data.rankings || []).map((r: any) => ({
      dishId: r.dish_id, dishName: r.dish_name, rank: r.rank, score: r.total_score,
    }));
  } catch {
    return [];
  }
}
