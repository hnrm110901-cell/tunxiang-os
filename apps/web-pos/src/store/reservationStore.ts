/**
 * 预订台账状态管理 — Zustand
 */
import { create } from 'zustand';
import type { Reservation, ReservationStatus, CreateReservationReq, UpdateReservationReq } from '../api/reservationApi';
import * as api from '../api/reservationApi';

interface ReservationState {
  reservations: Reservation[];
  loading: boolean;
  error: string | null;

  fetchList: (storeId: string) => Promise<void>;
  create: (storeId: string, data: CreateReservationReq) => Promise<Reservation | null>;
  update: (id: string, data: UpdateReservationReq) => Promise<void>;
  cancel: (id: string, reason?: string) => Promise<void>;
  confirmArrival: (id: string, tableNo: string) => Promise<void>;
  clearError: () => void;
}

export const useReservationStore = create<ReservationState>()((set) => ({
  reservations: [],
  loading: false,
  error: null,

  fetchList: async (storeId) => {
    set({ loading: true, error: null });
    try {
      const data = await api.fetchReservations(storeId);
      set({ reservations: data, loading: false });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  create: async (storeId, data) => {
    set({ loading: true, error: null });
    try {
      const reservation = await api.createReservation(storeId, data);
      set((s) => ({ reservations: [...s.reservations, reservation], loading: false }));
      return reservation;
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
      return null;
    }
  },

  update: async (id, data) => {
    set({ loading: true, error: null });
    try {
      const updated = await api.updateReservation(id, data);
      set((s) => ({
        reservations: s.reservations.map((r) => (r.id === id ? updated : r)),
        loading: false,
      }));
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  cancel: async (id, reason?) => {
    set({ loading: true, error: null });
    try {
      await api.cancelReservation(id, reason);
      set((s) => ({
        reservations: s.reservations.map((r) =>
          r.id === id ? { ...r, status: 'cancelled' as ReservationStatus } : r,
        ),
        loading: false,
      }));
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  confirmArrival: async (id, tableNo) => {
    set({ loading: true, error: null });
    try {
      await api.confirmArrival(id, tableNo);
      set((s) => ({
        reservations: s.reservations.map((r) =>
          r.id === id ? { ...r, status: 'seated' as ReservationStatus, tableNo } : r,
        ),
        loading: false,
      }));
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  clearError: () => set({ error: null }),
}));
