/**
 * 过敏原 API — /api/v1/allergens/*  /api/v1/dishes/{id}/allergens
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface AllergenCode {
  allergen_code: string;
  allergen_label: string;
  severity_hint: 'danger' | 'warning';
}

export interface AllergenAlert {
  allergen_code: string;
  allergen_label: string;
  severity: 'danger' | 'warning';
}

export interface DishAllergenResult {
  dish_id: string;
  dish_name: string;
  alerts: AllergenAlert[];
}

// ─── 接口 ───

/** 获取全部支持的过敏原代码和中文标签 */
export async function fetchAllergenCodes(): Promise<{
  items: AllergenCode[];
  total: number;
}> {
  return txFetch('/api/v1/allergens/codes');
}

/** 批量检查菜品列表对某会员是否有过敏风险 */
export async function checkAllergens(
  dishIds: string[],
  memberId: string,
  dishNames?: Record<string, string>,
): Promise<DishAllergenResult[]> {
  return txFetch('/api/v1/allergens/check', {
    method: 'POST',
    body: JSON.stringify({
      dish_ids: dishIds,
      member_id: memberId,
      dish_names: dishNames ?? {},
    }),
  });
}

/** 获取菜品的过敏原标签列表（管理端用） */
export async function fetchDishAllergens(dishId: string): Promise<{
  dish_id: string;
  items: Array<{ allergen_code: string; allergen_label: string }>;
  total: number;
}> {
  return txFetch(`/api/v1/dishes/${encodeURIComponent(dishId)}/allergens`);
}

/** 设置菜品过敏原（全量替换，管理端用） */
export async function setDishAllergens(
  dishId: string,
  allergenCodes: string[],
): Promise<{ dish_id: string; allergen_codes: string[]; count: number }> {
  return txFetch(`/api/v1/dishes/${encodeURIComponent(dishId)}/allergens`, {
    method: 'POST',
    body: JSON.stringify({ allergen_codes: allergenCodes }),
  });
}
