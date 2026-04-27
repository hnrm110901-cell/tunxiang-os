import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type DevforgeEnv = 'dev' | 'test' | 'staging' | 'gray' | 'prod'

export const ENV_LABELS: Record<DevforgeEnv, string> = {
  dev: '开发',
  test: '测试',
  staging: '预发',
  gray: '灰度',
  prod: '生产',
}

export const ENV_ORDER: DevforgeEnv[] = ['dev', 'test', 'staging', 'gray', 'prod']

interface EnvState {
  currentEnv: DevforgeEnv
  setEnv: (env: DevforgeEnv) => void
}

/** 当前环境，持久化到 localStorage（key: devforge.env） */
export const useEnvStore = create<EnvState>()(
  persist(
    (set) => ({
      currentEnv: 'dev',
      setEnv: (env) => set({ currentEnv: env }),
    }),
    { name: 'devforge.env' },
  ),
)
