/**
 * authStore — Zustand 认证状态管理
 * - token / user / tenant / permissions
 * - 从 localStorage 恢复
 * - 登录 / 登出 / Token 刷新
 */
import { create } from 'zustand';
import { apiPost } from '../api/client';

// ─── 类型 ───

export interface TxUser {
  user_id: string;
  username: string;
  display_name: string;
  tenant_id: string;
  role: string;
  permissions: string[];
}

interface LoginResponse {
  token: string;
  user: TxUser;
}

interface AuthState {
  token: string | null;
  user: TxUser | null;
  isAuthenticated: boolean;

  /** 登录 */
  login: (username: string, password: string) => Promise<void>;

  /** 登出 */
  logout: () => void;

  /** 从 localStorage 恢复（App 初始化时调用） */
  restore: () => void;

  /** 判断是否拥有指定权限 */
  hasPermission: (perm: string) => boolean;

  /** 刷新 token */
  refreshToken: () => Promise<void>;
}

// ─── 工具 ───

function persistToStorage(token: string, user: TxUser): void {
  localStorage.setItem('tx_token', token);
  localStorage.setItem('tx_user', JSON.stringify(user));
  localStorage.setItem('tx_tenant_id', user.tenant_id);
}

function clearStorage(): void {
  localStorage.removeItem('tx_token');
  localStorage.removeItem('tx_user');
  localStorage.removeItem('tx_tenant_id');
}

function restoreFromStorage(): { token: string | null; user: TxUser | null } {
  const token = localStorage.getItem('tx_token');
  const raw = localStorage.getItem('tx_user');
  let user: TxUser | null = null;

  if (raw) {
    try {
      user = JSON.parse(raw) as TxUser;
    } catch {
      user = null;
    }
  }

  return { token, user };
}

// ─── Token 自动刷新定时器 ───

let refreshTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleTokenRefresh(store: { getState: () => AuthState }): void {
  if (refreshTimer) {
    clearTimeout(refreshTimer);
    refreshTimer = null;
  }

  const token = store.getState().token;
  if (!token) return;

  // 解析 JWT 过期时间
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const exp = (payload.exp as number) * 1000;
    const now = Date.now();
    // 过期前 5 分钟刷新
    const refreshAt = exp - 5 * 60 * 1000;
    const delay = Math.max(refreshAt - now, 10_000);

    refreshTimer = setTimeout(() => {
      store.getState().refreshToken().catch(() => {
        // 刷新失败则登出
        store.getState().logout();
      });
    }, delay);
  } catch {
    // JWT 格式不对（如 Mock token），不做自动刷新
  }
}

// ─── Store ───

export const useAuthStore = create<AuthState>((set, get, store) => ({
  token: null,
  user: null,
  isAuthenticated: false,

  login: async (username: string, password: string) => {
    try {
      const data = await apiPost<LoginResponse>(
        '/api/v1/auth/login',
        { username, password },
        { skipAuth: true },
      );

      persistToStorage(data.token, data.user);
      set({
        token: data.token,
        user: data.user,
        isAuthenticated: true,
      });
      scheduleTokenRefresh(store);
    } catch (err) {
      // Mock 降级：当后端不可用时，允许任意账号登录
      if (
        err instanceof TypeError ||
        (err instanceof Error && err.message.includes('网络错误'))
      ) {
        const mockUser: TxUser = {
          user_id: 'mock-001',
          username,
          display_name: username,
          tenant_id: 'demo-tenant',
          role: 'admin',
          permissions: ['*'],
        };
        const mockToken = 'mock-jwt-token';

        persistToStorage(mockToken, mockUser);
        set({
          token: mockToken,
          user: mockUser,
          isAuthenticated: true,
        });
        return;
      }
      throw err;
    }
  },

  logout: () => {
    const token = get().token;
    // Fire-and-forget 后端登出
    if (token && token !== 'mock-jwt-token') {
      fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => { /* ignore */ });
    }

    if (refreshTimer) {
      clearTimeout(refreshTimer);
      refreshTimer = null;
    }

    clearStorage();
    set({ token: null, user: null, isAuthenticated: false });
  },

  restore: () => {
    const { token, user } = restoreFromStorage();
    if (token && user) {
      set({ token, user, isAuthenticated: true });
      scheduleTokenRefresh(store);
    }
  },

  hasPermission: (perm: string) => {
    const user = get().user;
    if (!user) return false;
    if (user.permissions.includes('*')) return true;
    return user.permissions.includes(perm);
  },

  refreshToken: async () => {
    const data = await apiPost<LoginResponse>('/api/v1/auth/refresh');
    persistToStorage(data.token, data.user);
    set({
      token: data.token,
      user: data.user,
      isAuthenticated: true,
    });
    scheduleTokenRefresh(store);
  },
}));
