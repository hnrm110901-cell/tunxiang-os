/**
 * 活鲜点单 API 客户端
 *
 * 对应后端: tx-menu /api/v1/live-seafood/tanks*
 * 数据来源: v112_xuji_live_seafood 迁移 (fish_tank_zones + dishes 扩展字段)
 */
import { txFetch } from './index';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

/** 计价方式 */
export type PricingMethod = 'weight' | 'count' | 'fixed';

/** 鱼缸区域（含库存摘要） */
export interface TankZone {
  zone_id: string;
  zone_code: string;        // 如 A1 / B2
  zone_name: string;        // 如 石斑鱼缸
  current_stock_count: number;   // 条/头数量（0=无库存）
  current_stock_weight_g: number; // 当前库存克重（0=无库存）
  is_active: boolean;
  featured_dish: string;    // 该缸主要品种名称
  price_display: string;    // 展示价格字符串，如 ¥128/斤
  pricing_method: PricingMethod;
}

/** 活鲜菜品（可点单） */
export interface LiveSeafoodDish {
  dish_id: string;
  dish_name: string;
  pricing_method: PricingMethod;
  price_per_unit_fen: number;    // 单位价格（分）：称重=每斤，计头=每条/头
  display_unit: string;          // 展示单位：斤 / 条 / 头
  weight_unit: string | null;    // 后端称重单位：jin / liang / kg / g
  live_stock_count: number;      // 当前条/头数量
  live_stock_weight_g: number;   // 当前克重
  min_order_qty: number;         // 最小点单量（如 0.5 斤起）
  image_url: string | null;
  price_display: string;         // 展示字符串，如 ¥128/斤
}

/** GET /api/v1/live-seafood/tanks 响应 */
interface TankListResponse {
  tanks: TankZone[];
}

/** GET /api/v1/live-seafood/tanks/{zone_code}/dishes 响应 */
interface TankDishesResponse {
  zone_code: string;
  zone_name: string;
  dishes: LiveSeafoodDish[];
}

// ─── API 函数 ─────────────────────────────────────────────────────────────────

/**
 * 获取门店所有鱼缸区域列表（含库存摘要）
 * 用于鱼缸选品卡片列表展示
 */
export async function fetchTankList(storeId: string): Promise<TankListResponse> {
  return txFetch<TankListResponse>(
    `/api/v1/live-seafood/tanks?store_id=${encodeURIComponent(storeId)}`,
  );
}

/**
 * 获取指定鱼缸区域的可点活鲜菜品
 * @param zoneCode  鱼缸编码，如 "A1"
 * @param storeId   门店 ID
 */
export async function fetchTankDishes(
  zoneCode: string,
  storeId: string,
): Promise<TankDishesResponse> {
  return txFetch<TankDishesResponse>(
    `/api/v1/live-seafood/tanks/${encodeURIComponent(zoneCode)}/dishes?store_id=${encodeURIComponent(storeId)}`,
  );
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

/** 判断鱼缸是否库存紧张（<3条 或 <500g 约1斤） */
export function isTankLowStock(tank: TankZone): boolean {
  if (tank.pricing_method === 'count') {
    return tank.current_stock_count > 0 && tank.current_stock_count < 3;
  }
  // 称重类：低于 500g（约1斤）为紧张
  return tank.current_stock_weight_g > 0 && tank.current_stock_weight_g < 500;
}

/** 判断鱼缸是否无库存 */
export function isTankEmpty(tank: TankZone): boolean {
  return tank.current_stock_count === 0 && tank.current_stock_weight_g === 0;
}

/** 生成鱼缸库存展示文本 */
export function tankStockLabel(tank: TankZone): string {
  if (isTankEmpty(tank)) return '暂无';
  if (tank.pricing_method === 'count') {
    return `${tank.current_stock_count}头在库`;
  }
  const jin = (tank.current_stock_weight_g / 500).toFixed(1);
  return `约${jin}斤`;
}

/** 将 LiveSeafoodDish 转换为 WeighDishSheet 所需的 DishInfo */
export function toWeighDishInfo(dish: LiveSeafoodDish): import('./index').DishInfo {
  return {
    dish_id: dish.dish_id,
    dish_name: dish.dish_name,
    category_id: 'live-seafood',
    // WeighDishSheet 把 price_fen 解读为"每 kg 价格（分）"
    // 活鲜 price_per_unit_fen 是每斤（jin），1斤=0.5kg，所以每kg = price*2
    price_fen: dish.pricing_method === 'weight' ? dish.price_per_unit_fen * 2 : dish.price_per_unit_fen,
    image_url: dish.image_url ?? undefined,
    sold_out: dish.live_stock_count === 0 && dish.live_stock_weight_g === 0,
    is_market_price: false,
    is_weighed: dish.pricing_method === 'weight',
  };
}
