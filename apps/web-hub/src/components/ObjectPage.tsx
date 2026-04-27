/**
 * Object Page — 八 Tab 通用详情框架
 *
 * 设计参考 Stripe Inspector Object Detail Page。
 * 提供统一的 Header + Tab 栏 + 内容区结构，各 Workspace 注入 Tab 内容。
 */
import { useRef, useEffect, useCallback } from 'react';

// ── 颜色常量 ──
const SURFACE = '#0E1E24';
const SURFACE2 = '#132932';
const SURFACE3 = '#1A3540';
const BORDER = '#1A3540';
const TEXT = '#E6EDF1';
const TEXT2 = '#94A8B3';
const TEXT3 = '#647985';
const ORANGE = '#FF6B2C';
const GREEN = '#22C55E';
const YELLOW = '#F59E0B';
const RED = '#EF4444';

// ── 类型定义 ──

export type ObjectStatus = 'healthy' | 'warning' | 'critical' | 'offline' | 'unknown';

export interface TabConfig {
  key: string;
  label: string;
  badge?: number;
  disabled?: boolean;
}

export interface ActionButton {
  label: string;
  icon?: string;
  variant?: 'default' | 'primary' | 'danger';
  shortcut?: string;
  onClick: () => void;
}

export interface ObjectPageProps {
  id: string;
  name: string;
  type: string;
  status: ObjectStatus;
  subtitle: React.ReactNode;
  actions?: ActionButton[];
  tabs: TabConfig[];
  activeTab?: string;
  onTabChange?: (tab: string) => void;
  children: React.ReactNode;
}

// ── 默认八 Tab ──

export const DEFAULT_TABS: TabConfig[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'timeline', label: 'Timeline' },
  { key: 'traces', label: 'Traces' },
  { key: 'cost', label: 'Cost' },
  { key: 'logs', label: 'Logs' },
  { key: 'related', label: 'Related' },
  { key: 'actions', label: 'Actions' },
  { key: 'playbooks', label: 'Playbooks' },
];

// ── 状态颜色 ──

const STATUS_COLOR: Record<ObjectStatus, string> = {
  healthy: GREEN,
  warning: YELLOW,
  critical: RED,
  offline: TEXT3,
  unknown: TEXT3,
};

const STATUS_LABEL: Record<ObjectStatus, string> = {
  healthy: '正常',
  warning: '警告',
  critical: '严重',
  offline: '离线',
  unknown: '未知',
};

// ── 样式 ──

const s = {
  container: {
    display: 'flex',
    flexDirection: 'column' as const,
    height: '100%',
    color: TEXT,
  } as React.CSSProperties,

  // Header
  header: {
    background: SURFACE,
    padding: '20px 24px 0',
    borderBottom: `1px solid ${BORDER}`,
    flexShrink: 0,
  } as React.CSSProperties,

  headerTop: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 8,
  } as React.CSSProperties,

  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    minWidth: 0,
  } as React.CSSProperties,

  statusDot: (status: ObjectStatus) => ({
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: STATUS_COLOR[status],
    flexShrink: 0,
    ...(status === 'critical'
      ? { boxShadow: `0 0 0 3px ${RED}33`, animation: 'objectPagePulse 1.5s ease-in-out infinite' }
      : {}),
  }) as React.CSSProperties,

  name: {
    fontSize: 20,
    fontWeight: 700,
    color: TEXT,
    whiteSpace: 'nowrap' as const,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  } as React.CSSProperties,

  idTag: {
    fontSize: 12,
    fontFamily: 'SF Mono, Menlo, monospace',
    color: TEXT2,
    background: SURFACE3,
    padding: '2px 8px',
    borderRadius: 4,
    flexShrink: 0,
  } as React.CSSProperties,

  statusTag: (status: ObjectStatus) => ({
    fontSize: 11,
    fontWeight: 600,
    color: STATUS_COLOR[status],
    background: STATUS_COLOR[status] + '18',
    padding: '2px 8px',
    borderRadius: 4,
    flexShrink: 0,
  }) as React.CSSProperties,

  subtitle: {
    fontSize: 13,
    color: TEXT3,
    marginBottom: 14,
  } as React.CSSProperties,

  // Actions
  actions: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexShrink: 0,
  } as React.CSSProperties,

  actionBtn: (variant: 'default' | 'primary' | 'danger') => {
    const base: React.CSSProperties = {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '6px 14px',
      fontSize: 13,
      fontWeight: 500,
      borderRadius: 6,
      cursor: 'pointer',
      border: 'none',
      transition: 'opacity 0.15s',
      fontFamily: 'inherit',
    };
    if (variant === 'primary') {
      return { ...base, background: ORANGE, color: '#fff' } as React.CSSProperties;
    }
    if (variant === 'danger') {
      return { ...base, background: RED + '22', color: RED, border: `1px solid ${RED}44` } as React.CSSProperties;
    }
    return { ...base, background: SURFACE3, color: TEXT2, border: `1px solid ${BORDER}` } as React.CSSProperties;
  },

  actionShortcut: {
    fontSize: 10,
    color: TEXT3,
    fontFamily: 'SF Mono, Menlo, monospace',
    marginLeft: 4,
  } as React.CSSProperties,

  // Tab bar
  tabBar: {
    display: 'flex',
    gap: 0,
    overflowX: 'auto' as const,
    scrollbarWidth: 'none' as const,
  } as React.CSSProperties,

  tab: (active: boolean, disabled: boolean) => ({
    padding: '10px 18px',
    fontSize: 13,
    fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer',
    color: disabled ? TEXT3 + '66' : active ? ORANGE : TEXT3,
    borderBottom: active ? `2px solid ${ORANGE}` : '2px solid transparent',
    background: 'transparent',
    border: 'none',
    borderBottomStyle: 'solid' as const,
    borderBottomWidth: 2,
    transition: 'color 0.15s',
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    whiteSpace: 'nowrap' as const,
    opacity: disabled ? 0.5 : 1,
    fontFamily: 'inherit',
    flexShrink: 0,
  }) as React.CSSProperties,

  tabBadge: {
    fontSize: 10,
    fontWeight: 700,
    color: TEXT,
    background: ORANGE,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '0 5px',
  } as React.CSSProperties,

  // Content
  content: {
    flex: 1,
    overflow: 'auto',
    padding: 24,
  } as React.CSSProperties,
};

