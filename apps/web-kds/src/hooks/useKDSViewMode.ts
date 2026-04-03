/**
 * useKDSViewMode — KDS 视角切换 Hook
 *
 * 支持两种视角：
 *   'dish'  — 菜品视角（后厨档口视角，按菜品/档口分组）
 *   'table' — 桌台视角（前厅大屏视角，按桌台分组）
 *
 * 状态持久化到 localStorage，刷新后恢复上次视角。
 */
import { useCallback, useState } from 'react';

export type KDSViewMode = 'dish' | 'table';

const STORAGE_KEY = 'kds_view_mode';
const DEFAULT_MODE: KDSViewMode = 'dish';

function readStoredMode(): KDSViewMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'dish' || stored === 'table') {
      return stored;
    }
  } catch {
    // localStorage 不可用（如隐私模式），静默降级
  }
  return DEFAULT_MODE;
}

function writeStoredMode(mode: KDSViewMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // 写入失败静默忽略
  }
}

export interface UseKDSViewModeReturn {
  /** 当前视角 */
  mode: KDSViewMode;
  /** 设置视角 */
  setMode: (mode: KDSViewMode) => void;
  /** 切换视角（dish ↔ table） */
  toggle: () => void;
}

export function useKDSViewMode(): UseKDSViewModeReturn {
  const [mode, setModeState] = useState<KDSViewMode>(readStoredMode);

  const setMode = useCallback((newMode: KDSViewMode) => {
    setModeState(newMode);
    writeStoredMode(newMode);
  }, []);

  const toggle = useCallback(() => {
    setModeState(prev => {
      const next: KDSViewMode = prev === 'dish' ? 'table' : 'dish';
      writeStoredMode(next);
      return next;
    });
  }, []);

  return { mode, setMode, toggle };
}
