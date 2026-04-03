/**
 * 预订 API — /api/v1/reservations/*
 * 预订台账、新增/修改/取消预订、状态更新
 */
import { txFetch } from './index';

// ─── 类型 ───

export type ReservationStatus = 'pending' | 'arrived' | 'seated' | 'cancelled' | 'no_show';

export interface Reservation {
  reservation_id: string;
  reservation_code: string;
  customer_name: string;
  phone: string;
  guest_count: number;
  time_slot: string;
  room_or_table: string;
  special_requests: string;
  status: ReservationStatus;
  is_vip: boolean;
  created_at: string;
}

export interface CreateReservationPayload {
  store_id: string;
  customer_name: string;
  phone: string;
  guest_count: number;
  time_slot: string;
  room_or_table: string;
  special_requests?: string;
}

// ─── 接口 ───

/** 获取今日预订列表 */
export async function fetchReservations(
  storeId: string,
  date?: string,
): Promise<{ items: Reservation[]; total: number }> {
  const dateParam = date ? `&date=${encodeURIComponent(date)}` : '';
  return txFetch(`/api/v1/reservations?store_id=${encodeURIComponent(storeId)}${dateParam}`);
}

/** 新增预订 */
export async function createReservation(
  payload: CreateReservationPayload,
): Promise<{ reservation_id: string; reservation_code: string }> {
  return txFetch('/api/v1/reservations', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 更新预订状态（到店/入座/取消） */
export async function updateReservationStatus(
  reservationId: string,
  status: ReservationStatus,
): Promise<{ reservation_id: string; status: ReservationStatus }> {
  return txFetch(`/api/v1/reservations/${encodeURIComponent(reservationId)}/status`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
}

/** 修改预订信息 */
export async function updateReservation(
  reservationId: string,
  updates: Partial<CreateReservationPayload>,
): Promise<Reservation> {
  return txFetch(`/api/v1/reservations/${encodeURIComponent(reservationId)}`, {
    method: 'PUT',
    body: JSON.stringify(updates),
  });
}

/** 获取单个预订详情 */
export async function getReservationDetail(
  reservationId: string,
): Promise<Reservation> {
  return txFetch(`/api/v1/reservations/${encodeURIComponent(reservationId)}`);
}

/** 通过预订码查询 */
export async function findByCode(
  code: string,
): Promise<Reservation> {
  return txFetch(`/api/v1/reservations/by-code?code=${encodeURIComponent(code)}`);
}
