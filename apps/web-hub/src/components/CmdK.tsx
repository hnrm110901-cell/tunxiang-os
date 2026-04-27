/**
 * Cmd-K 全局命令面板
 *
 * 设计参考 Linear / Vercel 命令面板。
 * 快捷键 ⌘K 打开/关闭，支持键盘导航、分组搜索、实时过滤。
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';

// ── 颜色常量 ──
const BG = '#0A1418';
const SURFACE = '#0E1E24';
const SURFACE2 = '#132932';
const SURFACE3 = '#1A3540';
const BORDER = '#1A3540';
const BORDER2 = '#23485a';
const TEXT = '#E6EDF1';
const TEXT2 = '#94A8B3';
const TEXT3 = '#647985';
const ORANGE = '#FF6B2C';

// ── 类型定义 ──

export type CommandGroup = 'navigate' | 'search' | 'create' | 'action' | 'settings';

export interface Command {
  id: string;
  group: CommandGroup;
  icon: string;
  title: string;
  description?: string;
  shortcut?: string;
  action: () => void;
}

interface CmdKProps {
  open: boolean;
  onClose: () => void;
  commands: Command[];
}

const GROUP_LABELS: Record<CommandGroup, string> = {
  navigate: '跳转',
  search: '搜索',
  create: '创建',
  action: '操作',
  settings: '设置',
};

const GROUP_ORDER: CommandGroup[] = ['navigate', 'search', 'create', 'action', 'settings'];

// ── 样式 ──

const s = {
  overlay: {
    position: 'fixed' as const,
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: 'rgba(0,0,0,0.55)',
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'center',
    paddingTop: 120,
    zIndex: 9000,
    animation: 'cmdkFadeIn 150ms ease-out',
  } as React.CSSProperties,

  panel: {
    width: 640,
    maxHeight: 480,
    background: SURFACE,
    border: `1px solid ${BORDER2}`,
    borderRadius: 12,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column' as const,
    boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
    animation: 'cmdkScaleIn 150ms ease-out',
  } as React.CSSProperties,

  searchWrap: {
    display: 'flex',
    alignItems: 'center',
    padding: '0 16px',
    borderBottom: `1px solid ${BORDER}`,
  } as React.CSSProperties,

  searchIcon: {
    fontSize: 16,
    color: TEXT3,
    marginRight: 10,
    flexShrink: 0,
  } as React.CSSProperties,

  searchInput: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    outline: 'none',
    color: TEXT,
    fontSize: 16,
    padding: '14px 0',
    fontFamily: 'inherit',
  } as React.CSSProperties,

  list: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '8px 0',
  } as React.CSSProperties,

  groupLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: TEXT3,
    textTransform: 'uppercase' as const,
    padding: '8px 16px 4px',
    letterSpacing: 0.5,
  } as React.CSSProperties,

  item: (selected: boolean) => ({
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '8px 16px',
    cursor: 'pointer',
    background: selected ? SURFACE3 : 'transparent',
    transition: 'background 80ms',
  }) as React.CSSProperties,

  itemIcon: {
    fontSize: 16,
    width: 24,
    textAlign: 'center' as const,
    flexShrink: 0,
  } as React.CSSProperties,

  itemBody: {
    flex: 1,
    minWidth: 0,
  } as React.CSSProperties,

  itemTitle: {
    fontSize: 14,
    color: TEXT,
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  } as React.CSSProperties,

  itemDesc: {
    fontSize: 12,
    color: TEXT3,
    marginTop: 1,
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  } as React.CSSProperties,

  shortcut: {
    fontSize: 11,
    color: TEXT3,
    background: SURFACE2,
    padding: '2px 6px',
    borderRadius: 4,
    fontFamily: 'SF Mono, Menlo, monospace',
    border: `1px solid ${BORDER}`,
    flexShrink: 0,
  } as React.CSSProperties,

  empty: {
    padding: '24px 16px',
    textAlign: 'center' as const,
    color: TEXT3,
    fontSize: 14,
  } as React.CSSProperties,

  footer: {
    display: 'flex',
    alignItems: 'center',
    gap: 16,
    padding: '8px 16px',
    borderTop: `1px solid ${BORDER}`,
    fontSize: 11,
    color: TEXT3,
  } as React.CSSProperties,

  footerKey: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
  } as React.CSSProperties,

  kbd: {
    fontSize: 10,
    background: SURFACE2,
    padding: '1px 5px',
    borderRadius: 3,
    border: `1px solid ${BORDER}`,
    fontFamily: 'SF Mono, Menlo, monospace',
    color: TEXT2,
  } as React.CSSProperties,
};

// ── 注入关键帧动画（仅一次）──

let styleInjected = false;
function injectStyles() {
  if (styleInjected) return;
  styleInjected = true;
  const style = document.createElement('style');
  style.textContent = `
    @keyframes cmdkFadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    @keyframes cmdkScaleIn {
      from { opacity: 0; transform: scale(0.95); }
      to { opacity: 1; transform: scale(1); }
    }
  `;
  document.head.appendChild(style);
}

// ── 组件 ──

export function CmdK({ open, onClose, commands }: CmdKProps) {
  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // 注入 CSS 动画
  useEffect(() => { injectStyles(); }, []);

  // 打开时聚焦 & 重置
  useEffect(() => {
    if (open) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // 过滤
  const filtered = useMemo(() => {
    if (!query.trim()) return commands;
    const q = query.toLowerCase();
    return commands.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        (c.description?.toLowerCase().includes(q)) ||
        c.id.toLowerCase().includes(q),
    );
  }, [commands, query]);

  // 按组排列
  const grouped = useMemo(() => {
    const map = new Map<CommandGroup, Command[]>();
    for (const cmd of filtered) {
      const list = map.get(cmd.group) || [];
      list.push(cmd);
      map.set(cmd.group, list);
    }
    const result: { group: CommandGroup; items: Command[] }[] = [];
    for (const g of GROUP_ORDER) {
      const items = map.get(g);
      if (items && items.length > 0) result.push({ group: g, items });
    }
    return result;
  }, [filtered]);

  // flat 列表用于键盘导航
  const flatItems = useMemo(() => grouped.flatMap((g) => g.items), [grouped]);

  // 选中索引 clamp
  useEffect(() => {
    if (selectedIndex >= flatItems.length) setSelectedIndex(Math.max(0, flatItems.length - 1));
  }, [flatItems.length, selectedIndex]);

  // 执行命令
  const execute = useCallback(
    (cmd: Command) => {
      onClose();
      // defer 执行，让面板先关闭
      setTimeout(() => cmd.action(), 50);
    },
    [onClose],
  );

  // 键盘导航
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((i) => (i + 1) % Math.max(1, flatItems.length));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((i) => (i - 1 + flatItems.length) % Math.max(1, flatItems.length));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const cmd = flatItems[selectedIndex];
        if (cmd) execute(cmd);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    },
    [flatItems, selectedIndex, execute, onClose],
  );

  // 滚动选中项到可见区域
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const el = list.querySelector(`[data-cmdk-index="${selectedIndex}"]`) as HTMLElement | null;
    if (el) el.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

  if (!open) return null;

  let flatIdx = 0;

  return (
    <div style={s.overlay} onClick={onClose}>
      <div style={s.panel} onClick={(e) => e.stopPropagation()} onKeyDown={handleKeyDown}>
        {/* 搜索框 */}
        <div style={s.searchWrap}>
          <span style={s.searchIcon}>&#x1F50D;</span>
          <input
            ref={inputRef}
            style={s.searchInput}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            placeholder="搜索或输入命令..."
          />
        </div>

        {/* 结果列表 */}
        <div style={s.list} ref={listRef}>
          {flatItems.length === 0 ? (
            <div style={s.empty}>没有匹配的命令</div>
          ) : (
            grouped.map((g) => (
              <div key={g.group}>
                <div style={s.groupLabel}>{GROUP_LABELS[g.group]}</div>
                {g.items.map((cmd) => {
                  const idx = flatIdx++;
                  const selected = idx === selectedIndex;
                  return (
                    <div
                      key={cmd.id}
                      data-cmdk-index={idx}
                      style={s.item(selected)}
                      onMouseEnter={() => setSelectedIndex(idx)}
                      onClick={() => execute(cmd)}
                    >
                      <span style={s.itemIcon}>{cmd.icon}</span>
                      <div style={s.itemBody}>
                        <div style={s.itemTitle}>{cmd.title}</div>
                        {cmd.description && <div style={s.itemDesc}>{cmd.description}</div>}
                      </div>
                      {cmd.shortcut && <span style={s.shortcut}>{cmd.shortcut}</span>}
                    </div>
                  );
                })}
              </div>
            ))
          )}
        </div>

        {/* 底部提示 */}
        <div style={s.footer}>
          <span style={s.footerKey}>
            <span style={s.kbd}>↑↓</span> 导航
          </span>
          <span style={s.footerKey}>
            <span style={s.kbd}>↵</span> 执行
          </span>
          <span style={s.footerKey}>
            <span style={s.kbd}>Esc</span> 关闭
          </span>
        </div>
      </div>
    </div>
  );
}

// ── 全局快捷键 Hook ──

export function useCmdK() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return { open, setOpen, onClose: () => setOpen(false) };
}
