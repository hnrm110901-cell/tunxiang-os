/**
 * 桌台 API — /api/v1/tables/*
 * 桌台状态、分配入座、按区域查询
 */
import { txFetch } from './index';

// ─── 类型 ───

export type TableStatus = 'available' | 'occupied' | 'reserved' | 'cleaning';

export interface TableInfo {
  table_id: string;
  table_name: string;
  zone: string;
  capacity: number;
  status: TableStatus;
  guest_name: string | null;
  guest_count: number | null;
  occupied_since: string | null;
  min_spend_fen: number | null;
  is_room: boolean;
}

export interface TableZone {
  zone_id: string;
  zone_name: string;
  total_tables: number;
  available_tables: number;
}

// ─── 接口 ───

/** 获取全部桌台（含状态） */
export async function fetchTables(
  storeId: string,
  zone?: string,
): Promise<{ items: TableInfo[]; total: number }> {
  const zoneParam = zone ? `&zone=${encodeURIComponent(zone)}` : '';
  return txFetch(`/api/v1/tables?store_id=${encodeURIComponent(storeId)}${zoneParam}`);
}

/** 获取区域列表及统计 */
export async function fetchTableZones(
  storeId: string,
): Promise<{ items: TableZone[] }> {
  return txFetch(`/api/v1/tables/zones?store_id=${encodeURIComponent(storeId)}`);
}

/** 分配入座 */
export async function seatAtTable(
  storeId: string,
  tableId: string,
  guestCount: number,
  guestName?: string,
  reservationId?: string,
): Promise<{ table_id: string; order_id: string; status: TableStatus }> {
  return txFetch('/api/v1/tables/seat', {
    method: 'POST',
    body: JSON.stringify({
      store_id: storeId,
      table_id: tableId,
      guest_count: guestCount,
      guest_name: guestName,
      reservation_id: reservationId,
    }),
  });
}

/** 智能推荐桌台（根据人数、偏好） */
export async function recommendTable(
  storeId: string,
  guestCount: number,
  preferences?: string[],
): Promise<{ items: Array<{ table_id: string; table_name: string; zone: string; score: number; reason: string }> }> {
  return txFetch('/api/v1/tables/recommend', {
    method: 'POST',
    body: JSON.stringify({
      store_id: storeId,
      guest_count: guestCount,
      preferences,
    }),
  });
}

/** 清台 */
export async function clearTable(
  storeId: string,
  tableId: string,
): Promise<{ table_id: string; status: TableStatus }> {
  return txFetch('/api/v1/tables/clear', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_id: tableId }),
  });
}
