import { create } from 'zustand';

export type ToastType = 'success' | 'error' | 'info' | 'offline';

export interface ToastItem {
  id: string;
  message: string;
  type: ToastType;
  autoDismissMs: number | null;
}

interface ToastState {
  toasts: ToastItem[];
  push: (message: string, type: ToastType) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

const MAX_VISIBLE = 3;
const DEFAULT_TTL_MS = 3000;

function ttlFor(type: ToastType): number | null {
  if (type === 'offline') return null;
  return DEFAULT_TTL_MS;
}

function newId(): string {
  const rand = Math.random().toString(36).slice(2, 8);
  return `toast_${Date.now()}_${rand}`;
}

export const useToastStore = create<ToastState>()((set) => ({
  toasts: [],
  push: (message, type) => {
    const id = newId();
    const item: ToastItem = { id, message, type, autoDismissMs: ttlFor(type) };
    set((state) => {
      const next = [...state.toasts, item];
      while (next.length > MAX_VISIBLE) next.shift();
      return { toasts: next };
    });
    return id;
  },
  dismiss: (id) => {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },
  clear: () => set({ toasts: [] }),
}));

export function showToast(message: string, type: ToastType = 'info'): string {
  return useToastStore.getState().push(message, type);
}

export function dismissToast(id: string): void {
  useToastStore.getState().dismiss(id);
}

export function useToasts(): ToastItem[] {
  return useToastStore((s) => s.toasts);
}
