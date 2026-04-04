/**
 * 桌台状态管理 — Zustand
 */
import { create } from 'zustand';

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

export interface TableInfo {
  id: string;
  tableNo: string;
  zone: string;
  capacity: number;
  status: string;
  currentOrderId: string | null;
  guestName: string | null;
  guestCount: number;
  occupiedSince: string | null;
}

interface TableState {
  tables: TableInfo[];
  loading: boolean;
  error: string | null;

  // Actions
  fetchTables: (storeId: string) => Promise<void>;
  updateTableStatus: (tableId: string, status: string) => void;
  getTableByNo: (tableNo: string) => TableInfo | undefined;
}

export const useTableStore = create<TableState>((set, get) => ({
  tables: [],
  loading: false,
  error: null,

  fetchTables: async (storeId) => {
    set({ loading: true, error: null });
    try {
      const resp = await fetch(`${BASE}/api/v1/tables/board/${storeId}`, {
        headers: {
          'Content-Type': 'application/json',
          ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
        },
      });
      const json = await resp.json();
      if (!json.ok) throw new Error(json.error?.message || 'Failed to fetch tables');
      const items: unknown[] = json.data?.tables || json.data?.items || [];
      const tables: TableInfo[] = items.map((t: any) => ({
        id: t.id || t.table_id,
        tableNo: t.table_no || t.tableNo || '',
        zone: t.zone || '',
        capacity: t.capacity || 0,
        status: t.status || 'idle',
        currentOrderId: t.current_order_id || null,
        guestName: t.guest_name || null,
        guestCount: t.guest_count || 0,
        occupiedSince: t.occupied_since || null,
      }));
      set({ tables, loading: false });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      set({ error: message, loading: false });
    }
  },

  updateTableStatus: (tableId, status) => set((state) => ({
    tables: state.tables.map((t) =>
      t.id === tableId ? { ...t, status } : t,
    ),
  })),

  getTableByNo: (tableNo) => {
    return get().tables.find((t) => t.tableNo === tableNo);
  },
}));
