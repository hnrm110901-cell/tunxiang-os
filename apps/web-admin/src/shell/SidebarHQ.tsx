/**
 * Sidebar-HQ — 二级导航（220px）
 * 决策4：菜单配置引擎驱动，不写死
 */
import { useState } from 'react';
import { getTokenPayload } from '../api/client';

// 菜单配置引擎的数据结构（决策4）
interface MenuConfig {
  moduleId: string;
  groups: {
    label: string;
    items: { id: string; label: string; icon: string; count?: number; path: string }[];
  }[];
}

// 动态菜单配置（从后端加载，此处 demo 数据）
const MENU_CONFIGS: Record<string, MenuConfig> = {
  dashboard: {
    moduleId: 'dashboard', groups: [
      { label: '总览', items: [
        { id: 'hq-dashboard', label: '经营驾驶舱', icon: '📊', path: '/dashboard' },
        { id: 'store-health', label: '门店健康', icon: '🏥', path: '/store-health' },
        { id: 'agent-monitor', label: 'Agent 监控', icon: '🤖', path: '/agents' },
        { id: 'daily-plan', label: '每日计划', icon: '📋', path: '/daily-plan' },
      ]},
    ],
  },
  trade: {
    moduleId: 'trade', groups: [
      { label: '交易管理', items: [
        { id: 'orders', label: '订单列表', icon: '📋', count: 12, path: '/trade/orders' },
        { id: 'payments', label: '支付记录', icon: '💳', path: '/trade/payments' },
        { id: 'settlements', label: '日结/班结', icon: '📑', path: '/trade/settlements' },
        { id: 'refunds', label: '退款管理', icon: '↩️', path: '/trade/refunds' },
      ]},
    ],
  },
  menu: {
    moduleId: 'menu', groups: [
      { label: '菜品', items: [
        { id: 'dish-list', label: '菜品列表', icon: '🍜', path: '/menu/dishes' },
        { id: 'categories', label: '分类管理', icon: '📂', path: '/menu/categories' },
        { id: 'bom', label: 'BOM 配方', icon: '📐', path: '/menu/bom' },
        { id: 'ranking', label: '菜单排名', icon: '🏆', path: '/menu/ranking' },
        { id: 'pricing', label: '定价仿真', icon: '💲', path: '/menu/pricing' },
      ]},
      { label: '研发', items: [
        { id: 'new-dish', label: '新菜研发', icon: '🧪', path: '/menu/rd' },
        { id: 'quality', label: '质量检测', icon: '✅', path: '/menu/quality' },
      ]},
    ],
  },
  analytics: {
    moduleId: 'analytics', groups: [
      { label: '分析', items: [
        { id: 'daily', label: '日报', icon: '📰', path: '/analytics/daily' },
        { id: 'kpi', label: 'KPI 监控', icon: '🎯', path: '/analytics/kpi' },
        { id: 'cost', label: '成本分析', icon: '💰', path: '/analytics/cost' },
        { id: 'waste', label: '损耗分析', icon: '🗑️', count: 3, path: '/analytics/waste' },
      ]},
      { label: '决策', items: [
        { id: 'decisions', label: 'AI 决策', icon: '🧠', count: 5, path: '/analytics/decisions' },
        { id: 'scenarios', label: '场景识别', icon: '🔍', path: '/analytics/scenarios' },
      ]},
    ],
  },
};

interface SidebarHQProps {
  activeModule: string;
}

export function SidebarHQ({ activeModule }: SidebarHQProps) {
  const [search, setSearch] = useState('');
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
              .map((item) => (
                <div
                  key={item.id}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '7px 10px', borderRadius: 8, cursor: 'pointer', fontSize: 13,
                    transition: 'background var(--duration-fast, .15s)',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--bg-2, #1a2a33)')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
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
              ))}
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
