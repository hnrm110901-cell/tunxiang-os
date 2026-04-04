/**
 * useAuth — 认证状态 Hook
 * 对 authStore 的薄封装，提供组件级便捷 API
 */
import { useAuthStore, TxUser } from '../store/authStore';

export interface UseAuthResult {
  token: string | null;
  user: TxUser | null;
  tenantId: string | null;
  permissions: string[];
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  hasPermission: (perm: string) => boolean;
}

export function useAuth(): UseAuthResult {
  const store = useAuthStore();

  return {
    token: store.token,
    user: store.user,
    tenantId: store.user?.tenant_id ?? null,
    permissions: store.user?.permissions ?? [],
    isAuthenticated: store.isAuthenticated,
    login: store.login,
    logout: store.logout,
    hasPermission: store.hasPermission,
  };
}
