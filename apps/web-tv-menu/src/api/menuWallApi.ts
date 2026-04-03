/**
 * 电视点菜墙 — 所有API端点
 * 对应后端: services/tx-trade/src/api/tv_menu_routes.py
 */
import { tvFetch, getStoreId } from './index';

/* ==================== 类型定义 ==================== */

export interface DishItem {
  id: string;
  name: string;
  price: number;
  originalPrice?: number;
  memberPrice?: number;
  image: string;
  category: string;
  description?: string;
  tags: string[];
  isSoldOut: boolean;
  isRecommended: boolean;
  isMarketPrice: boolean;
  timeSlot?: 'morning_tea' | 'lunch' | 'dinner' | 'late_night';
  salesCount?: number;
  rating?: number;
}

export interface ScreenLayout {
  screenId: number;
  zone: string;
  dishes: DishItem[];
  gridCols: number;
  gridRows: number;
  refreshInterval: number;
}

export interface MenuWallLayout {
  storeId: string;
  storeName: string;
  screens: ScreenLayout[];
  brandLogo?: string;
  brandColor: string;
}

export interface RealtimeStatus {
  soldOutIds: string[];
  updatedPrices: Array<{ dishId: string; newPrice: number }>;
  timestamp: string;
}

export interface TimeRecommendation {
  timeSlot: string;
  label: string;
  dishIds: string[];
}

export interface WeatherRecommendation {
  weather: string;
  label: string;
  dishIds: string[];
}

export interface SmartLayout {
  layout: ScreenLayout[];
  reason: string;
}

export interface SeafoodItem {
  id: string;
  name: string;
  price: number;
  previousPrice: number;
  unit: string;
  status: 'alive' | 'weak' | 'sold_out';
  updatedAt: string;
}

export interface SeafoodBoard {
  items: SeafoodItem[];
  updatedAt: string;
}

export interface RankingItem {
  rank: number;
  dishId: string;
  name: string;
  image?: string;
  value: number;
  label: string;
}

export interface RankingData {
  metric: string;
  metricLabel: string;
  items: RankingItem[];
}

export interface ScreenConfig {
  screens: Array<{
    screenId: string;
    ip: string;
    position: string;
    sizeInches: number;
    zone: string;
    status: 'online' | 'offline';
  }>;
}

export interface ComboItem {
  id: string;
  name: string;
  price: number;
  image: string;
  servesCount: string;
  description: string;
  dishes: Array<{ name: string; quantity: number }>;
}

export interface WaitingInfo {
  waitingTables: number;
  estimatedMinutes: number;
  qrcodeUrl: string;
}

/* ==================== API 调用 ==================== */

/** 获取菜单墙整体布局 */
export function getMenuWallLayout(screens = 4): Promise<MenuWallLayout> {
  const storeId = getStoreId();
  return tvFetch<MenuWallLayout>(`/layout/${storeId}?screens=${screens}`);
}

/** 获取单屏内容 */
export function getScreenContent(screenId: number, zone = 'signature'): Promise<ScreenLayout> {
  const storeId = getStoreId();
  return tvFetch<ScreenLayout>(`/screen/${storeId}/${screenId}?zone=${zone}`);
}

/** 获取实时沽清/变价状态 */
export function getRealtimeStatus(): Promise<RealtimeStatus> {
  const storeId = getStoreId();
  return tvFetch<RealtimeStatus>(`/status/${storeId}`);
}

/** 获取时段推荐 */
export function getTimeRecommendation(): Promise<TimeRecommendation> {
  const storeId = getStoreId();
  return tvFetch<TimeRecommendation>(`/recommend/${storeId}`);
}

/** 获取天气推荐 */
export function getWeatherRecommendation(weather = 'normal'): Promise<WeatherRecommendation> {
  const storeId = getStoreId();
  return tvFetch<WeatherRecommendation>(`/weather/${storeId}?weather=${weather}`);
}

/** 获取AI智能布局 */
export function getSmartLayout(): Promise<SmartLayout> {
  const storeId = getStoreId();
  return tvFetch<SmartLayout>(`/smart-layout/${storeId}`);
}

/** 触发点单(触控模式) */
export function triggerOrder(tableId: string, items: Array<{ dishId: string; qty: number }>, customerId?: string) {
  const storeId = getStoreId();
  return tvFetch('/order', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_id: tableId, items, customer_id: customerId }),
  });
}

/** 注册屏幕 */
export function registerScreen(screenId: string, ip: string, position: string, sizeInches = 55) {
  const storeId = getStoreId();
  return tvFetch('/screen/register', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, screen_id: screenId, ip, position, size_inches: sizeInches }),
  });
}

/** 获取屏幕分组配置 */
export function getScreenGroupConfig(): Promise<ScreenConfig> {
  const storeId = getStoreId();
  return tvFetch<ScreenConfig>(`/config/${storeId}`);
}

/** 获取海鲜时价板 */
export function getSeafoodBoard(): Promise<SeafoodBoard> {
  const storeId = getStoreId();
  return tvFetch<SeafoodBoard>(`/seafood-board/${storeId}`);
}

/** 获取排行榜 */
export function getRankingBoard(metric = 'hot_sales'): Promise<RankingData> {
  const storeId = getStoreId();
  return tvFetch<RankingData>(`/ranking/${storeId}?metric=${metric}`);
}
