/**
 * GlobalSearch -- Ctrl+K / Cmd+K 全局搜索弹窗
 * 搜索范围：页面路由 + 功能快捷入口 + 最近访问
 */
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

// ---------- 数据结构 ----------

interface SearchItem {
  id: string;
  label: string;
  icon: string;
  path: string;
  group: string;       // 所属模块/分组
  category: 'page' | 'feature' | 'recent';
  keywords?: string[]; // 额外搜索关键词
}

// ---------- 搜索索引（从侧边栏菜单配置提取） ----------

const SEARCH_INDEX: SearchItem[] = [
  // --- 驾驶舱 ---
  { id: 'hq-dashboard', label: '经营驾驶舱', icon: '📊', path: '/dashboard', group: '驾驶舱', category: 'page', keywords: ['首页', '总览'] },
  { id: 'store-health', label: '门店健康', icon: '🏥', path: '/store-health', group: '驾驶舱', category: 'page' },
  { id: 'agent-monitor', label: 'Agent 监控', icon: '🤖', path: '/agents', group: '驾驶舱', category: 'page' },
  { id: 'daily-plan', label: '每日计划', icon: '📋', path: '/daily-plan', group: '驾驶舱', category: 'page' },

  // --- 交易 ---
  { id: 'orders', label: '订单列表', icon: '📋', path: '/trade/orders', group: '交易', category: 'page', keywords: ['订单查询', '订单搜索'] },
  { id: 'payments', label: '支付记录', icon: '💳', path: '/trade/payments', group: '交易', category: 'page' },
  { id: 'settlements', label: '日结/班结', icon: '📑', path: '/trade/settlements', group: '交易', category: 'page' },
  { id: 'refunds', label: '退款管理', icon: '↩️', path: '/trade/refunds', group: '交易', category: 'page' },
  { id: 'delivery', label: '外卖聚合', icon: '🛵', path: '/hq/trade/delivery', group: '交易', category: 'page' },
  { id: 'delivery-hub', label: '外卖管理中心', icon: '📦', path: '/delivery/hub', group: '交易', category: 'page' },

  // --- 菜品 ---
  { id: 'dish-list', label: '菜品列表', icon: '🍜', path: '/menu/dishes', group: '菜品', category: 'page', keywords: ['菜品管理', '菜单'] },
  { id: 'categories', label: '分类管理', icon: '📂', path: '/menu/categories', group: '菜品', category: 'page' },
  { id: 'bom', label: 'BOM 配方', icon: '📐', path: '/menu/bom', group: '菜品', category: 'page' },
  { id: 'ranking', label: '菜单排名', icon: '🏆', path: '/menu/ranking', group: '菜品', category: 'page' },
  { id: 'pricing', label: '定价仿真', icon: '💲', path: '/menu/pricing', group: '菜品', category: 'page' },
  { id: 'dish-specs', label: '规格管理', icon: '⚙️', path: '/menu/specs', group: '菜品', category: 'page' },
  { id: 'dish-sort', label: '排序管理', icon: '↕️', path: '/menu/sort', group: '菜品', category: 'page' },
  { id: 'dish-batch', label: '批量操作', icon: '📦', path: '/menu/batch', group: '菜品', category: 'page' },
  { id: 'menu-optimize', label: 'AI排菜建议', icon: '🧠', path: '/menu/optimize', group: '菜品', category: 'feature' },
  { id: 'new-dish', label: '新菜研发', icon: '🧪', path: '/menu/rd', group: '菜品', category: 'page' },
  { id: 'quality', label: '质量检测', icon: '✅', path: '/menu/quality', group: '菜品', category: 'page' },

  // --- 会员 ---
  { id: 'crm', label: 'CDP 会员列表', icon: '👤', path: '/crm', group: '会员', category: 'page', keywords: ['会员查询', '会员管理'] },
  { id: 'member-tiers', label: '等级体系', icon: '🏆', path: '/member/tiers', group: '会员', category: 'page' },
  { id: 'member-insight', label: 'AI 会员洞察', icon: '🧠', path: '/member/insight', group: '会员', category: 'feature' },
  { id: 'customer-service', label: '客服工单管理', icon: '🎧', path: '/member/customer-service', group: '会员', category: 'page' },

  // --- 增长 ---
  { id: 'growth-dashboard', label: '增长驾驶舱', icon: '🚀', path: '/hq/growth/dashboard', group: '增长', category: 'page' },
  { id: 'growth-roi', label: 'ROI总览', icon: '💰', path: '/hq/growth/roi', group: '增长', category: 'page' },
  { id: 'segments', label: '人群分层', icon: '👥', path: '/hq/growth/segments', group: '增长', category: 'page' },
  { id: 'journeys', label: '旅程管理', icon: '📍', path: '/hq/growth/journeys', group: '增长', category: 'page' },
  { id: 'journey-monitor', label: '旅程执行监控', icon: '🗺️', path: '/hq/growth/journey-monitor', group: '增长', category: 'page' },
  { id: 'member-cards', label: '储值卡与积分', icon: '💳', path: '/hq/growth/member-cards', group: '增长', category: 'page' },
  { id: 'campaigns', label: '活动管理', icon: '🎯', path: '/growth/campaigns', group: '增长', category: 'page' },
  { id: 'offers', label: '优惠中心', icon: '🎫', path: '/hq/growth/offers', group: '增长', category: 'page' },
  { id: 'content', label: '内容中心', icon: '📝', path: '/hq/growth/content', group: '增长', category: 'page' },
  { id: 'channels', label: '渠道中心', icon: '📡', path: '/hq/growth/channels', group: '增长', category: 'page' },
  { id: 'referral', label: '裂变中心', icon: '🔗', path: '/hq/growth/referral', group: '增长', category: 'page' },
  { id: 'group-buy', label: '团购管理', icon: '🛒', path: '/hq/growth/group-buy', group: '增长', category: 'page' },
  { id: 'stamp-card', label: '集章卡', icon: '🎴', path: '/hq/growth/stamp-card', group: '增长', category: 'page' },
  { id: 'xhs', label: '小红书运营', icon: '📕', path: '/hq/growth/xhs', group: '增长', category: 'page' },
  { id: 'retail-mall', label: '零售商城', icon: '🏪', path: '/hq/growth/retail-mall', group: '增长', category: 'page' },
  { id: 'execution', label: '门店执行', icon: '📋', path: '/hq/growth/execution', group: '增长', category: 'page' },
  { id: 'crm-campaign', label: '私域运营生成', icon: '📢', path: '/growth/crm-campaign', group: '增长', category: 'feature' },

  // --- 分析 ---
  { id: 'analytics-hq-dashboard', label: '集团驾驶舱', icon: '🚀', path: '/analytics/hq-dashboard', group: '分析', category: 'page' },
  { id: 'analytics-dashboard', label: '经营驾驶舱(分析)', icon: '🖥️', path: '/analytics/dashboard', group: '分析', category: 'page' },
  { id: 'daily', label: '日报', icon: '📰', path: '/analytics/daily', group: '分析', category: 'page' },
  { id: 'kpi', label: 'KPI 监控', icon: '🎯', path: '/analytics/kpi', group: '分析', category: 'page' },
  { id: 'cost', label: '成本分析', icon: '💰', path: '/analytics/cost', group: '分析', category: 'page' },
  { id: 'waste', label: '损耗分析', icon: '🗑️', path: '/analytics/waste', group: '分析', category: 'page' },
  { id: 'finance-analysis', label: '财务分析', icon: '💹', path: '/hq/analytics/finance', group: '分析', category: 'page' },
  { id: 'pl-report', label: '损益表P&L', icon: '💹', path: '/hq/analytics/pl-report', group: '分析', category: 'page' },
  { id: 'member-analysis', label: '会员分析', icon: '👥', path: '/hq/analytics/member', group: '分析', category: 'page' },
  { id: 'budget-tracker', label: '预算追踪', icon: '📊', path: '/hq/analytics/budget', group: '分析', category: 'page' },
  { id: 'dish-analytics', label: '菜品分析', icon: '🍽️', path: '/analytics/dishes', group: '分析', category: 'page' },
  { id: 'decisions', label: 'AI 决策', icon: '🧠', path: '/analytics/decisions', group: '分析', category: 'feature' },
  { id: 'scenarios', label: '场景识别', icon: '🔍', path: '/analytics/scenarios', group: '分析', category: 'feature' },

  // --- 财务 ---
  { id: 'pnl-report', label: 'P&L 报表', icon: '📈', path: '/finance/pnl-report', group: '财务', category: 'page' },
  { id: 'finance-audit', label: 'AI 财务稽核', icon: '🔍', path: '/finance/audit', group: '财务', category: 'feature' },

  // --- 组织 ---
  { id: 'hr-dashboard', label: '人力管理', icon: '👥', path: '/hq/org/hr', group: '组织', category: 'page' },
  { id: 'franchise', label: '加盟管理', icon: '🏪', path: '/franchise', group: '组织', category: 'page' },
  { id: 'franchise-contracts', label: '合同管理', icon: '📝', path: '/franchise/contracts', group: '组织', category: 'page' },
  { id: 'franchise-dashboard', label: '加盟驾驶舱', icon: '📊', path: '/franchise-dashboard', group: '组织', category: 'page' },
  { id: 'payroll-configs', label: '薪资方案配置', icon: '⚙️', path: '/org/payroll-configs', group: '组织', category: 'page' },
  { id: 'payroll-records', label: '月度薪资管理', icon: '💴', path: '/org/payroll-records', group: '组织', category: 'page' },
  { id: 'payroll-manage', label: '薪资总览', icon: '📋', path: '/payroll-manage', group: '组织', category: 'page' },
  { id: 'attendance', label: '考勤管理', icon: '🕐', path: '/org/attendance', group: '组织', category: 'page' },
  { id: 'performance', label: '绩效考核', icon: '🏆', path: '/org/performance', group: '组织', category: 'page' },

  // --- 经营 ---
  { id: 'ops-dashboard', label: '经营驾驶舱(运营)', icon: '📊', path: '/hq/ops/dashboard', group: '经营', category: 'page' },
  { id: 'store-analysis', label: '门店分析', icon: '🏪', path: '/hq/ops/store-analysis', group: '经营', category: 'page' },
  { id: 'dish-analysis', label: '菜品分析(运营)', icon: '🍜', path: '/hq/ops/dish-analysis', group: '经营', category: 'page' },
  { id: 'smart-specials', label: '今日特供', icon: '🍽️', path: '/hq/ops/smart-specials', group: '经营', category: 'page' },
  { id: 'patrol-inspection', label: 'AI巡店质检', icon: '🔍', path: '/ops/patrol-inspection', group: '经营', category: 'feature' },
  { id: 'reviews', label: '评价管理', icon: '⭐', path: '/ops/reviews', group: '经营', category: 'page' },
  { id: 'cruise-monitor', label: '营业巡航', icon: '🚢', path: '/hq/ops/cruise', group: '经营', category: 'page' },
  { id: 'peak-monitor', label: '高峰值守', icon: '🔥', path: '/hq/ops/peak-monitor', group: '经营', category: 'page' },
  { id: 'daily-review', label: '日清追踪', icon: '📅', path: '/hq/ops/daily-review', group: '经营', category: 'page' },
  { id: 'approvals', label: '审批中心', icon: '✅', path: '/ops/approval-center', group: '经营', category: 'page' },
  { id: 'operation-plans', label: '高风险待确认', icon: '⚡', path: '/hq/ops/operation-plans', group: '经营', category: 'page' },
  { id: 'alerts', label: '异常中心', icon: '🚨', path: '/hq/ops/alerts', group: '经营', category: 'page' },
  { id: 'review-center', label: '复盘中心', icon: '📋', path: '/hq/ops/review', group: '经营', category: 'page' },
  { id: 'regional', label: '区域追踪', icon: '🗺️', path: '/hq/ops/regional', group: '经营', category: 'page' },

  // --- 供应链 ---
  { id: 'supply-dashboard', label: '供应链看板', icon: '📊', path: '/supply/dashboard', group: '供应链', category: 'page' },
  { id: 'purchase-orders', label: '采购管理', icon: '🛒', path: '/supply/purchase-orders', group: '供应链', category: 'page' },
  { id: 'central-kitchen', label: '中央厨房', icon: '🏭', path: '/supply/central-kitchen', group: '供应链', category: 'page' },
  { id: 'expiry-alerts', label: '临期预警', icon: '⚠️', path: '/supply/expiry-alerts', group: '供应链', category: 'page' },
  { id: 'food-safety', label: '食安追溯', icon: '🛡️', path: '/supply/food-safety', group: '供应链', category: 'page' },
  { id: 'inventory-intel', label: '智能补货', icon: '📦', path: '/hq/supply/inventory-intel', group: '供应链', category: 'page' },
  { id: 'supply-chain', label: '收货与调拨', icon: '🚛', path: '/hq/supply/chain', group: '供应链', category: 'page' },

  // --- 门店 ---
  { id: 'store-manage', label: '门店管理', icon: '🏬', path: '/store/manage', group: '经营', category: 'page' },
  { id: 'store-clone', label: '快速开店', icon: '🏪', path: '/hq/ops/store-clone', group: '经营', category: 'page' },

  // --- 配置 ---
  { id: 'system-settings', label: '系统设置', icon: '🔧', path: '/system/settings', group: '配置', category: 'page' },
  { id: 'settings', label: '模板配置', icon: '⚙️', path: '/hq/ops/settings', group: '配置', category: 'page' },
  { id: 'receipt-editor', label: '小票模板', icon: '🧾', path: '/receipt-editor', group: '配置', category: 'page' },
  { id: 'event-bus-health', label: '事件总线监控', icon: '🔄', path: '/hq/ops/event-bus-health', group: '配置', category: 'page' },
];

