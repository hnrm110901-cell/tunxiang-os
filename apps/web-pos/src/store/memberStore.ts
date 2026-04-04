/**
 * 会员状态管理 — Zustand
 */
import { create } from 'zustand';

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';

export interface MemberInfo {
  id: string;
  phone: string;
  name: string;
  vipLevel: string;
  totalVisits: number;
  balanceFen: number;
  pointsBalance: number;
}

interface MemberState {
  currentMember: MemberInfo | null;
  searchResults: MemberInfo[];
  loading: boolean;
  error: string | null;

  // Actions
  searchMember: (query: string) => Promise<void>;
  selectMember: (member: MemberInfo) => void;
  clearMember: () => void;
  fetchBalance: (memberId: string) => Promise<void>;
}

function buildHeaders(): Record<string, string> {
  return {
    'Content-Type': 'application/json',
    ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
  };
}

export const useMemberStore = create<MemberState>((set, get) => ({
  currentMember: null,
  searchResults: [],
  loading: false,
  error: null,

  searchMember: async (query) => {
    set({ loading: true, error: null });
    try {
      const resp = await fetch(
        `${BASE}/api/v1/member/depth/search?keyword=${encodeURIComponent(query)}`,
        { headers: buildHeaders() },
      );
      const json = await resp.json();
      if (!json.ok) throw new Error(json.error?.message || 'Member search failed');
      const items: unknown[] = json.data?.items || json.data?.members || [];
      const searchResults: MemberInfo[] = items.map((m: any) => ({
        id: m.id || m.member_id,
        phone: m.phone || '',
        name: m.name || m.member_name || '',
        vipLevel: m.vip_level || m.level || '',
        totalVisits: m.total_visits || 0,
        balanceFen: m.balance_fen || 0,
        pointsBalance: m.points_balance || m.points || 0,
      }));
      set({ searchResults, loading: false });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      set({ searchResults: [], error: message, loading: false });
    }
  },

  selectMember: (member) => set({ currentMember: member, searchResults: [] }),

  clearMember: () => set({ currentMember: null, searchResults: [], error: null }),

  fetchBalance: async (memberId) => {
    try {
      const resp = await fetch(
        `${BASE}/api/v1/member/points/cards/${memberId}/balance`,
        { headers: buildHeaders() },
      );
      const json = await resp.json();
      if (!json.ok) throw new Error(json.error?.message || 'Failed to fetch balance');
      const current = get().currentMember;
      if (current && current.id === memberId) {
        set({
          currentMember: {
            ...current,
            balanceFen: json.data?.balance_fen ?? current.balanceFen,
            pointsBalance: json.data?.points_balance ?? json.data?.points ?? current.pointsBalance,
          },
        });
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      set({ error: message });
    }
  },
}));
