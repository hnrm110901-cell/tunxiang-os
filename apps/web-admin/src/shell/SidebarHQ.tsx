/**
 * Sidebar-HQ — 二级导航（220px）
 * 决策4：菜单配置引擎驱动，不写死
 * MENU_CONFIGS 定义在 config/menuConfigs.ts
 */
import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { getTokenPayload } from '../api/client';
import { MENU_CONFIGS } from '../config/menuConfigs';

interface SidebarHQProps {
  activeModule: string;
}

export function SidebarHQ({ activeModule }: SidebarHQProps) {
  const [search, setSearch] = useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const config = MENU_CONFIGS[activeModule] || MENU_CONFIGS.dashboard;

  return (
    <aside style={{
      width: 220, background: 'var(--bg-1, #112228)',
      borderRight: '1px solid var(--bg-2, #1a2a33)',
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
    }}>
      {/* 模块标题 + 搜索 */}
      <div style={{ padding: '12px 12px 8px' }}>
        <div style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
          color: 'var(--text-3, #999)', marginBottom: 8,
        }}>
          {activeModule}
        </div>
        <input
          placeholder="搜索菜单..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: '100%', padding: '6px 10px', borderRadius: 6,
            border: '1px solid var(--bg-2, #1a2a33)', background: 'var(--bg-0, #0B1A20)',
            color: 'var(--text-2, #ccc)', fontSize: 12, outline: 'none',
          }}
        />
      </div>

      {/* 菜单分组 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0 8px' }}>
        {config.groups.map((group) => (
          <div key={group.label} style={{ marginBottom: 8 }}>
            <div style={{
              fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
              color: 'var(--text-4, #666)', padding: '8px 4px 4px',
            }}>
              {group.label}
            </div>
            {group.items
              .filter((item) => !search || item.label.includes(search))
              .map((item) => {
                const isActive = location.pathname === item.path || location.pathname.startsWith(item.path + '/');
                return (
                  <div
                    key={item.id}
                    onClick={() => navigate(item.path)}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                      padding: '7px 10px', borderRadius: 8, cursor: 'pointer', fontSize: 13,
                      transition: 'background var(--duration-fast, .15s)',
                      background: isActive ? 'var(--brand-bg, rgba(255,107,44,0.12))' : 'transparent',
                      color: isActive ? 'var(--brand, #FF6B35)' : 'inherit',
                      fontWeight: isActive ? 600 : 400,
                    }}
                    onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--bg-2, #1a2a33)'; }}
                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 14 }}>{item.icon}</span>
                      {item.label}
                    </span>
                    {item.count != null && (
                      <span style={{
                        fontSize: 10, padding: '1px 6px', borderRadius: 10,
                        background: 'var(--brand-bg)', color: 'var(--brand)',
                      }}>
                        {item.count}
                      </span>
                    )}
                  </div>
                );
              })}
          </div>
        ))}
      </div>

      {/* 门店选择器 — 从 JWT 动态读取商户名 */}
      <div style={{
        padding: 12, borderTop: '1px solid var(--bg-2, #1a2a33)',
        display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
      }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--green)' }} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, fontWeight: 600 }}>{getTokenPayload()?.merchant_name || '屯象OS'}</div>
          <div style={{ fontSize: 10, color: 'var(--text-4)' }}>在线</div>
        </div>
        <span style={{ color: 'var(--text-4)', fontSize: 12 }}>▼</span>
      </div>
    </aside>
  );
}