// ---------- localStorage 最近访问 ----------

const RECENT_KEY = 'tx_global_search_recent';
const MAX_RECENT = 10;

function getRecentItems(): SearchItem[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const ids: string[] = JSON.parse(raw);
    return ids
      .map((id) => SEARCH_INDEX.find((item) => item.id === id))
      .filter((item): item is SearchItem => item != null)
      .map((item) => ({ ...item, category: 'recent' as const }));
  } catch {
    return [];
  }
}

function addRecentItem(id: string): void {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    let ids: string[] = raw ? JSON.parse(raw) : [];
    ids = [id, ...ids.filter((x) => x !== id)].slice(0, MAX_RECENT);
    localStorage.setItem(RECENT_KEY, JSON.stringify(ids));
  } catch {
    // ignore storage errors
  }
}

// ---------- 搜索逻辑 ----------

function searchItems(query: string): { pages: SearchItem[]; features: SearchItem[]; recent: SearchItem[] } {
  const q = query.toLowerCase().trim();

  if (!q) {
    return { pages: [], features: [], recent: getRecentItems() };
  }

  const matched = SEARCH_INDEX.filter((item) => {
    const fields = [item.label, item.path, item.group, ...(item.keywords ?? [])];
    return fields.some((f) => f.toLowerCase().includes(q));
  });

  return {
    pages: matched.filter((i) => i.category === 'page'),
    features: matched.filter((i) => i.category === 'feature'),
    recent: [],
  };
}

