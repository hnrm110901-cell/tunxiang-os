/**
 * 菜单配置引擎 — 数据驱动侧边栏/搜索/面包屑
 *
 * 从 SidebarHQ.tsx 提取，可被多处引用：
 * - SidebarHQ 侧边栏渲染
 * - 全局搜索（Cmd+K）
 * - 面包屑导航
 * - 权限检查
 */

export interface MenuItem {
  id: string;
  label: string;
  icon: string;
  count?: number;
  path: string;
}

export interface MenuGroup {
  label: string;
  items: MenuItem[];
}

export interface MenuConfig {
  moduleId: string;
  groups: MenuGroup[];
}

// 动态菜单配置（未来从后端加载，当前为静态数据）
export const MENU_CONFIGS: Record<string, MenuConfig> = {
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
        { id: 'orders', label: '订单列表', icon: '📋', count: 12, path: '/hq/trade/orders' },
        { id: 'payments', label: '支付记录', icon: '💳', path: '/hq/trade/payments' },
        { id: 'settlements', label: '日结/班结', icon: '📑', path: '/hq/trade/settlements' },
        { id: 'refunds', label: '退款管理', icon: '↩️', path: '/hq/trade/refunds' },
      ]},
      { label: '外卖', items: [
        { id: 'delivery', label: '外卖聚合', icon: '🛵', count: 0, path: '/hq/trade/delivery' },
      ]},
      { label: '预定/宴席', items: [
        { id: 'reservations', label: '预定管理', icon: '📅', path: '/hq/reservations' },
        { id: 'banquets', label: '宴席管理', icon: '🥂', path: '/hq/trade/banquets' },
      ]},
    ],
  },
  menu: {
    moduleId: 'menu', groups: [
      { label: '菜品管理', items: [
        { id: 'dish-list', label: '菜品列表', icon: '🍜', path: '/hq/menu/dishes' },
        { id: 'categories', label: '分类管理', icon: '📂', path: '/hq/menu/categories' },
        { id: 'specs', label: '规格/做法', icon: '🔧', path: '/hq/menu/specs' },
        { id: 'packages', label: '套餐组合', icon: '📦', path: '/hq/menu/packages' },
        { id: 'pricing', label: '价格版本', icon: '💲', path: '/hq/menu/pricing' },
      ]},
      { label: '菜品分析', items: [
        { id: 'ranking', label: '菜品排名', icon: '🏆', path: '/hq/menu/ranking' },
        { id: 'bom', label: 'BOM 配方', icon: '📐', path: '/hq/menu/bom' },
      ]},
      { label: 'AI 决策', items: [
        { id: 'menu-optimize', label: 'AI排菜建议', icon: '🧠', path: '/hq/menu/optimize' },
        { id: 'dish-agent', label: '菜品智能体看板', icon: '🍳', path: '/hq/menu/dish-agent' },
        { id: 'kitchen-schedule', label: '厨房排班建议', icon: '👨‍🍳', path: '/hq/menu/kitchen-schedule' },
      ]},
      { label: '研发', items: [
        { id: 'new-dish', label: '新菜研发', icon: '🧪', path: '/hq/menu/rd' },
        { id: 'quality', label: '质量检测', icon: '✅', path: '/hq/menu/quality' },
      ]},
    ],
  },
  store: {
    moduleId: 'store', groups: [
      { label: '组织与主体', items: [
        { id: 'stores', label: '门店管理', icon: '🏪', path: '/hq/org/stores' },
        { id: 'brands', label: '品牌管理', icon: '🏷️', path: '/hq/org/brands' },
        { id: 'regions', label: '区域管理', icon: '🗺️', path: '/hq/org/regions' },
      ]},
      { label: '桌台与出品', items: [
        { id: 'floor-tables', label: '桌台配置', icon: '🪑', path: '/hq/floor/tables' },
        { id: 'kitchen-stations', label: '档口配置', icon: '👨‍🍳', path: '/hq/kitchen/stations' },
        { id: 'print-rules', label: '打印方案', icon: '🖨️', path: '/hq/print/rules' },
        { id: 'kds-dispatch', label: '出品路由', icon: '🔀', path: '/hq/kds/dispatch' },
      ]},
      { label: '营业规则', items: [
        { id: 'business-day', label: '营业日配置', icon: '📅', path: '/hq/business-day/config' },
        { id: 'shifts', label: '班次配置', icon: '🕐', path: '/hq/shifts/config' },
        { id: 'payment-channels', label: '支付渠道', icon: '💳', path: '/hq/payments/channels' },
        { id: 'billing-rules', label: '折扣/抹零规则', icon: '🧮', path: '/hq/billing/rules' },
        { id: 'invoice-rules', label: '发票规则', icon: '🧾', path: '/hq/invoice/rules' },
      ]},
      { label: '人员与权限', items: [
        { id: 'roles', label: '角色权限', icon: '🔐', path: '/hq/iam/roles' },
        { id: 'staff', label: '员工档案', icon: '👤', path: '/hq/iam/staff' },
      ]},
      { label: '事件与任务', items: [
        { id: 'tasks', label: '任务中心', icon: '📋', path: '/hq/tasks' },
        { id: 'events', label: '事件中心', icon: '🔔', path: '/hq/events' },
        { id: 'audit-logs', label: '审计日志', icon: '📜', path: '/hq/audit/logs' },
      ]},
    ],
  },
  member: {
    moduleId: 'member', groups: [
      { label: '会员管理', items: [
        { id: 'member-list', label: '会员档案', icon: '👥', path: '/hq/members' },
        { id: 'member-tags', label: '偏好标签', icon: '🏷️', path: '/hq/members/tags' },
        { id: 'consumption', label: '消费记录', icon: '📊', path: '/hq/members/consumption' },
      ]},
      { label: '企业客户', items: [
        { id: 'corporate', label: '协议单位', icon: '🏢', path: '/hq/corporate-accounts' },
      ]},
      { label: '轻营销', items: [
        { id: 'coupons', label: '券核销', icon: '🎫', path: '/hq/members/coupons' },
        { id: 'campaigns', label: '营销活动', icon: '📣', path: '/hq/members/campaigns' },
      ]},
    ],
  },
  analytics: {
    moduleId: 'analytics', groups: [
      { label: '驾驶舱', items: [
        { id: 'analytics-dashboard', label: '经营驾驶舱', icon: '🖥️', path: '/analytics/dashboard' },
      ]},
      { label: '分析', items: [
        { id: 'finance-analysis', label: '财务分析', icon: '💹', path: '/hq/analytics/finance' },
        { id: 'pl-report', label: '损益表P&L', icon: '💹', path: '/hq/analytics/pl-report' },
        { id: 'member-analysis', label: '会员分析', icon: '👥', path: '/hq/analytics/member' },
        { id: 'budget-tracker', label: '预算追踪', icon: '📊', path: '/hq/analytics/budget' },
      ]},
      { label: 'AI 经营', items: [
        { id: 'nlq', label: 'AI 自然语言问数', icon: '🔍', path: '/hq/analytics/nlq' },
        { id: 'revenue-optimize', label: '收益优化看板', icon: '💡', path: '/hq/analytics/revenue-optimize' },
        { id: 'table-turnover', label: '翻台率分析', icon: '🔄', path: '/hq/analytics/table-turnover' },
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
        { id: 'customer-brain', label: '客户大脑工作台', icon: '🧠', path: '/hq/growth/customer-brain' },
      ]},
      { label: '归因复盘', items: [
        { id: 'growth-roi', label: 'ROI总览', icon: '💰', path: '/hq/growth/roi' },
        { id: 'journey-attribution', label: '旅程归因', icon: '📊', path: '/hq/growth/journey-attribution' },
      ]},
      { label: '集团视图', items: [
        { id: 'brand-comparison', label: '品牌对比', icon: '🏢', path: '/hq/growth/brand-comparison' },
        { id: 'store-ranking', label: '门店排行', icon: '🏪', path: '/hq/growth/store-ranking' },
        { id: 'cross-brand', label: '跨品牌增长', icon: '🔗', path: '/hq/growth/cross-brand' },
      ]},
      { label: '营销工具', items: [
        { id: 'referral', label: '裂变中心', icon: '🔗', path: '/hq/growth/referral' },
        { id: 'group-buy', label: '团购管理', icon: '🛒', path: '/hq/growth/group-buy' },
        { id: 'stamp-card', label: '集章卡', icon: '🎴', path: '/hq/growth/stamp-card' },
        { id: 'member-cards', label: '储值卡与积分', icon: '💳', path: '/hq/growth/member-cards' },
      ]},
      { label: '配置', items: [
        { id: 'growth-settings', label: '配置治理', icon: '⚙️', path: '/hq/growth/settings' },
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
      { label: '发票管理', items: [
        { id: 'e-invoice', label: '电子发票', icon: '🧾', path: '/finance/invoices' },
      ]},
      { label: 'AI 稽核', items: [
        { id: 'finance-audit', label: 'AI 财务稽核', icon: '🔍', path: '/finance/audit' },
      ]},
    ],
  },
  org: {
    moduleId: 'org', groups: [
      { label: '组织管理', items: [
        { id: 'hr-dashboard', label: '人力中枢', icon: '👥', path: '/hq/org/hr' },
        { id: 'franchise', label: '加盟管理', icon: '🏪', path: '/hq/org/franchise' },
      ]},
      { label: '人事管理', items: [
        { id: 'payroll-configs', label: '薪资方案配置', icon: '⚙️', path: '/hq/org/payroll-configs' },
        { id: 'payroll-records', label: '月度薪资管理', icon: '💴', path: '/hq/org/payroll-records' },
        { id: 'payroll-manage', label: '薪资总览', icon: '📋', path: '/hq/org/payroll-manage' },
        { id: 'attendance', label: '考勤管理', icon: '🕐', path: '/hq/org/attendance' },
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
      ]},
      { label: '供应链', items: [
        { id: 'inventory-intel', label: '智能补货', icon: '📦', path: '/hq/supply/inventory-intel' },
        { id: 'supply-chain', label: '收货与调拨', icon: '🚛', path: '/hq/supply/chain' },
        { id: 'procurement-ai', label: 'AI 采购建议', icon: '🤖', path: '/hq/supply/procurement-ai' },
        { id: 'wastage', label: '损耗分析', icon: '♻️', path: '/hq/supply/wastage' },
        { id: 'demand-forecast', label: '需求预测', icon: '📈', path: '/hq/supply/demand-forecast' },
      ]},
      { label: '配置', items: [
        { id: 'settings', label: '模板配置', icon: '⚙️', path: '/hq/ops/settings' },
        { id: 'receipt-editor', label: '小票模板', icon: '🧾', path: '/receipt-editor' },
        { id: 'event-bus-health', label: '事件总线监控', icon: '🔄', path: '/hq/ops/event-bus-health' },
        { id: 'store-clone', label: '快速开店', icon: '🏪', path: '/hq/ops/store-clone' },
      ]},
    ],
  },
  agent: {
    moduleId: 'agent', groups: [
      { label: 'AI 中枢', items: [
        { id: 'agent-hub', label: 'AI 中枢首页', icon: '🤖', path: '/hq/agent/hub' },
        { id: 'agent-command', label: '运营大盘', icon: '🎯', path: '/hq/agent/command' },
        { id: 'agent-log', label: '行动日志', icon: '📋', path: '/hq/agent/log' },
        { id: 'agent-market', label: 'Agent 市场', icon: '🏪', path: '/hq/agent/market' },
        { id: 'agent-settings', label: '权限与授权', icon: '⚙️', path: '/hq/agent/settings' },
      ]},
      { label: '分析工具', items: [
        { id: 'daily-brief', label: 'AI 经营简报', icon: '📰', path: '/hq/analytics/daily-brief' },
        { id: 'anomaly', label: '经营异常检测', icon: '🚨', path: '/hq/analytics/anomaly' },
      ]},
    ],
  },
};

/**
 * 获取所有菜单项的扁平列表（用于全局搜索）
 */
export function getAllMenuItems(): MenuItem[] {
  return Object.values(MENU_CONFIGS).flatMap(config =>
    config.groups.flatMap(group => group.items)
  );
}
