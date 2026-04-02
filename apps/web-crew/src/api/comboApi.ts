/**
 * 套餐N选M — API 类型定义与请求函数
 * 对应后端: GET /api/v1/menu/combos/{combo_id}/detail
 */

import { txFetch } from './index';

// ─── 类型定义 ───

export interface ComboGroupItem {
  item_id: string;
  dish_id: string;
  dish_name: string;
  extra_price_fen: number;  // 加价（分），0=不加价
  is_default: boolean;
  image_url?: string;
  sold_out: boolean;
}

export interface ComboGroup {
  group_id: string;
  group_name: string;       // 如"主菜（任选2款）"
  min_select: number;
  max_select: number;
  is_required: boolean;
  items: ComboGroupItem[];
}

export interface ComboDetail {
  combo_id: string;
  combo_name: string;
  price_fen: number;
  description: string;
  min_person?: number;
  image_url?: string;
  groups: ComboGroup[];
}

/** 用户在某个分组的选择 */
export interface ComboSelection {
  group_id: string;
  group_name: string;
  selected_items: Array<{
    dish_id: string;
    dish_name: string;
    extra_price_fen: number;
  }>;
}

// ─── API 函数 ───

/**
 * 获取套餐N选M完整结构（分组 + 可选菜品）
 * TODO: 后端目前返回 Mock 数据，待 combo_groups/combo_group_items 表接入后自动生效
 */
export async function fetchComboDetail(comboId: string): Promise<ComboDetail> {
  return txFetch<ComboDetail>(`/api/v1/menu/combos/${encodeURIComponent(comboId)}/detail`);
}
