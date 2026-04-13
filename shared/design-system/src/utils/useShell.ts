import { useMemo } from 'react';
import type { ShellType } from '../tokens/shell';

/**
 * 终端检测 Hook
 * 根据 URL / UserAgent / TXBridge 判断当前运行终端
 */
export function useShell(): ShellType {
  return useMemo(() => detectShell(), []);
}

export function detectShell(): ShellType {
  if (typeof window === 'undefined') return 'admin';

  // 安卓 POS（有 TXBridge）
  if ((window as any).TXBridge) return 'pos';

  // KDS（URL 包含 kds）
  if (window.location.pathname.includes('/kds')) return 'kds';

  // 服务员端（URL 包含 crew）
  if (window.location.pathname.includes('/crew')) return 'crew';

  // H5 自助点餐
  if (window.location.pathname.includes('/order') || window.location.pathname.includes('/h5')) return 'h5';

  // 默认总部管理
  return 'admin';
}