// ---------- 高亮匹配文字 ----------

function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) return text;
  return (
    <>
      {text.slice(0, idx)}
      <span style={{ color: 'var(--brand, #ff6b2c)', fontWeight: 600 }}>{text.slice(idx, idx + query.length)}</span>
      {text.slice(idx + query.length)}
    </>
  );
}

// ---------- 组件 ----------

interface GlobalSearchProps {
  visible: boolean;
  onClose: () => void;
}

export function GlobalSearch({ visible, onClose }: GlobalSearchProps) {
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [debouncedQuery, setDebouncedQuery] = useState('');

  // 防抖 300ms
  useEffect(() => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setDebouncedQuery(query);
      setActiveIndex(0);
    }, 300);
    return () => {
      if (debounceTimer.current) clearTimeout(debounceTimer.current);
    };
  }, [query]);

  // 搜索结果
  const results = useMemo(() => searchItems(debouncedQuery), [debouncedQuery]);

  // 扁平化结果列表（用于键盘导航）
  const flatList = useMemo(() => {
    const list: SearchItem[] = [];
    if (results.recent.length > 0) list.push(...results.recent);
    if (results.pages.length > 0) list.push(...results.pages);
    if (results.features.length > 0) list.push(...results.features);
    return list;
  }, [results]);

  // 自动聚焦
  useEffect(() => {
    if (visible) {
      setQuery('');
      setDebouncedQuery('');
      setActiveIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [visible]);

  // 全局快捷键 Ctrl+K / Cmd+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        if (visible) {
          onClose();
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [visible, onClose]);

  // 跳转
  const handleSelect = useCallback((item: SearchItem) => {
    addRecentItem(item.id);
    navigate(item.path);
    onClose();
  }, [navigate, onClose]);

  // 键盘导航
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((prev) => Math.min(prev + 1, flatList.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((prev) => Math.max(prev - 1, 0));
    } else if (e.key === 'Enter' && flatList[activeIndex]) {
      e.preventDefault();
      handleSelect(flatList[activeIndex]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      onClose();
    }
  }, [flatList, activeIndex, handleSelect, onClose]);

  // 滚动选中项到可视区
  useEffect(() => {
    const container = listRef.current;
    if (!container) return;
    const activeEl = container.querySelector(`[data-index="${activeIndex}"]`);
    if (activeEl) {
      (activeEl as HTMLElement).scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  if (!visible) return null;

  const renderGroup = (title: string, items: SearchItem[], startIndex: number) => {
    if (items.length === 0) return null;
    return (
      <div key={title}>
        <div style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase',
          color: 'var(--text-4, #666)', padding: '10px 16px 4px',
        }}>
          {title}
        </div>
        {items.map((item, i) => {
          const globalIdx = startIndex + i;
          const isActive = globalIdx === activeIndex;
          return (
            <div
              key={item.id + '-' + item.category}
              data-index={globalIdx}
              onClick={() => handleSelect(item)}
              onMouseEnter={() => setActiveIndex(globalIdx)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '8px 16px', cursor: 'pointer', borderRadius: 8, margin: '0 8px',
                background: isActive ? 'var(--bg-2, #1a2a33)' : 'transparent',
                transition: 'background 0.1s',
              }}
            >
              <span style={{ fontSize: 16, width: 24, textAlign: 'center' }}>{item.icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: 'var(--text-1, #fff)' }}>
                  {highlightMatch(item.label, debouncedQuery)}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-4, #666)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {item.group} &middot; {item.path}
                </div>
              </div>
              {isActive && (
                <kbd style={{
                  fontSize: 10, padding: '1px 6px', borderRadius: 4,
                  background: 'var(--bg-3, #2a3a43)', color: 'var(--text-3, #999)',
                  fontFamily: 'var(--font-mono)',
                }}>Enter</kbd>
              )}
            </div>
          );
        })}
      </div>
    );
  };

  let offset = 0;
  const recentOffset = 0;
  offset += results.recent.length;
  const pageOffset = offset;
  offset += results.pages.length;
  const featureOffset = offset;

  const hasResults = flatList.length > 0;

  return (
    <>
      {/* 遮罩层 */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)',
          zIndex: 9998, backdropFilter: 'blur(4px)',
        }}
      />

      {/* 搜索弹窗 */}
      <div style={{
        position: 'fixed', top: '15%', left: '50%', transform: 'translateX(-50%)',
        width: 560, maxHeight: '60vh', zIndex: 9999,
        background: 'var(--bg-1, #112228)',
        border: '1px solid var(--bg-2, #1a2a33)',
        borderRadius: 14,
        boxShadow: '0 24px 80px rgba(0,0,0,0.6)',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
      }}>
        {/* 搜索输入 */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 16px',
          borderBottom: '1px solid var(--bg-2, #1a2a33)',
        }}>
          <span style={{ fontSize: 16, color: 'var(--text-3, #999)' }}>&#x1F50D;</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="搜索页面、功能..."
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              fontSize: 14, color: 'var(--text-1, #fff)',
              fontFamily: 'inherit',
            }}
          />
          <kbd style={{
            padding: '2px 8px', borderRadius: 4, background: 'var(--bg-2, #1a2a33)',
            fontSize: 10, color: 'var(--text-4, #666)', fontFamily: 'var(--font-mono)',
          }}>ESC</kbd>
        </div>

        {/* 搜索结果 */}
        <div ref={listRef} style={{ flex: 1, overflow: 'auto', padding: '4px 0 8px' }}>
          {!hasResults && debouncedQuery && (
            <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--text-4, #666)', fontSize: 13 }}>
              未找到匹配的页面或功能
            </div>
          )}
          {!hasResults && !debouncedQuery && (
            <div style={{ padding: '16px', textAlign: 'center', color: 'var(--text-4, #666)', fontSize: 12 }}>
              输入关键词搜索页面和功能
            </div>
          )}
          {renderGroup('最近访问', results.recent, recentOffset)}
          {renderGroup('页面', results.pages, pageOffset)}
          {renderGroup('功能', results.features, featureOffset)}
        </div>

        {/* 底部提示 */}
        <div style={{
          padding: '8px 16px',
          borderTop: '1px solid var(--bg-2, #1a2a33)',
          display: 'flex', alignItems: 'center', gap: 16,
          fontSize: 11, color: 'var(--text-4, #666)',
        }}>
          <span><kbd style={{ padding: '1px 4px', borderRadius: 3, background: 'var(--bg-2)', fontFamily: 'var(--font-mono)', fontSize: 10 }}>&#8593;&#8595;</kbd> 导航</span>
          <span><kbd style={{ padding: '1px 4px', borderRadius: 3, background: 'var(--bg-2)', fontFamily: 'var(--font-mono)', fontSize: 10 }}>Enter</kbd> 打开</span>
          <span><kbd style={{ padding: '1px 4px', borderRadius: 3, background: 'var(--bg-2)', fontFamily: 'var(--font-mono)', fontSize: 10 }}>Esc</kbd> 关闭</span>
        </div>
      </div>
    </>
  );
}
