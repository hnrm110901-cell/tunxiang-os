/**
 * 堂食会话状态管理 Store (v149 桌台中心化架构)
 *
 * 替代原 tableStore 碎片化状态，以 DiningSession 为核心聚合根。
 * 所有开台/点菜/转台/并台/结账/清台操作均通过此 store。
 *
 * WebSocket 实时更新：连接 /api/v1/tables/ws/layout/{storeId}
 * 收到桌台状态变更时自动刷新看板。
 */

import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';
import type {
  DiningSession,
  SessionBoardCard,
  BoardSummary,
  OpenTableRequest,
  TransferTableRequest,
  MergeSessionsRequest,
  CreateServiceCallRequest,
  ServiceCall,
} from '../types/dining-session';

const API = '/api/v1';

// ─── API helpers ─────────────────────────────────────────────────────────────

function tenantHeaders(): Record<string, string> {
  const tid = localStorage.getItem('tenant_id') || '';
  return { 'Content-Type': 'application/json', 'X-Tenant-ID': tid };
}

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...options, headers: { ...tenantHeaders(), ...(options?.headers ?? {}) } });
  const json = await res.json();
  if (!res.ok || !json.ok) {
    throw new Error(json?.detail?.error?.message ?? json?.detail ?? `HTTP ${res.status}`);
  }
  return json.data as T;
}

// ─── Store 类型 ───────────────────────────────────────────────────────────────

export interface DiningSessionStore {
  // ── 状态 ──────────────────────────────────────────────────────────
  /** 桌台大板（当前门店所有活跃会话） */
  board: SessionBoardCard[];
  /** 大板汇总统计 */
  summary: BoardSummary | null;
  /** 当前操作的会话（POS 收银台使用） */
  activeSession: DiningSession | null;
  /** 当前门店ID */
  storeId: string | null;
  /** 按状态筛选（null = 不筛选） */
  statusFilter: string | null;
  /** 按区域筛选 */
  zoneFilter: string | null;
  loading: boolean;
  error: string | null;
  /** 待处理服务呼叫（实时看板） */
  pendingCalls: ServiceCall[];

  // ── 大板操作 ──────────────────────────────────────────────────────
  /** 加载门店大板 */
  fetchBoard: (storeId: string) => Promise<void>;
  /** 按筛选条件过滤大板 */
  getFilteredBoard: () => SessionBoardCard[];
  setStatusFilter: (status: string | null) => void;
  setZoneFilter: (zoneId: string | null) => void;

  // ── 会话生命周期 ──────────────────────────────────────────────────
  /** 开台 */
  openTable: (req: OpenTableRequest) => Promise<DiningSession>;
  /** 获取会话详情 */
  getSession: (sessionId: string) => Promise<DiningSession>;
  /** 查桌台当前活跃会话 */
  getActiveSessionByTable: (tableId: string) => Promise<DiningSession | null>;
  /** 设置当前操作会话 */
  setActiveSession: (session: DiningSession | null) => void;

  // ── 桌台操作 ──────────────────────────────────────────────────────
  /** 转台 */
  transferTable: (sessionId: string, req: TransferTableRequest) => Promise<DiningSession>;
  /** 并台 */
  mergeSessions: (primarySessionId: string, req: MergeSessionsRequest) => Promise<DiningSession>;
  /** 买单 */
  requestBill: (sessionId: string, operatorId?: string) => Promise<DiningSession>;
  /** 结账完成（由支付完成后调用） */
  completePayment: (sessionId: string, finalAmountFen: number, discountAmountFen?: number) => Promise<DiningSession>;
  /** 清台 */
  clearTable: (sessionId: string, cleanerId: string) => Promise<void>;
  /** 修改就餐人数 */
  updateGuestCount: (sessionId: string, guestCount: number) => Promise<void>;
  /** VIP识别 */
  identifyVip: (sessionId: string, customerId: string, identifiedBy?: string) => Promise<void>;

  // ── 服务呼叫 ──────────────────────────────────────────────────────
  /** 发起服务呼叫（催菜/呼叫服务员等） */
  createServiceCall: (req: CreateServiceCallRequest) => Promise<ServiceCall>;
  /** 加载门店待处理呼叫 */
  fetchPendingCalls: (storeId: string) => Promise<void>;
  /** 处理服务呼叫 */
  handleServiceCall: (callId: string, handledBy: string) => Promise<void>;

  // ── 内部 ──────────────────────────────────────────────────────────
  reset: () => void;
  _refreshBoardCard: (sessionId: string) => Promise<void>;
}

// ─── Store 实现 ───────────────────────────────────────────────────────────────

