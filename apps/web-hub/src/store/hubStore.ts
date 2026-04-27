/**
 * Hub v2.0 — Zustand 全局状态
 */
import { create } from 'zustand';
import type {
  WorkMode,
  WorkspaceType,
  ObjectPageTab,
  StreamConnectionStatus,
} from '../types/hub';

export interface HubState {
  /* ─── 导航 ─── */
  workMode: WorkMode;
  activeWorkspace: WorkspaceType | null;
  selectedObjectId: string | null;
  activeTab: ObjectPageTab;

  /* ─── UI 面板 ─── */
  cmdkOpen: boolean;
  copilotOpen: boolean;

  /* ─── Stream ─── */
  streamStatus: StreamConnectionStatus;

  /* ─── Actions ─── */
  setWorkMode: (mode: WorkMode) => void;
  setActiveWorkspace: (ws: WorkspaceType | null) => void;
  selectObject: (id: string | null) => void;
  setActiveTab: (tab: ObjectPageTab) => void;
  toggleCmdK: () => void;
  setCmdKOpen: (open: boolean) => void;
  toggleCopilot: () => void;
  setCopilotOpen: (open: boolean) => void;
  setStreamStatus: (s: StreamConnectionStatus) => void;
}

export const useHubStore = create<HubState>((set) => ({
  /* ─── 初始值 ─── */
  workMode: 'today',
  activeWorkspace: null,
  selectedObjectId: null,
  activeTab: 'overview',

  cmdkOpen: false,
  copilotOpen: false,

  streamStatus: 'disconnected',

  /* ─── Reducers ─── */
  setWorkMode: (mode) =>
    set({ workMode: mode }),

  setActiveWorkspace: (ws) =>
    set({ activeWorkspace: ws, selectedObjectId: null, activeTab: 'overview' }),

  selectObject: (id) =>
    set({ selectedObjectId: id, activeTab: 'overview' }),

  setActiveTab: (tab) =>
    set({ activeTab: tab }),

  toggleCmdK: () =>
    set((s) => ({ cmdkOpen: !s.cmdkOpen })),

  setCmdKOpen: (open) =>
    set({ cmdkOpen: open }),

  toggleCopilot: () =>
    set((s) => ({ copilotOpen: !s.copilotOpen })),

  setCopilotOpen: (open) =>
    set({ copilotOpen: open }),

  setStreamStatus: (status) =>
    set({ streamStatus: status }),
}));
