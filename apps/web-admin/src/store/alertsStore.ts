/**
 * 预警中心状态管理
 */
import { create } from 'zustand';
import type { AlertListItem, AlertDetail } from '../../../shared/api-types/p0-pages';

interface AlertsState {
  selectedAlertId: string | null;
  detailOpen: boolean;
  alertDetail: AlertDetail | null;
  detailLoading: boolean;

  selectAlert: (id: string) => void;
  closeDetail: () => void;
  setAlertDetail: (detail: AlertDetail) => void;
  setDetailLoading: (loading: boolean) => void;
}

export const useAlertsStore = create<AlertsState>((set) => ({
  selectedAlertId: null,
  detailOpen: false,
  alertDetail: null,
  detailLoading: false,

  selectAlert: (id) => set({ selectedAlertId: id, detailOpen: true, detailLoading: true }),
  closeDetail: () => set({ selectedAlertId: null, detailOpen: false, alertDetail: null }),
  setAlertDetail: (alertDetail) => set({ alertDetail, detailLoading: false }),
  setDetailLoading: (detailLoading) => set({ detailLoading }),
}));
