/**
 * 桌台管理状态存储
 * @module stores/tableStore
 */

import { create } from 'zustand';
import {
  TableCardData,
  TableSummary,
  ViewMode,
  TableListResponse,
  ClickTrackPayload,
  ClickTrackResponse,
} from '../types/table-card';

/**
 * 桌台店铺状态
 */
export interface TableStoreState {
  // ==================== State ====================
  /** 桌台列表 */
  tables: TableCardData[];
  /** 汇总统计 */
  summary: TableSummary | null;
  /** 当前用餐时段 */
  mealPeriod: string;
  /** 当前视图模式 */
  viewMode: ViewMode;
  /** 加载中状态 */
  loading: boolean;
  /** 错误消息 */
  error: string | null;
  /** 当前门店ID */
  currentStoreId: string | null;
  /** 状态筛选 (null表示不筛选) */
  statusFilter: string | null;

  // ==================== Actions ====================
  /**
   * 获取指定门店的桌台列表
   * @param storeId 门店ID
   * @param view 视图类型
   */
  fetchTables: (storeId: string, view: ViewMode) => Promise<void>;

  /**
   * 设置当前视图模式
   * @param mode 视图模式
   */
  setViewMode: (mode: ViewMode) => void;

  /**
   * 记录字段点击事件
   * @param storeId 门店ID
   * @param tableNo 桌号
   * @param fieldKey 字段键值
   * @param fieldLabel 字段标签
   */
  trackFieldClick: (
    storeId: string,
    tableNo: string,
    fieldKey: string,
    fieldLabel: string
  ) => Promise<void>;

  /**
   * 设置状态筛选
   * @param status 状态值或null
   */
  setStatusFilter: (status: string | null) => void;

  /**
   * 获取按筛选条件过滤的桌台列表
   */
  getFilteredTables: () => TableCardData[];

  /**
   * 重置状态
   */
  reset: () => void;
}

/**
 * API 基础路径
 */
const API_BASE = '/api/v1';

/**
 * 桌台状态管理 Store
 */
export const useTableStore = create<TableStoreState>((set, get) => ({
  // ==================== Initial State ====================
  tables: [],
  summary: null,
  mealPeriod: '',
  viewMode: 'card',
  loading: false,
  error: null,
  currentStoreId: null,
  statusFilter: null,

  // ==================== Actions ====================
  fetchTables: async (storeId: string, view: ViewMode) => {
    set({ loading: true, error: null, currentStoreId: storeId });

    try {
      const url = `${API_BASE}/tables?store_id=${storeId}&view=${view}`;
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data: TableListResponse = await response.json();

      if (!data.ok) {
        throw new Error('API returned error');
      }

      set({
        tables: data.data.tables,
        summary: data.data.summary,
        mealPeriod: data.data.meal_period,
        viewMode: view,
        loading: false,
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error';
      set({
        error: errorMessage,
        loading: false,
        tables: [],
        summary: null,
      });

      console.error('[TableStore] fetchTables error:', err);
    }
  },

  setViewMode: (mode: ViewMode) => {
    set({ viewMode: mode });

    // 立即重新获取数据
    const state = get();
    if (state.currentStoreId) {
      state.fetchTables(state.currentStoreId, mode);
    }
  },

  trackFieldClick: async (
    storeId: string,
    tableNo: string,
    fieldKey: string,
    fieldLabel: string
  ) => {
    try {
      const payload: ClickTrackPayload = {
        store_id: storeId,
        table_no: tableNo,
        field_key: fieldKey,
        field_label: fieldLabel,
        timestamp: Date.now(),
      };

      const response = await fetch(`${API_BASE}/tables/click-track`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        console.warn('[TableStore] trackFieldClick HTTP error:', response.status);
        return;
      }

      const result: ClickTrackResponse = await response.json();

      if (!result.ok) {
        console.warn('[TableStore] trackFieldClick API error:', result.message);
      }
    } catch (err) {
      console.error('[TableStore] trackFieldClick error:', err);
      // 不阻断业务流程，仅记录日志
    }
  },

  setStatusFilter: (status: string | null) => {
    set({ statusFilter: status });
  },

  getFilteredTables: () => {
    const state = get();
    const { tables, statusFilter } = state;

    if (!statusFilter) {
      return tables;
    }

    return tables.filter((table) => table.status === statusFilter);
  },

  reset: () => {
    set({
      tables: [],
      summary: null,
      mealPeriod: '',
      viewMode: 'card',
      loading: false,
      error: null,
      currentStoreId: null,
      statusFilter: null,
    });
  },
}));
