/**
 * Topbar-HQ — 顶栏（48px，贯穿全宽）
 * Logo + Command Palette 触发器(⌘K) + 通知 + 用户 + 登出
 */
import { useState } from 'react';
import { useLang } from '../i18n/LangContext';

interface TopbarHQProps {
  onToggleAgent: () => void;
  userName?: string;
  userRole?: string;
  onLogout?: () => void;
}

export function TopbarHQ({ onToggleAgent, userName, userRole, onLogout }: TopbarHQProps) {
  const [showUserMenu, setShowUserMenu] = useState(false);
  const { t } = useLang();

  // First character of user name for avatar
  const avatarChar = userName ? userName[0] : '?';

  return (
    <header style={{
      height: 48, background: 'var(--bg-1, #112228)',
      borderBottom: '1px solid var(--bg-2, #1a2a33)',
      display: 'flex', alignItems: 'center', padding: '0 16px', gap: 12,
    }}>
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 140 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 7, background: 'var(--brand)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, fontWeight: 'bold', color: '#fff',
        }}>TX</div>
        <span style={{ fontFamily: 'var(--font-title)', fontWeight: 700, fontSize: 13 }}>屯象OS</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-4)' }}>{t('common.version')}</span>
      </div>

      {/* Command Palette 触发器 */}
      <div style={{
        flex: 1, maxWidth: 480, padding: '6px 12px', borderRadius: 8,
        background: 'var(--bg-0)', border: '1px solid var(--bg-2)',
        display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
      }}>
        <span style={{ fontSize: 14 }}>&#x1F50D;</span>
        <span style={{ fontSize: 12, color: 'var(--text-4)', flex: 1 }}>{t('common.search')}</span>
        <kbd style={{
          padding: '2px 6px', borderRadius: 4, background: 'var(--bg-2)',
          fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)',
        }}>&#x2318;K</kbd>
      </div>

      <div style={{ flex: 1 }} />

      {/* 右侧工具 */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-3)' }}>
        {new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
      </span>

      <button onClick={onToggleAgent} title="Agent Console" style={{
        width: 32, height: 32, border: 'none', borderRadius: 8, cursor: 'pointer',
        background: 'transparent', fontSize: 16,
      }}>&#x1F916;</button>

      <button title={t('common.notification')} style={{
        width: 32, height: 32, border: 'none', borderRadius: 8, cursor: 'pointer',
        background: 'transparent', fontSize: 16, position: 'relative',
      }}>
        &#x1F514;
        <span style={{
          position: 'absolute', top: 2, right: 2, width: 8, height: 8,
          borderRadius: '50%', background: 'var(--red)',
        }} />
      </button>

      {/* 用户区域 — 点击展开菜单 */}
      <div style={{ position: 'relative' }}>
        <button
          onClick={() => setShowUserMenu(!showUserMenu)}
          style={{
            display: 'flex', alignItems: 'center', gap: 8,
            background: 'transparent', border: 'none', cursor: 'pointer',
            padding: '4px 8px', borderRadius: 8,
          }}
        >
          {/* 用户头像 */}
          <div style={{
            width: 28, height: 28, borderRadius: '50%',
            background: 'linear-gradient(135deg, var(--brand, #ff6b2c), var(--purple, #a855f7))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 12, fontWeight: 'bold', color: '#fff',
          }}>{avatarChar}</div>
          {/* 用户名 + 角色 */}
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 12, color: '#fff', fontWeight: 500, lineHeight: 1.2 }}>{userName}</div>
            {userRole && (
              <div style={{ fontSize: 10, color: 'var(--text-4, rgba(255,255,255,0.35))', lineHeight: 1.2 }}>
                {userRole}
              </div>
            )}
          </div>
        </button>

        {/* Dropdown menu */}
        {showUserMenu && (
          <>
            {/* Invisible overlay to close menu on click outside */}
            <div
              onClick={() => setShowUserMenu(false)}
              style={{ position: 'fixed', inset: 0, zIndex: 999 }}
            />
            <div style={{
              position: 'absolute', top: '100%', right: 0, marginTop: 4,
              width: 160, background: 'var(--bg-1, #112228)',
              border: '1px solid var(--bg-2, #1a2a33)',
              borderRadius: 10, padding: 4, zIndex: 1000,
              boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
            }}>
              <button
                onClick={() => {
                  setShowUserMenu(false);
                  onLogout?.();
                }}
                style={{
                  width: '100%', padding: '8px 12px', border: 'none',
                  borderRadius: 8, background: 'transparent', color: '#f87171',
                  fontSize: 13, cursor: 'pointer', textAlign: 'left',
                  display: 'flex', alignItems: 'center', gap: 8,
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
              >
                <span style={{ fontSize: 14 }}>&#x2190;</span>
                {t('common.logout')}
              </button>
            </div>
          </>
        )}
      </div>
    </header>
  );
}
