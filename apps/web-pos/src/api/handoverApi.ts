/**
 * 收银交班 API — /api/v1/handover/*
 * 获取班次快照、提交交班、查询交班记录
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface ChannelAmount {
  channel: string;
  amount_fen: number;
}

export interface ShiftSnapshot {
  shift_id: string;
  cashier_id: string;
  cashier_name: string;
  start_time: string;
  end_time: string;
  total_orders: number;
  total_revenue_fen: number;
  total_guests: number;
  avg_per_guest_fen: number;
  channels: ChannelAmount[];
  system_cash_fen: number;
}

export interface CashCount {
  denomination: string;
  count: number;
  subtotal_fen: number;
}

export interface HandoverSubmitPayload {
  shift_id: string;
  store_id: string;
  cashier_id: string;
  cash_counts: CashCount[];
  actual_cash_fen: number;
  diff_fen: number;
  remark: string;
  signed: boolean;
}

export interface HandoverRecord {
  handover_id: string;
  shift_id: string;
  cashier_name: string;
  total_revenue_fen: number;
  actual_cash_fen: number;
  diff_fen: number;
  remark: string;
  submitted_at: string;
}

// ─── 接口 ───

/** 获取当前班次快照（交班前预览） */
export async function fetchShiftSnapshot(
  storeId: string,
  cashierId: string,
): Promise<ShiftSnapshot> {
  return txFetch(
    `/api/v1/handover/snapshot?store_id=${encodeURIComponent(storeId)}&cashier_id=${encodeURIComponent(cashierId)}`,
  );
}

/** 提交交班 */
export async function submitHandover(
  payload: HandoverSubmitPayload,
): Promise<{ handover_id: string; submitted_at: string }> {
  return txFetch('/api/v1/handover/submit', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/** 查询交班历史记录 */
export async function fetchHandoverRecords(
  storeId: string,
  page = 1,
  size = 20,
): Promise<{ items: HandoverRecord[]; total: number }> {
  return txFetch(
    `/api/v1/handover/records?store_id=${encodeURIComponent(storeId)}&page=${page}&size=${size}`,
  );
}

/** 获取单条交班详情 */
export async function getHandoverDetail(
  handoverId: string,
): Promise<HandoverRecord & { cash_counts: CashCount[]; channels: ChannelAmount[] }> {
  return txFetch(`/api/v1/handover/${encodeURIComponent(handoverId)}`);
}
