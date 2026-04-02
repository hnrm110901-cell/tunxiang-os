/**
 * AgentDrawer 全局状态 — 所有页面共享的 Agent 抽屉数据
 *
 * 每个页面负责向 store 写入当前上下文的 suggestions/explanations/actions/logs，
 * AgentDrawer 组件从 store 读取并渲染。
 */
import { create } from 'zustand';

import type {
  AgentSuggestion, AgentAction, AgentExplanation, AgentLogEntry,
} from '../components/agent/AgentDrawer';

interface AgentDrawerState {
  visible: boolean;
  loading: boolean;
  contextSummary: string;
  suggestions: AgentSuggestion[];
  explanations: AgentExplanation[];
  actions: AgentAction[];
  logs: AgentLogEntry[];
  monthlySavingsFen: number;

  // Actions
  toggle: () => void;
  setLoading: (loading: boolean) => void;
  setContext: (summary: string) => void;
  setSuggestions: (items: AgentSuggestion[]) => void;
  setExplanations: (items: AgentExplanation[]) => void;
  setActions: (items: AgentAction[]) => void;
  setLogs: (items: AgentLogEntry[]) => void;
  /** 页面切换时重置抽屉内容 */
  reset: () => void;
}

export const useAgentDrawerStore = create<AgentDrawerState>((set) => ({
  visible: true,
  loading: false,
  contextSummary: '',
  suggestions: [],
  explanations: [],
  actions: [],
  logs: [],
  monthlySavingsFen: 1268000, // ¥12,680 mock

  toggle: () => set((s) => ({ visible: !s.visible })),
  setLoading: (loading) => set({ loading }),
  setContext: (contextSummary) => set({ contextSummary }),
  setSuggestions: (suggestions) => set({ suggestions }),
  setExplanations: (explanations) => set({ explanations }),
  setActions: (actions) => set({ actions }),
  setLogs: (logs) => set({ logs }),
  reset: () => set({
    loading: false, contextSummary: '',
    suggestions: [], explanations: [], actions: [], logs: [],
  }),
}));