// ── 注入关键帧（仅一次）──

let styleInjected = false;
function injectStyles() {
  if (styleInjected) return;
  styleInjected = true;
  const style = document.createElement('style');
  style.textContent = `
    @keyframes objectPagePulse {
      0%, 100% { box-shadow: 0 0 0 3px ${RED}33; }
      50% { box-shadow: 0 0 0 6px ${RED}55; }
    }
    .object-page-tab-bar::-webkit-scrollbar { display: none; }
  `;
  document.head.appendChild(style);
}

// ── 组件 ──

export function ObjectPage({
  id,
  name,
  type,
  status,
  subtitle,
  actions,
  tabs,
  activeTab,
  onTabChange,
  children,
}: ObjectPageProps) {
  const tabBarRef = useRef<HTMLDivElement>(null);
  const resolvedActive = activeTab || (tabs.length > 0 ? tabs[0].key : '');

  useEffect(() => { injectStyles(); }, []);

  // 滚动 active tab 可见
  useEffect(() => {
    const bar = tabBarRef.current;
    if (!bar) return;
    const el = bar.querySelector(`[data-tab-key="${resolvedActive}"]`) as HTMLElement | null;
    if (el) el.scrollIntoView({ inline: 'nearest', block: 'nearest' });
  }, [resolvedActive]);

  const handleTabClick = useCallback(
    (tab: TabConfig) => {
      if (tab.disabled) return;
      onTabChange?.(tab.key);
    },
    [onTabChange],
  );

  return (
    <div style={s.container}>
      {/* Header */}
      <div style={s.header}>
        <div style={s.headerTop}>
          <div style={s.headerLeft}>
            <span style={s.statusDot(status)} title={STATUS_LABEL[status]} />
            <span style={s.name}>{name}</span>
            <span style={s.idTag}>#{id}</span>
            <span style={s.statusTag(status)}>{STATUS_LABEL[status]}</span>
          </div>
          {actions && actions.length > 0 && (
            <div style={s.actions}>
              {actions.map((a) => (
                <button
                  key={a.label}
                  style={s.actionBtn(a.variant || 'default')}
                  onClick={a.onClick}
                >
                  {a.icon && <span>{a.icon}</span>}
                  {a.label}
                  {a.shortcut && <span style={s.actionShortcut}>{a.shortcut}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
        <div style={s.subtitle}>{subtitle}</div>

        {/* Tab 栏 */}
        <div ref={tabBarRef} style={s.tabBar} className="object-page-tab-bar">
          {tabs.map((tab) => {
            const active = tab.key === resolvedActive;
            return (
              <button
                key={tab.key}
                data-tab-key={tab.key}
                style={s.tab(active, !!tab.disabled)}
                onClick={() => handleTabClick(tab)}
              >
                {tab.label}
                {tab.badge != null && tab.badge > 0 && <span style={s.tabBadge}>{tab.badge}</span>}
              </button>
            );
          })}
        </div>
      </div>

      {/* 内容区 */}
      <div style={s.content}>{children}</div>
    </div>
  );
}
