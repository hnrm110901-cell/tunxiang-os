import { txFetch } from './index';

/* ---- 类型定义 ---- */

export interface Category {
  id: string;
  name: string;
  icon?: string;
  sortOrder: number;
}

export interface DishTag {
  type: 'signature' | 'new' | 'spicy1' | 'spicy2' | 'spicy3' | 'seasonal';
  label: string;
}

export interface Allergen {
  code: string;        // e.g. 'gluten', 'shellfish', 'peanut'
  name: string;
  icon: string;
}

export interface NutritionInfo {
  calories: number;    // kcal
  protein: number;     // g
  fat: number;         // g
}

export interface Traceability {
  origin: string;
  supplier: string;
  arrivalDate: string; // ISO date
}

export interface CustomOption {
  groupName: string;   // e.g. '辣度', '份量'
  required: boolean;
  maxSelect: number;
  items: {
    id: string;
    name: string;
    priceAdjust: number; // 0 = 无加价
  }[];
}

export interface DishItem {
  id: string;
  name: string;
  categoryId: string;
  description: string;
  price: number;
  memberPrice?: number;
  images: string[];
  tags: DishTag[];
  allergens: Allergen[];
  nutrition?: NutritionInfo;
  traceability?: Traceability;
  customOptions: CustomOption[];
  soldOut: boolean;
  sortOrder: number;
}

export interface AiRecommendation {
  dishId: string;
  dish: DishItem;
  reason: string;
}

/* ---- API 函数 ---- */

export function fetchCategories(storeId: string) {
  return txFetch<Category[]>(`/stores/${storeId}/categories`);
}

export function fetchDishes(storeId: string, categoryId?: string) {
  const query = categoryId ? `?categoryId=${categoryId}` : '';
  return txFetch<DishItem[]>(`/stores/${storeId}/dishes${query}`);
}

export function fetchDishDetail(storeId: string, dishId: string) {
  return txFetch<DishItem>(`/stores/${storeId}/dishes/${dishId}`);
}

export function fetchAiRecommendations(storeId: string, cartDishIds: string[]) {
  return txFetch<AiRecommendation[]>(`/stores/${storeId}/ai-recommend`, {
    method: 'POST',
    body: JSON.stringify({ cartDishIds }),
  });
}

export function searchDishes(storeId: string, keyword: string) {
  return txFetch<DishItem[]>(`/stores/${storeId}/dishes/search?q=${encodeURIComponent(keyword)}`);
}
