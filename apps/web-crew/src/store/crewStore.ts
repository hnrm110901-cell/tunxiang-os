/**
 * crewStore — 服务员端全局状态
 * 管理简约模式（isSlimMode）等跨组件状态
 */
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface CrewStore {
  /** 高峰期简约模式：只显示核心操作 */
  isSlimMode: boolean;
  toggleSlimMode: () => void;
  setSlimMode: (val: boolean) => void;
}

export const useCrewStore = create<CrewStore>()(
  persist(
    (set) => ({
      isSlimMode: false,
      toggleSlimMode: () => set((s) => ({ isSlimMode: !s.isSlimMode })),
      setSlimMode: (val) => set({ isSlimMode: val }),
    }),
    {
      name: 'tx-crew-store',
    }
  )
);
