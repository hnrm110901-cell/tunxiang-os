/**
 * POS 全局快捷键 Hook
 *
 * 快捷键映射（与天财商龙对齐）:
 *   F1~F12: 新建订单/结账/整单作废/拆单/桌台地图/会员查询/整单折扣/打印/交班/计算器/全屏/锁屏
 *   Ctrl+Enter: 快速现金结账
 *   Ctrl+F: 搜索菜品
 *   Ctrl+G: 赠菜
 *   Ctrl+P: 改价
 *   Ctrl+L: 锁屏
 *   Ctrl+/: 快捷键帮助面板
 *   Esc: 取消/关闭弹窗
 *
 * 按住 Alt 键显示快捷键提示浮层（原有行为保留）。
 * Ctrl+/ 打开新版分类帮助面板（KeyboardShortcutHelp）。
 *
 * 检测规则：
 *   - navigator.maxTouchPoints === 0 → 纯键盘设备，激活全部快捷键
 *   - 触控设备也可通过设置手动启用键盘模式
 */
import { useEffect, useState, useCallback, useRef } from 'react';

/* ═══════════════════════════════════════════
   键盘设备检测
   ═══════════════════════════════════════════ */

/**
 * 检测当前设备是否具备实体键盘。
 * navigator.maxTouchPoints === 0 说明无触控，基本确定是PC/桌面。
 * 强制启用键：localStorage 'tx_keyboard_mode' = '1'
 */
export function isKeyboardDevice(): boolean {
  try {
    if (localStorage.getItem('tx_keyboard_mode') === '1') return true;
  } catch {
    // localStorage 不可用
  }
  return navigator.maxTouchPoints === 0;
}

/* ═══════════════════════════════════════════
   POS 快捷键常量（与天财商龙对齐）
   ═══════════════════════════════════════════ */

/** POS 快捷键分类 */
export type ShortcutCategory = 'cashier' | 'dish' | 'system';

export interface ShortcutDefinition {
  key: string;
  description: string;
  category: ShortcutCategory;
}

/** 全局 POS 快捷键常量 */
export const POS_SHORTCUTS = {
  // ── 收银类 ──
  NEW_ORDER:    { key: 'F1',          description: '新建订单',     category: 'cashier' },
  CHECKOUT:     { key: 'F2',          description: '结账',         category: 'cashier' },
  VOID_ORDER:   { key: 'F3',          description: '整单作废',     category: 'cashier' },
  SPLIT_ORDER:  { key: 'F4',          description: '拆单',         category: 'cashier' },
  TABLE_MAP:    { key: 'F5',          description: '桌台地图',     category: 'cashier' },
  MEMBER_LOOKUP:{ key: 'F6',          description: '查询会员',     category: 'cashier' },
  DISCOUNT:     { key: 'F7',          description: '整单折扣',     category: 'cashier' },
  PRINT:        { key: 'F8',          description: '打印账单',     category: 'cashier' },
  SHIFT_HANDOVER:{ key: 'F9',         description: '交班',         category: 'cashier' },
  CALCULATOR:   { key: 'F10',         description: '计算器',       category: 'cashier' },
  QUICK_CASH:   { key: 'Ctrl+Enter',  description: '快速现金结账', category: 'cashier' },
  // ── 菜品操作类 ──
  SEARCH_DISH:  { key: 'Ctrl+F',      description: '搜索菜品',     category: 'dish'    },
  GIFT_DISH:    { key: 'Ctrl+G',      description: '赠菜',         category: 'dish'    },
  CHANGE_PRICE: { key: 'Ctrl+P',      description: '改价',         category: 'dish'    },
  // ── 系统功能类 ──
  FULLSCREEN:   { key: 'F11',         description: '全屏切换',     category: 'system'  },
  LOCK_SCREEN:  { key: 'Ctrl+L',      description: '锁屏',         category: 'system'  },
  HELP:         { key: 'Ctrl+/',      description: '快捷键帮助',   category: 'system'  },
  ESCAPE:       { key: 'Escape',      description: '取消/关闭',    category: 'system'  },
} as const satisfies Record<string, ShortcutDefinition>;

/** 快捷键按分类分组（供帮助面板使用） */
export const SHORTCUT_CATEGORIES: Record<ShortcutCategory, { label: string; shortcuts: ShortcutDefinition[] }> = {
  cashier: {
    label: '收银类',
    shortcuts: Object.values(POS_SHORTCUTS).filter((s) => s.category === 'cashier'),
  },
  dish: {
    label: '菜品操作',
    shortcuts: Object.values(POS_SHORTCUTS).filter((s) => s.category === 'dish'),
  },
  system: {
    label: '系统功能',
    shortcuts: Object.values(POS_SHORTCUTS).filter((s) => s.category === 'system'),
  },
};

