import { create } from 'zustand'

export interface DevforgeUser {
  id: string
  name: string
  avatar?: string
  email?: string
}

interface UserState {
  user: DevforgeUser
  tenant: string
  role: string
  setUser: (user: DevforgeUser) => void
  setTenant: (tenant: string) => void
}

/** 当前登录用户 — Day-1 用 mock，后续接 SSO/OAuth */
export const useUserStore = create<UserState>()((set) => ({
  user: {
    id: 'u-001',
    name: '未了已',
    email: 'founder@tunxiang.com',
  },
  tenant: 'tunxiang-internal',
  role: 'platform-admin',
  setUser: (user) => set({ user }),
  setTenant: (tenant) => set({ tenant }),
}))