export const useDiningSessionStore = create<DiningSessionStore>()(
  subscribeWithSelector((set, get) => ({
    board: [],
    summary: null,
    activeSession: null,
    storeId: null,
    statusFilter: null,
    zoneFilter: null,
    loading: false,
    error: null,
    pendingCalls: [],

    // ── 大板 ────────────────────────────────────────────────────────

    fetchBoard: async (storeId: string) => {
      set({ loading: true, error: null, storeId });
      try {
        const sessions = await apiFetch<SessionBoardCard[]>(
          `${API}/dining-sessions/board?store_id=${storeId}`
        );

        // 计算汇总
        const summary: BoardSummary = {
          totalSessions: sessions.length,
          seatedTables: sessions.filter(s =>
            ['seated', 'ordering', 'dining', 'add_ordering'].includes(s.status)
          ).length,
          billingTables: sessions.filter(s => s.status === 'billing').length,
          availableTables: 0,  // 由 tableStore 补充（从 tables 表获取空台数）
          totalGuests: sessions.reduce((sum, s) => sum + s.guestCount, 0),
          avgDiningMinutes: sessions.length
            ? Math.round(sessions.reduce((s, r) => s + (r.diningMinutes ?? 0), 0) / sessions.length)
            : 0,
          totalRevenueFen: sessions
            .filter(s => ['paid', 'clearing'].includes(s.status))
            .reduce((sum, s) => sum + s.finalAmountFen, 0),
        };

        set({ board: sessions, summary, loading: false });
      } catch (err) {
        set({ error: err instanceof Error ? err.message : '加载失败', loading: false });
      }
    },

    getFilteredBoard: () => {
      const { board, statusFilter, zoneFilter } = get();
      return board.filter(s => {
        if (statusFilter && s.status !== statusFilter) return false;
        if (zoneFilter && s.zoneName !== zoneFilter) return false;
        return true;
      });
    },

    setStatusFilter: (status) => set({ statusFilter: status }),
    setZoneFilter:   (zone)   => set({ zoneFilter: zone }),

    // ── 会话生命周期 ─────────────────────────────────────────────────

    openTable: async (req) => {
      const session = await apiFetch<DiningSession>(`${API}/dining-sessions`, {
        method: 'POST',
        body: JSON.stringify({
          store_id:        req.storeId,
          table_id:        req.tableId,
          guest_count:     req.guestCount,
          lead_waiter_id:  req.leadWaiterId,
          zone_id:         req.zoneId,
          booking_id:      req.bookingId,
          vip_customer_id: req.vipCustomerId,
          session_type:    req.sessionType ?? 'dine_in',
        }),
      });
      set({ activeSession: session });
      // 刷新大板
      const { storeId } = get();
      if (storeId) get().fetchBoard(storeId);
      return session;
    },

    getSession: async (sessionId) => {
      return apiFetch<DiningSession>(`${API}/dining-sessions/${sessionId}`);
    },

    getActiveSessionByTable: async (tableId) => {
      const { storeId } = get();
      if (!storeId) return null;
      return apiFetch<DiningSession | null>(
        `${API}/dining-sessions/by-table/${tableId}?store_id=${storeId}`
      ).catch(() => null);
    },

    setActiveSession: (session) => set({ activeSession: session }),

    // ── 桌台操作 ─────────────────────────────────────────────────────

    transferTable: async (sessionId, req) => {
      const session = await apiFetch<DiningSession>(
        `${API}/dining-sessions/${sessionId}/transfer`,
        {
          method: 'POST',
          body: JSON.stringify({
            target_table_id: req.targetTableId,
            reason:          req.reason,
            operator_id:     req.operatorId,
          }),
        }
      );
      set({ activeSession: session });
      const { storeId } = get();
      if (storeId) get().fetchBoard(storeId);
      return session;
    },

    mergeSessions: async (primarySessionId, req) => {
      const session = await apiFetch<DiningSession>(
        `${API}/dining-sessions/${primarySessionId}/merge`,
        {
          method: 'POST',
          body: JSON.stringify({
            secondary_session_ids: req.secondarySessionIds,
            operator_id:           req.operatorId,
          }),
        }
      );
      set({ activeSession: session });
      const { storeId } = get();
      if (storeId) get().fetchBoard(storeId);
      return session;
    },

    requestBill: async (sessionId, operatorId) => {
      const session = await apiFetch<DiningSession>(
        `${API}/dining-sessions/${sessionId}/request-bill`,
        { method: 'POST', body: JSON.stringify({ operator_id: operatorId }) }
      );
      if (get().activeSession?.id === sessionId) set({ activeSession: session });
      get()._refreshBoardCard(sessionId);
      return session;
    },

    completePayment: async (sessionId, finalAmountFen, discountAmountFen = 0) => {
      const session = await apiFetch<DiningSession>(
        `${API}/dining-sessions/${sessionId}/complete-payment`,
        {
          method: 'POST',
          body: JSON.stringify({
            final_amount_fen:    finalAmountFen,
            discount_amount_fen: discountAmountFen,
          }),
        }
      );
      if (get().activeSession?.id === sessionId) set({ activeSession: session });
      get()._refreshBoardCard(sessionId);
      return session;
    },

    clearTable: async (sessionId, cleanerId) => {
      await apiFetch(`${API}/dining-sessions/${sessionId}/clear`, {
        method: 'POST',
        body: JSON.stringify({ cleaner_id: cleanerId }),
      });
      if (get().activeSession?.id === sessionId) set({ activeSession: null });
      // 清台后刷新整个大板（桌台变空台，需更新汇总）
      const { storeId } = get();
      if (storeId) get().fetchBoard(storeId);
    },

    updateGuestCount: async (sessionId, guestCount) => {
      await apiFetch(`${API}/dining-sessions/${sessionId}/guest-count`, {
        method: 'PATCH',
        body: JSON.stringify({ guest_count: guestCount }),
      });
      get()._refreshBoardCard(sessionId);
    },

    identifyVip: async (sessionId, customerId, identifiedBy = 'scan') => {
      const session = await apiFetch<DiningSession>(
        `${API}/dining-sessions/${sessionId}/identify-vip`,
        {
          method: 'POST',
          body: JSON.stringify({ customer_id: customerId, identified_by: identifiedBy }),
        }
      );
      if (get().activeSession?.id === sessionId) set({ activeSession: session });
      get()._refreshBoardCard(sessionId);
    },

    // ── 服务呼叫 ─────────────────────────────────────────────────────

    createServiceCall: async (req) => {
      const call = await apiFetch<ServiceCall>(`${API}/service-calls`, {
        method: 'POST',
        body: JSON.stringify({
          store_id:         req.storeId,
          table_session_id: req.tableSessionId,
          call_type:        req.callType,
          content:          req.content,
          target_dish_id:   req.targetDishId,
          called_by:        req.calledBy ?? 'pos',
          caller_name:      req.callerName,
        }),
      });
      // 更新大板卡片的 serviceCallCount
      set(state => ({
        board: state.board.map(s =>
          s.id === req.tableSessionId
            ? { ...s, serviceCallCount: s.serviceCallCount + 1 }
            : s
        ),
      }));
      return call;
    },

    fetchPendingCalls: async (storeId) => {
      try {
        const { calls } = await apiFetch<{ calls: ServiceCall[]; total: number }>(
          `${API}/service-calls/pending?store_id=${storeId}`
        );
        set({ pendingCalls: calls });
      } catch {
        // 静默失败，不影响主流程
      }
    },

    handleServiceCall: async (callId, handledBy) => {
      await apiFetch(`${API}/service-calls/${callId}/handle`, {
        method: 'POST',
        body: JSON.stringify({ handled_by: handledBy }),
      });
      set(state => ({
        pendingCalls: state.pendingCalls.filter(c => c.id !== callId),
      }));
    },

    // ── 内部工具 ─────────────────────────────────────────────────────

    _refreshBoardCard: async (sessionId) => {
      try {
        const session = await apiFetch<DiningSession>(`${API}/dining-sessions/${sessionId}`);
        set(state => ({
          board: state.board.map(s => s.id === sessionId ? { ...s, ...session } : s),
        }));
      } catch {
        // 静默失败
      }
    },

    reset: () => set({
      board: [],
      summary: null,
      activeSession: null,
      storeId: null,
      statusFilter: null,
      zoneFilter: null,
      loading: false,
      error: null,
      pendingCalls: [],
    }),
  }))
);

// ─── 选择器（性能优化，避免全量重渲染）────────────────────────────────────────

/** 桌台大板（已筛选） */
export const selectFilteredBoard = (s: DiningSessionStore) => s.getFilteredBoard();
/** 汇总数据 */
export const selectBoardSummary  = (s: DiningSessionStore) => s.summary;
/** 当前操作会话 */
export const selectActiveSession = (s: DiningSessionStore) => s.activeSession;
/** 待处理呼叫数量（红点角标） */
export const selectPendingCallCount = (s: DiningSessionStore) => s.pendingCalls.length;
/** 按状态分组的桌台数量 */
export const selectStatusCounts = (s: DiningSessionStore) => {
  const counts: Record<string, number> = {};
  for (const card of s.board) {
    counts[card.status] = (counts[card.status] ?? 0) + 1;
  }
  return counts;
};
