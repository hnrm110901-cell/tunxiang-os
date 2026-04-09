/**
 * POS 全局快捷键 Hook
 *
 * 快捷键映射:
 *   F1~F12: 开台/点餐/结账/挂单/取单/预订/外卖/会员/退单/打印/全屏/锁屏
 *   Ctrl+F1/F2: 班次报表/系统设置
 *   Esc: 取消/关闭弹窗
 *
 * 按住 Alt 键显示快捷键提示浮层。
 */
import { useEffect, useState, useCallback, useRef } from 'react';

/* ═══════════════════════════════════════════
   类型定义
   ═══════════════════════════════════════════ */

export interface ShortcutAction {
  /** 快捷键标识，如 'F1', 'Ctrl+F1', 'Escape' */
  key: string;
  /** 显示标签 */
  label: string;
  /** 回调函数 */
  handler: () => void;
  /** 是否禁用 */
  disabled?: boolean;
}

export interface KeyboardShortcutsConfig {
  /** 自定义快捷键映射（会合并/覆盖默认映射） */
  overrides?: Partial<Record<string, ShortcutAction>>;
  /** 是否启用快捷键（输入框聚焦时可临时关闭） */
  enabled?: boolean;
}

/** 默认 POS 快捷键定义（key → 显示标签映射） */
export const DEFAULT_SHORTCUT_LABELS: Record<string, string> = {
  F1: '开台',
  F2: '点餐/加菜',
  F3: '结账',
  F4: '挂单',
  F5: '取单',
  F6: '预订',
  F7: '外卖',
  F8: '会员查询',
  F9: '退单',
  F10: '打印',
  F11: '全屏切换',
  F12: '锁屏',
  'Ctrl+F1': '班次报表',
  'Ctrl+F2': '系统设置',
  Escape: '取消/关闭',
};

/* ═══════════════════════════════════════════
   工具：从 KeyboardEvent 生成标识键
   ═══════════════════════════════════════════ */

function eventToKey(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push('Ctrl');
  if (e.shiftKey) parts.push('Shift');
  // Alt 键单独用于浮层显示，不纳入组合键标识
  parts.push(e.key === 'Escape' ? 'Escape' : e.key);
  return parts.join('+');
}

/* ═══════════════════════════════════════════
   Hook 主体
   ═══════════════════════════════════════════ */

export interface UseKeyboardShortcutsReturn {
  /** Alt 键是否按下（用于显示快捷键提示浮层） */
  altPressed: boolean;
  /** 当前已注册的快捷键列表（含 label） */
  shortcuts: Array<{ key: string; label: string; disabled: boolean }>;
}

export function useKeyboardShortcuts(
  actions: ShortcutAction[],
  config?: KeyboardShortcutsConfig,
): UseKeyboardShortcutsReturn {
  const { enabled = true } = config ?? {};
  const [altPressed, setAltPressed] = useState(false);

  // 用 ref 保持 actions 最新引用，避免频繁重新绑定事件
  const actionsRef = useRef<ShortcutAction[]>(actions);
  actionsRef.current = actions;

  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  /* ── keydown 处理 ── */
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Alt 浮层
    if (e.key === 'Alt') {
      setAltPressed(true);
      e.preventDefault();
      return;
    }

    if (!enabledRef.current) return;

    // 在输入框中按非功能键时不拦截
    const tag = (e.target as HTMLElement)?.tagName;
    const isInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    if (isInput && e.key === 'Escape') {
      // Esc 在输入框中也应生效（关闭弹窗）
    } else if (isInput && !e.key.startsWith('F')) {
      return;
    }

    const keyId = eventToKey(e);
    const action = actionsRef.current.find((a) => a.key === keyId);

    if (action && !action.disabled) {
      e.preventDefault();
      e.stopPropagation();
      action.handler();
    } else if (e.key.startsWith('F') || e.key === 'Escape') {
      // 阻止浏览器默认行为（F1 帮助、F5 刷新等）
      e.preventDefault();
    }
  }, []);

  /* ── keyup 处理 ── */
  const handleKeyUp = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Alt') {
      setAltPressed(false);
    }
  }, []);

  /* ── blur 时重置 Alt 状态（防止 Alt+Tab 切走后卡住） ── */
  const handleBlur = useCallback(() => {
    setAltPressed(false);
  }, []);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown, { capture: true });
    window.addEventListener('keyup', handleKeyUp, { capture: true });
    window.addEventListener('blur', handleBlur);

    return () => {
      window.removeEventListener('keydown', handleKeyDown, { capture: true });
      window.removeEventListener('keyup', handleKeyUp, { capture: true });
      window.removeEventListener('blur', handleBlur);
    };
  }, [handleKeyDown, handleKeyUp, handleBlur]);

  /* ── 返回已注册快捷键摘要 ── */
  const shortcuts = actions.map((a) => ({
    key: a.key,
    label: a.label,
    disabled: !!a.disabled,
  }));

  return { altPressed, shortcuts };
}

/* ═══════════════════════════════════════════
   快捷键提示浮层组件
   ═══════════════════════════════════════════ */

export { ShortcutOverlay } from '../components/ShortcutOverlay';
