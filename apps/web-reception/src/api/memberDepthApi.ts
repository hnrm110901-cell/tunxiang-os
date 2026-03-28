/**
 * 客户识别 API — /api/v1/member/depth/*
 * 深度客户画像：VIP识别、历史偏好、过敏忌口、常点菜、宴请记录
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface CustomerProfile {
  member_id: string;
  name: string;
  phone: string;
  is_vip: boolean;
  vip_level: string;
  total_visits: number;
  total_spend_fen: number;
  last_visit: string;
  last_spend_fen: number;
  preferences: string[];
  allergies: string[];
  favorite_items: string[];
  favorite_seat: string;
  drink_preference: string;
  notes: string;
}

export type BanquetType = 'business' | 'family' | 'celebration' | 'other';

export interface BanquetRecord {
  banquet_id: string;
  customer_name: string;
  banquet_type: BanquetType;
  guest_count: number;
  date: string;
  room: string;
  spend_fen: number;
  notes: string;
}

export interface VIPAlert {
  alert_id: string;
  member_id: string;
  customer_name: string;
  vip_level: string;
  alert_type: 'arrival' | 'birthday' | 'anniversary' | 'long_absence';
  message: string;
  created_at: string;
  acknowledged: boolean;
}

// ─── 接口 ───

/** 搜索客户（手机号/姓名/预订码） */
export async function searchCustomer(
  keyword: string,
): Promise<{ items: CustomerProfile[] }> {
  return txFetch(`/api/v1/member/depth/search?keyword=${encodeURIComponent(keyword)}`);
}

/** 获取客户深度画像 */
export async function getCustomerProfile(
  memberId: string,
): Promise<CustomerProfile> {
  return txFetch(`/api/v1/member/depth/${encodeURIComponent(memberId)}`);
}

/** 获取客户宴请记录 */
export async function fetchBanquetHistory(
  memberId: string,
  page = 1,
  size = 10,
): Promise<{ items: BanquetRecord[]; total: number }> {
  return txFetch(
    `/api/v1/member/depth/${encodeURIComponent(memberId)}/banquets?page=${page}&size=${size}`,
  );
}

/** 获取 VIP 到店提醒列表 */
export async function fetchVIPAlerts(
  storeId: string,
): Promise<{ items: VIPAlert[] }> {
  return txFetch(`/api/v1/member/depth/vip-alerts?store_id=${encodeURIComponent(storeId)}`);
}

/** 确认 VIP 提醒已处理 */
export async function acknowledgeVIPAlert(
  alertId: string,
): Promise<{ alert_id: string; acknowledged: boolean }> {
  return txFetch(`/api/v1/member/depth/vip-alerts/${encodeURIComponent(alertId)}/ack`, {
    method: 'POST',
  });
}

/** 记录客户到店签到 */
export async function checkInCustomer(
  storeId: string,
  memberId: string,
  reservationId?: string,
): Promise<{ check_in_id: string; member_id: string; checked_in_at: string }> {
  return txFetch('/api/v1/member/depth/check-in', {
    method: 'POST',
    body: JSON.stringify({
      store_id: storeId,
      member_id: memberId,
      reservation_id: reservationId,
    }),
  });
}