/** 兼容旧版 DEFAULT_SHORTCUT_LABELS（保留以防其他地方引用） */
export const DEFAULT_SHORTCUT_LABELS: Record<string, string> = Object.fromEntries(
  Object.values(POS_SHORTCUTS).map((s) => [s.key, s.description]),
);

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
  /**
   * 上下文过滤：指定此快捷键只在特定页面/模式下响应。
   * 不填时全局响应。
   * 使用时配合 activeContext 参数。
   */
  context?: string;
}

export interface KeyboardShortcutsConfig {
  /** 自定义快捷键映射（会合并/覆盖默认映射） */
  overrides?: Partial<Record<string, ShortcutAction>>;
  /**
   * 是否启用快捷键（输入框聚焦时可临时关闭）
   * 不填时默认仅键盘设备启用（isKeyboardDevice() 检测）
   */
  enabled?: boolean;
  /**
   * 当前活跃上下文标识（如 'cashier' / 'table-map' / 'settle'）。
   * 有 context 字段的 ShortcutAction 仅在 activeContext 匹配时响应。
   */
  activeContext?: string;
  /**
   * 按键触发时的视觉反馈回调（0.2秒高亮）。
   * 传入后 hook 内部在命中快捷键时调用，参数为被命中的 key 字符串。
   */
  onKeyActivated?: (key: string) => void;
}

/* ═══════════════════════════════════════════
   工具：从 KeyboardEvent 生成标识键
   ═══════════════════════════════════════════ */

function eventToKey(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push('Ctrl');
  if (e.shiftKey) parts.push('Shift');
  // Alt 键单独用于浮层显示，不纳入组合键标识
  // '/' 在 keydown 中 e.key 为 '/'，标准化为 'Ctrl+/'
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
  /** 最近激活的快捷键（0.2秒后自动清空，用于视觉高亮） */
  activeKey: string | null;
}

export function useKeyboardShortcuts(
  actions: ShortcutAction[],
  config?: KeyboardShortcutsConfig,
): UseKeyboardShortcutsReturn {
  // 默认：仅键盘设备启用（触控设备不注册全局快捷键）
  const { enabled = isKeyboardDevice(), activeContext, onKeyActivated } = config ?? {};
  const [altPressed, setAltPressed] = useState(false);
  const [activeKey, setActiveKey] = useState<string | null>(null);

  // 用 ref 保持最新引用，避免频繁重新绑定事件
  const actionsRef = useRef<ShortcutAction[]>(actions);
  actionsRef.current = actions;

  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  const activeContextRef = useRef(activeContext);
  activeContextRef.current = activeContext;

  const onKeyActivatedRef = useRef(onKeyActivated);
  onKeyActivatedRef.current = onKeyActivated;

  /* ── 视觉反馈：激活高亮 0.2秒后清空 ── */
  const activateKeyFeedback = useCallback((key: string) => {
    setActiveKey(key);
    onKeyActivatedRef.current?.(key);
    setTimeout(() => setActiveKey(null), 200);
  }, []);

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
    } else if (isInput && !e.key.startsWith('F') && !(e.ctrlKey || e.metaKey)) {
      return;
    }

    const keyId = eventToKey(e);

    // 查找命中的 action（context 过滤：action 无 context 字段时全局匹配）
    const action = actionsRef.current.find((a) => {
      if (a.key !== keyId) return false;
      if (a.context && activeContextRef.current && a.context !== activeContextRef.current) return false;
      return true;
    });

    if (action && !action.disabled) {
      e.preventDefault();
      e.stopPropagation();
      activateKeyFeedback(keyId);
      action.handler();
    } else if (e.key.startsWith('F') || e.key === 'Escape') {
      // 阻止浏览器默认行为（F1 帮助、F5 刷新等），即使未绑定也阻止
      e.preventDefault();
    } else if ((e.ctrlKey || e.metaKey) && (e.key === '/' || e.key === 'f' || e.key === 'l' || e.key === 'p' || e.key === 'g')) {
      // 阻止 Ctrl+F 触发浏览器搜索栏等默认行为
      e.preventDefault();
    }
  }, [activateKeyFeedback]);

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

  return { altPressed, shortcuts, activeKey };
}

/* ═══════════════════════════════════════════
   快捷键提示浮层组件
   ═══════════════════════════════════════════ */

export { ShortcutOverlay } from '../components/ShortcutOverlay';
