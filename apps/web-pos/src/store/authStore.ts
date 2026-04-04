/**
 * POS 认证状态管理 — Zustand
 * 员工工号 + PIN 登录，token 持久化到 localStorage
 */
import { create } from 'zustand';

const BASE = import.meta.env.VITE_API_BASE_URL || '';
const TENANT_ID = import.meta.env.VITE_TENANT_ID || '';
const STORE_ID = import.meta.env.VITE_STORE_ID || '';

const LS_TOKEN_KEY = 'tx_pos_token';
const LS_EMPLOYEE_KEY = 'tx_pos_employee';

export interface EmployeeInfo {
  id: string;
  name: string;
  role: string;
  storeId: string;
  permissions: string[];
}

interface AuthState {
  employee: EmployeeInfo | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  error: string | null;

  login: (employeeCode: string, pin: string) => Promise<boolean>;
  logout: () => void;
  checkSession: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  employee: null,
  token: null,
  isAuthenticated: false,
  loading: true,
  error: null,

  login: async (employeeCode: string, pin: string): Promise<boolean> => {
    set({ loading: true, error: null });
    try {
      const resp = await fetch(`${BASE}/api/v1/auth/pos-login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(TENANT_ID ? { 'X-Tenant-ID': TENANT_ID } : {}),
        },
        body: JSON.stringify({
          employee_code: employeeCode,
          pin,
          store_id: STORE_ID,
        }),
      });

      const json = await resp.json();

      if (!json.ok) {
        const message = json.error?.message || '登录失败，请检查工号和密码';
        set({ loading: false, error: message });
        return false;
      }

      const { token, employee } = json.data as {
        token: string;
        employee: {
          id: string;
          name: string;
          role: string;
          store_id: string;
          permissions: string[];
        };
      };

      const employeeInfo: EmployeeInfo = {
        id: employee.id,
        name: employee.name,
        role: employee.role,
        storeId: employee.store_id,
        permissions: employee.permissions,
      };

      localStorage.setItem(LS_TOKEN_KEY, token);
      localStorage.setItem(LS_EMPLOYEE_KEY, JSON.stringify(employeeInfo));

      set({
        token,
        employee: employeeInfo,
        isAuthenticated: true,
        loading: false,
        error: null,
      });

      return true;
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : '网络错误，请检查连接';
      set({ loading: false, error: message });
      return false;
    }
  },

  logout: () => {
    localStorage.removeItem(LS_TOKEN_KEY);
    localStorage.removeItem(LS_EMPLOYEE_KEY);
    set({
      employee: null,
      token: null,
      isAuthenticated: false,
      loading: false,
      error: null,
    });
  },

  checkSession: () => {
    const token = localStorage.getItem(LS_TOKEN_KEY);
    const employeeRaw = localStorage.getItem(LS_EMPLOYEE_KEY);

    if (token && employeeRaw) {
      try {
        const employee = JSON.parse(employeeRaw) as EmployeeInfo;
        set({
          token,
          employee,
          isAuthenticated: true,
          loading: false,
        });
        return;
      } catch {
        // Corrupted data — clear and require re-login
      }
    }

    localStorage.removeItem(LS_TOKEN_KEY);
    localStorage.removeItem(LS_EMPLOYEE_KEY);
    set({
      employee: null,
      token: null,
      isAuthenticated: false,
      loading: false,
    });
  },
}));
