/**
 * KeyboardShortcutHelp — 快捷键帮助面板
 *
 * 触发方式：
 *   - 按 Ctrl+/ 打开/关闭
 *   - 点击帮助图标（⌨）
 *   - 点击遮罩层关闭
 *
 * 特性：
 *   - 按功能分类展示（收银类/菜品操作/系统功能）
 *   - 支持搜索过滤
 *   - 高亮最近激活的快捷键（0.2秒）
 *
 * 编码规范：TypeScript strict，纯 inline style，Store终端规范
 * 触控规范：所有点击区域 >= 48×48px，字体 >= 16px
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { SHORTCUT_CATEGORIES, type ShortcutDefinition } from '../hooks/useKeyboardShortcuts';

// ─── 颜色常量 ────────────────────────────────────────────────────────────────

const C = {
  bg: 'rgba(11, 26, 32, 0.96)',
  card: '#112228',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentLight: 'rgba(255, 107, 53, 0.15)',
  text: '#E0E0E0',
  textDim: '#8899A6',
  success: '#0F6E56',
  warning: '#BA7517',
  keyBg: '#1E3A48',
  keyActive: '#FF6B35',
  searchBg: 'rgba(255,255,255,0.06)',
  searchBorder: 'rgba(255,255,255,0.15)',
} as const;

const CATEGORY_COLORS: Record<string, string> = {
  cashier: '#0F6E56',
  dish: '#185FA5',
  system: '#BA7517',
};

const CATEGORY_BADGE_LABELS: Record<string, string> = {
  cashier: '收银',
  dish: '菜品',
  system: '系统',
};

// ─── Props ───────────────────────────────────────────────────────────────────

interface KeyboardShortcutHelpProps {
  /** 面板是否可见 */
  visible: boolean;
  /** 关闭面板 */
  onClose: () => void;
  /** 最近激活的快捷键（0.2秒高亮，由 useKeyboardShortcuts 的 activeKey 传入） */
  activeKey?: string | null;
}

// ─── 注入动画样式 ─────────────────────────────────────────────────────────────

function ensureHelpPanelStyle(): void {
  const STYLE_ID = 'tx-kbd-help-style';
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = `
    @keyframes tx-kbd-panel-in {
      from { opacity: 0; transform: translateY(-12px) scale(0.97); }
      to   { opacity: 1; transform: translateY(0) scale(1); }
    }
    @keyframes tx-kbd-key-flash {
      0%   { background-color: #FF6B35; color: #fff; }
      100% { background-color: #1E3A48; color: #E0E0E0; }
    }
  `;
  document.head.appendChild(style);
}

// ─── 快捷键标签组件 ────────────────────────────────────────────────────────────

function KeyBadge({ keyStr, active }: { keyStr: string; active: boolean }) {
  const parts = keyStr.split('+');
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
      {parts.map((part, i) => (
        <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              minWidth: 40,
              height: 32,
              padding: '0 8px',
              borderRadius: 6,
              backgroundColor: active ? C.keyActive : C.keyBg,
              color: active ? '#fff' : C.text,
              fontSize: 14,
              fontWeight: 700,
              fontFamily: 'monospace',
              border: active ? 'none' : `1px solid ${C.border}`,
              transition: 'background-color 0.15s ease, color 0.15s ease',
              animation: active ? 'tx-kbd-key-flash 0.2s ease-out' : 'none',
              boxShadow: active ? `0 0 8px ${C.accent}66` : '0 1px 2px rgba(0,0,0,0.3)',
            }}
          >
            {part}
          </span>
          {i < parts.length - 1 && (
            <span style={{ color: C.textDim, fontSize: 12, fontWeight: 600 }}>+</span>
          )}
        </span>
      ))}
    </span>
  );
}

// ─── 主组件 ──────────────────────────────────────────────────────────────────

