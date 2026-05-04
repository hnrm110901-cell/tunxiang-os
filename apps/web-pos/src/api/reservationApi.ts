/**
 * reservationApi.ts — 预订 CRUD API 客户端
 */
import { txFetch } from './index';

// ─── Types ────────────────────────────────────────────────────────────────────

export type ReservationStatus = 'pending' | 'confirmed' | 'seated' | 'cancelled' | 'no_show';
export type TablePref = '靠窗' | '包间' | '户外' | '大厅' | '无所谓';
export type MealPeriod = 'lunch' | 'dinner';

export interface Reservation {
  id: string;
  storeId: string;
  customerName: string;
  contactPhone: string;
  guestCount: number;
  mealPeriod: MealPeriod;
  date: string;          // 'YYYY-MM-DD'
  time: string;          // 'HH:mm'
  tableNo: string;
  tablePref: TablePref;
  notes: string;
  status: ReservationStatus;
  createdAt: string;
}

export interface CreateReservationReq {
  customerName: string;
  contactPhone: string;
  guestCount: number;
  date: string;
  time: string;
  mealPeriod: MealPeriod;
  tablePref?: TablePref;
  tableNo?: string;
  notes?: string;
}

export type UpdateReservationReq = Partial<CreateReservationReq>;

// ─── API Functions ────────────────────────────────────────────────────────────

export async function fetchReservations(storeId: string): Promise<Reservation[]> {
  return txFetch(`/api/v1/trade/reservations?store_id=${encodeURIComponent(storeId)}`);
}

export async function createReservation(storeId: string, data: CreateReservationReq): Promise<Reservation> {
  return txFetch('/api/v1/trade/reservations', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, ...data }),
  });
}

export async function updateReservation(id: string, data: UpdateReservationReq): Promise<Reservation> {
  return txFetch(`/api/v1/trade/reservations/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}

export async function cancelReservation(id: string, reason?: string): Promise<void> {
  return txFetch(`/api/v1/trade/reservations/${id}/cancel`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

export async function confirmArrival(id: string, tableNo: string): Promise<void> {
  return txFetch(`/api/v1/trade/reservations/${id}/arrive`, {
    method: 'POST',
    body: JSON.stringify({ table_no: tableNo }),
  });
}
