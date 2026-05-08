/**
 * agentConsoleStore — AgentConsole 全局状态（zustand）
 *
 * 职责：
 *   - visible：右侧 Agent 抽屉是否展示
 *   - tab：当前激活的 tab（feed | chat | audit）
 *   - openChat：唤起 chat tab（visible=true + tab=chat）— Cmd+J 全局快捷键调用入口
 *
 * 取代：
 *   - ShellHQ.useState(agentVisible)
 *   - AgentConsole.useState(tab)
 *
 * 让外部（Cmd+J 全局快捷键）能跨组件触发 chat 唤起。
 *
 * Sprint 4 / S4-01 / Tier 2
 */
import { create } from 'zustand';

export type AgentTab = 'feed' | 'chat' | 'audit';

interface AgentConsoleState {
  visible: boolean;
  tab: AgentTab;
  setVisible: (v: boolean) => void;
  toggleVisible: () => void;
  setTab: (t: AgentTab) => void;
  openChat: () => void;
}

export const useAgentConsoleStore = create<AgentConsoleState>((set) => ({
  visible: true,
  tab: 'feed',
  setVisible: (visible) => set({ visible }),
  toggleVisible: () => set((s) => ({ visible: !s.visible })),
  setTab: (tab) => set({ tab }),
  openChat: () => set({ visible: true, tab: 'chat' }),
}));