export function KeyboardShortcutHelp({ visible, onClose, activeKey }: KeyboardShortcutHelpProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const searchRef = useRef<HTMLInputElement>(null);

  ensureHelpPanelStyle();

  // 打开时自动聚焦搜索框
  useEffect(() => {
    if (visible && searchRef.current) {
      setTimeout(() => searchRef.current?.focus(), 50);
    }
    if (!visible) {
      setSearchQuery('');
    }
  }, [visible]);

  // Escape 关闭（独立监听，不经过 useKeyboardShortcuts 避免冲突）
  useEffect(() => {
    if (!visible) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', handler, { capture: true });
    return () => window.removeEventListener('keydown', handler, { capture: true });
  }, [visible, onClose]);

  const handleOverlayClick = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose();
  }, [onClose]);

  // ── 搜索过滤 ──────────────────────────────────────────────────────────────

  const filterShortcuts = useCallback((shortcuts: ShortcutDefinition[]): ShortcutDefinition[] => {
    if (!searchQuery.trim()) return shortcuts;
    const q = searchQuery.trim().toLowerCase();
    return shortcuts.filter(
      (s) => s.description.toLowerCase().includes(q) || s.key.toLowerCase().includes(q),
    );
  }, [searchQuery]);

  if (!visible) return null;

  // ── 样式 ─────────────────────────────────────────────────────────────────

  const overlayStyle: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    zIndex: 9999,
    backgroundColor: C.bg,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'flex-start',
    padding: '40px 24px 32px',
    overflowY: 'auto',
    WebkitOverflowScrolling: 'touch',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
  };

  const panelStyle: React.CSSProperties = {
    width: '100%',
    maxWidth: 900,
    animation: 'tx-kbd-panel-in 0.25s ease-out',
  };

  return (
    <div style={overlayStyle} onClick={handleOverlayClick}>
      <div style={panelStyle}>

        {/* ── 标题行 ── */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 28,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 28, color: C.accent, lineHeight: 1 }}>⌨</span>
            <h2 style={{ margin: 0, color: '#FFFFFF', fontSize: 24, fontWeight: 700 }}>
              POS 快捷键
            </h2>
            <span style={{
              padding: '4px 10px',
              borderRadius: 20,
              backgroundColor: C.accentLight,
              color: C.accent,
              fontSize: 14,
              fontWeight: 700,
            }}>
              与天财商龙对齐
            </span>
          </div>

          {/* 关闭按钮 */}
          <button
            type="button"
            onClick={onClose}
            style={{
              minWidth: 48,
              minHeight: 48,
              padding: '8px 16px',
              borderRadius: 10,
              border: `1px solid ${C.border}`,
              backgroundColor: 'transparent',
              color: C.textDim,
              fontSize: 18,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'transform 200ms ease',
            }}
            onPointerDown={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.95)'; }}
            onPointerUp={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
            onPointerCancel={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
          >
            ✕
          </button>
        </div>

        {/* ── 搜索框 ── */}
        <div style={{ marginBottom: 28, position: 'relative' }}>
          <span style={{
            position: 'absolute',
            left: 16,
            top: '50%',
            transform: 'translateY(-50%)',
            color: C.textDim,
            fontSize: 18,
            pointerEvents: 'none',
          }}>
            🔍
          </span>
          <input
            ref={searchRef}
            type="text"
            placeholder="搜索快捷键（功能名称或按键）..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              width: '100%',
              height: 52,
              paddingLeft: 48,
              paddingRight: 16,
              borderRadius: 12,
              border: `1px solid ${C.searchBorder}`,
              backgroundColor: C.searchBg,
              color: '#FFFFFF',
              fontSize: 18,
              outline: 'none',
              boxSizing: 'border-box',
            }}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              style={{
                position: 'absolute',
                right: 12,
                top: '50%',
                transform: 'translateY(-50%)',
                minWidth: 32,
                minHeight: 32,
                border: 'none',
                background: 'transparent',
                color: C.textDim,
                fontSize: 18,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              ✕
            </button>
          )}
        </div>

        {/* ── 分类快捷键列表 ── */}
        {Object.entries(SHORTCUT_CATEGORIES).map(([categoryKey, category]) => {
          const filtered = filterShortcuts(category.shortcuts);
          if (filtered.length === 0) return null;
          const color = CATEGORY_COLORS[categoryKey] ?? C.accent;
          const badgeLabel = CATEGORY_BADGE_LABELS[categoryKey] ?? categoryKey;

          return (
            <section key={categoryKey} style={{ marginBottom: 32 }}>
              {/* 分类标题 */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                marginBottom: 16,
                paddingBottom: 10,
                borderBottom: `1px solid ${C.border}`,
              }}>
                <span style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 32,
                  height: 32,
                  borderRadius: 8,
                  backgroundColor: `${color}25`,
                  color,
                  fontSize: 13,
                  fontWeight: 700,
                }}>
                  {badgeLabel}
                </span>
                <h3 style={{
                  margin: 0,
                  color: '#FFFFFF',
                  fontSize: 20,
                  fontWeight: 700,
                }}>
                  {category.label}
                </h3>
                <span style={{
                  padding: '2px 8px',
                  borderRadius: 10,
                  backgroundColor: `${color}20`,
                  color,
                  fontSize: 14,
                  fontWeight: 600,
                }}>
                  {filtered.length}
                </span>
              </div>

              {/* 快捷键网格 */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))',
                gap: 12,
              }}>
                {filtered.map((shortcut) => {
                  const isActive = activeKey === shortcut.key;
                  return (
                    <div
                      key={shortcut.key}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: 12,
                        padding: '12px 16px',
                        borderRadius: 12,
                        backgroundColor: isActive ? `${C.accent}18` : C.card,
                        border: `1px solid ${isActive ? C.accent : C.border}`,
                        minHeight: 52,
                        transition: 'background-color 0.15s ease, border-color 0.15s ease',
                      }}
                    >
                      {/* 功能说明 */}
                      <span style={{
                        color: C.text,
                        fontSize: 17,
                        fontWeight: 500,
                        flex: 1,
                        minWidth: 0,
                      }}>
                        {shortcut.description}
                      </span>

                      {/* 按键标签 */}
                      <KeyBadge keyStr={shortcut.key} active={isActive} />
                    </div>
                  );
                })}
              </div>
            </section>
          );
        })}

        {/* 搜索无结果 */}
        {searchQuery && Object.values(SHORTCUT_CATEGORIES).every(
          (c) => filterShortcuts(c.shortcuts).length === 0,
        ) && (
          <div style={{
            textAlign: 'center',
            color: C.textDim,
            fontSize: 18,
            padding: '48px 0',
          }}>
            未找到与 "{searchQuery}" 相关的快捷键
          </div>
        )}

        {/* ── 底部提示 ── */}
        <div style={{
          marginTop: 8,
          paddingTop: 20,
          borderTop: `1px solid ${C.border}`,
          display: 'flex',
          flexWrap: 'wrap',
          gap: 20,
          color: C.textDim,
          fontSize: 16,
        }}>
          <span>按 <strong style={{ color: C.text }}>Ctrl+/</strong> 或 <strong style={{ color: C.text }}>Esc</strong> 关闭此面板</span>
          <span>按住 <strong style={{ color: C.text }}>Alt</strong> 键查看简易浮层</span>
          <span>触控设备设置 <strong style={{ color: C.text }}>键盘模式</strong> 后可使用快捷键</span>
        </div>
      </div>
    </div>
  );
}

// ─── 触发按钮（可嵌入侧边栏/设置菜单）──────────────────────────────────────

interface KeyboardHelpTriggerProps {
  onClick: () => void;
}

export function KeyboardHelpTrigger({ onClick }: KeyboardHelpTriggerProps) {
  return (
    <button
      type="button"
      title="快捷键帮助 (Ctrl+/)"
      onClick={onClick}
      style={{
        minWidth: 48,
        minHeight: 48,
        padding: '8px 12px',
        borderRadius: 10,
        border: '1px solid rgba(255,255,255,0.15)',
        backgroundColor: 'rgba(255,255,255,0.06)',
        color: '#8899A6',
        fontSize: 20,
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'transform 200ms ease, background-color 200ms ease',
      }}
      onPointerDown={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(0.94)'; }}
      onPointerUp={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
      onPointerCancel={(e) => { (e.currentTarget as HTMLElement).style.transform = 'scale(1)'; }}
    >
      ⌨
    </button>
  );
}
