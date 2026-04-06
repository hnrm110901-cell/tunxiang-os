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
      { label: '外卖', items: [
        { id: 'delivery', label: '外卖聚合', icon: '🛵', count: 0, path: '/hq/trade/delivery' },
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
      { label: 'AI 决策', items: [
        { id: 'menu-optimize', label: 'AI排菜建议', icon: '🧠', path: '/menu/optimize' },
      ]},
      { label: '研发', items: [
        { id: 'new-dish', label: '新菜研发', icon: '🧪', path: '/menu/rd' },
        { id: 'quality', label: '质量检测', icon: '✅', path: '/menu/quality' },
      ]},
    ],
  },
  analytics: {
    moduleId: 'analytics', groups: [
      { label: '驾驶舱', items: [
        { id: 'analytics-dashboard', label: '经营驾驶舱', icon: '🖥️', path: '/analytics/dashboard' },
      ]},
      { label: '分析', items: [
        { id: 'daily', label: '日报', icon: '📰', path: '/analytics/daily' },
        { id: 'kpi', label: 'KPI 监控', icon: '🎯', path: '/analytics/kpi' },
        { id: 'cost', label: '成本分析', icon: '💰', path: '/analytics/cost' },
        { id: 'waste', label: '损耗分析', icon: '🗑️', count: 3, path: '/analytics/waste' },
        { id: 'finance-analysis', label: '财务分析', icon: '💹', path: '/hq/analytics/finance' },
        { id: 'pl-report', label: '损益表P&L', icon: '💹', path: '/hq/analytics/pl-report' },
        { id: 'member-analysis', label: '会员分析', icon: '👥', path: '/hq/analytics/member' },
        { id: 'budget-tracker', label: '预算追踪', icon: '📊', path: '/hq/analytics/budget' },
      ]},
      { label: '决策', items: [
        { id: 'decisions', label: 'AI 决策', icon: '🧠', count: 5, path: '/analytics/decisions' },
        { id: 'scenarios', label: '场景识别', icon: '🔍', path: '/analytics/scenarios' },
      ]},
    ],
  },
  growth: {
    moduleId: 'growth', groups: [
      { label: '增长中枢', items: [
        { id: 'growth-dashboard', label: '增长驾驶舱', icon: '🚀', path: '/hq/growth/dashboard' },
      ]},
      { label: '客户资产', items: [
        { id: 'customer-pool', label: '客户总池', icon: '👥', path: '/hq/growth/customers' },
      ]},
      { label: '人群标签', items: [
        { id: 'segments', label: '规则分群', icon: '🎯', path: '/hq/growth/segments' },
        { id: 'segment-tags', label: '增长标签', icon: '🏷️', path: '/hq/growth/segment-tags' },
      ]},
      { label: '旅程编排', items: [
        { id: 'journey-templates', label: '旅程模板', icon: '📋', path: '/hq/growth/journey-templates' },
        { id: 'journey-runs', label: '运行中心', icon: '▶️', path: '/hq/growth/journey-runs' },
        { id: 'journey-monitor', label: '旅程执行监控', icon: '🗺️', path: '/hq/growth/journey-monitor' },
      ]},
      { label: '触达与权益', items: [
        { id: 'offer-packs', label: '权益策略台', icon: '🎁', path: '/hq/growth/offer-packs' },
        { id: 'offers', label: '优惠中心', icon: '🎫', path: '/hq/growth/offers' },
        { id: 'channels', label: '渠道触达', icon: '📡', path: '/hq/growth/channels' },
        { id: 'content', label: '内容中心', icon: '📝', path: '/hq/growth/content' },
      ]},
      { label: '私域复购Agent', items: [
        { id: 'agent-workbench', label: 'Agent工作台', icon: '🤖', path: '/hq/growth/agent-workbench' },
      ]},
      { label: '归因复盘', items: [
        { id: 'growth-roi', label: 'ROI总览', icon: '💰', path: '/hq/growth/roi' },
        { id: 'journey-attribution', label: '旅程归因', icon: '📊', path: '/hq/growth/journey-attribution' },
      ]},
      { label: '配置', items: [
        { id: 'growth-settings', label: '配置治理', icon: '⚙️', path: '/hq/growth/settings' },
      ]},
      { label: '营销工具', items: [
        { id: 'referral', label: '裂变中心', icon: '🔗', path: '/hq/growth/referral' },
        { id: 'group-buy', label: '团购管理', icon: '🛒', path: '/hq/growth/group-buy' },
        { id: 'stamp-card', label: '集章卡', icon: '🎴', path: '/hq/growth/stamp-card' },
        { id: 'member-cards', label: '储值卡与积分', icon: '💳', path: '/hq/growth/member-cards' },
      ]},
    ],
  },
  finance: {
    moduleId: 'finance', groups: [
      { label: '财务分析', items: [
        { id: 'finance-analysis', label: '财务分析', icon: '💹', path: '/hq/analytics/finance' },
        { id: 'pl-report', label: '损益表 P&L', icon: '📊', path: '/hq/analytics/pl-report' },
        { id: 'budget-tracker', label: '预算追踪', icon: '🎯', path: '/hq/analytics/budget' },
      ]},
      { label: 'AI 稽核', items: [
        { id: 'finance-audit', label: 'AI 财务稽核', icon: '🔍', path: '/finance/audit' },
      ]},
    ],
  },
  org: {
    moduleId: 'org', groups: [
      { label: '组织管理', items: [
        { id: 'hr-dashboard', label: '人力管理',     icon: '👥', path: '/hq/org/hr'          },
        { id: 'franchise',    label: '加盟管理',     icon: '🏪', path: '/franchise-dashboard' },
      ]},
      { label: '人事管理', items: [
        { id: 'payroll-configs',  label: '薪资方案配置', icon: '⚙️', path: '/org/payroll-configs'  },
        { id: 'payroll-records',  label: '月度薪资管理', icon: '💴', path: '/org/payroll-records'  },
        { id: 'payroll-manage',   label: '薪资总览',     icon: '📋', path: '/payroll-manage'        },
        { id: 'attendance',       label: '考勤管理',     icon: '🕐', path: '/org/attendance'        },
      ]},
    ],
  },
  ops: {
    moduleId: 'ops', groups: [
      { label: '经营管理', items: [
        { id: 'ops-dashboard', label: '经营驾驶舱', icon: '📊', path: '/hq/ops/dashboard' },
        { id: 'store-analysis', label: '门店分析', icon: '🏪', path: '/hq/ops/store-analysis' },
        { id: 'dish-analysis', label: '菜品分析', icon: '🍜', path: '/hq/ops/dish-analysis' },
        { id: 'smart-specials', label: '今日特供', icon: '🍽️', path: '/hq/ops/smart-specials' },
      ]},
      { label: '巡检质控', items: [
        { id: 'patrol-inspection', label: 'AI巡店质检', icon: '🔍', path: '/ops/patrol-inspection' },
      ]},
      { label: '实时监控', items: [
        { id: 'cruise-monitor', label: '营业巡航', icon: '🚢', path: '/hq/ops/cruise' },
        { id: 'peak-monitor', label: '高峰值守', icon: '🔥', path: '/hq/ops/peak-monitor' },
        { id: 'daily-review', label: '日清追踪', icon: '📅', path: '/hq/ops/daily-review' },
      ]},
      { label: '管控', items: [
        { id: 'approvals', label: '审批中心', icon: '✅', count: 4, path: '/hq/ops/approvals' },
        { id: 'operation-plans', label: '高风险待确认', icon: '⚡', path: '/hq/ops/operation-plans' },
        { id: 'alerts', label: '异常中心', icon: '🚨', count: 5, path: '/hq/ops/alerts' },
        { id: 'review', label: '复盘中心', icon: '📋', path: '/hq/ops/review' },
        { id: 'regional', label: '区域追踪', icon: '🗺️', count: 3, path: '/hq/ops/regional' },
        { id: 'hr-dashboard', label: '人力管理', icon: '👥', path: '/hq/org/hr' },
      ]},
      { label: '供应链', items: [
        { id: 'inventory-intel', label: '智能补货', icon: '📦', path: '/hq/supply/inventory-intel' },
        { id: 'supply-chain', label: '收货与调拨', icon: '🚛', path: '/hq/supply/chain' },
      ]},
      { label: '配置', items: [
        { id: 'settings', label: '模板配置', icon: '⚙️', path: '/hq/ops/settings' },
        { id: 'receipt-editor', label: '小票模板', icon: '🧾', path: '/receipt-editor' },
        { id: 'event-bus-health', label: '事件总线监控', icon: '🔄', path: '/hq/ops/event-bus-health' },
        { id: 'store-clone', label: '快速开店', icon: '🏪', path: '/hq/ops/store-clone' },
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
