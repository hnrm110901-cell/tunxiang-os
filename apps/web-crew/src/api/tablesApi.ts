/**
 * 桌台操作 API — /api/v1/tables/*
 * 开台、清台、转台、并台、桌台状态
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface TableInfo {
  table_no: string;
  zone: string;
  capacity: number;
  status: 'idle' | 'occupied' | 'reserved' | 'cleaning';
  guest_count: number;
  order_id: string | null;
  seated_at: string | null;
}

// ─── 接口 ───

/** 获取所有桌台状态 */
export async function fetchTables(
  storeId: string,
): Promise<{ items: TableInfo[]; total: number }> {
  return txFetch(`/api/v1/tables?store_id=${encodeURIComponent(storeId)}`);
}

/** 开台 */
export async function openTable(
  storeId: string,
  tableNo: string,
  guestCount: number,
): Promise<{ table_no: string; order_id: string }> {
  return txFetch('/api/v1/tables/open', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_no: tableNo, guest_count: guestCount }),
  });
}

/** 清台 */
export async function clearTable(
  storeId: string,
  tableNo: string,
): Promise<{ table_no: string; status: string }> {
  return txFetch('/api/v1/tables/clear', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, table_no: tableNo }),
  });
}

/** 转台 */
export async function transferTable(
  storeId: string,
  fromTable: string,
  toTable: string,
): Promise<{ from_table: string; to_table: string }> {
  return txFetch('/api/v1/tables/transfer', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, from_table: fromTable, to_table: toTable }),
  });
}

/** 并台 */
export async function mergeTables(
  storeId: string,
  mainTable: string,
  mergeTableNos: string[],
): Promise<{ main_table: string; merged_tables: string[] }> {
  return txFetch('/api/v1/tables/merge', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, main_table: mainTable, merge_tables: mergeTableNos }),
  });
}

/** 预留桌台 */
export async function reserveTable(
  storeId: string,
  tableNo: string,
  customerName: string,
  reserveTime: string,
): Promise<{ table_no: string; reservation_id: string }> {
  return txFetch('/api/v1/tables/reserve', {
    method: 'POST',
    body: JSON.stringify({
      store_id: storeId,
      table_no: tableNo,
      customer_name: customerName,
      reserve_time: reserveTime,
    }),
  });
}
