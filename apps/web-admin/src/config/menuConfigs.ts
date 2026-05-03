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
  labelKey: string;
  icon: string;
  count?: number;
  path: string;
}

export interface MenuGroup {
  label: string;
  labelKey: string;
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
      { label: '总览', labelKey: 'dashboard.overview', items: [
        { id: 'hq-dashboard', label: '经营驾驶舱', labelKey: 'dashboard.hqDashboard', icon: '📊', path: '/dashboard' },
        { id: 'store-health', label: '门店健康', labelKey: 'dashboard.storeHealth', icon: '🏥', path: '/store-health' },
        { id: 'agent-monitor', label: 'Agent 监控', labelKey: 'dashboard.agentMonitor', icon: '🤖', path: '/agents' },
        { id: 'daily-plan', label: '每日计划', labelKey: 'dashboard.dailyPlan', icon: '📋', path: '/daily-plan' },
      ]},
    ],
  },
  trade: {
    moduleId: 'trade', groups: [
      { label: '交易管理', labelKey: 'trade.management', items: [
        { id: 'orders', label: '订单列表', labelKey: 'trade.orderList', icon: '📋', count: 12, path: '/hq/trade/orders' },
        { id: 'payments', label: '支付记录', labelKey: 'trade.payments', icon: '💳', path: '/hq/trade/payments' },
        { id: 'settlements', label: '日结/班结', labelKey: 'trade.settlements', icon: '📑', path: '/hq/trade/settlements' },
        { id: 'refunds', label: '退款管理', labelKey: 'trade.refunds', icon: '↩️', path: '/hq/trade/refunds' },
      ]},
      { label: '外卖', labelKey: 'trade.delivery', items: [
        { id: 'delivery', label: '外卖聚合', labelKey: 'trade.delivery', icon: '🛵', count: 0, path: '/hq/trade/delivery' },
      ]},
      { label: '预定/宴席', labelKey: 'trade.reservation', items: [
        { id: 'reservations', label: '预定管理', labelKey: 'trade.reservationManage', icon: '📅', path: '/hq/reservations' },
        { id: 'banquets', label: '宴席管理', labelKey: 'trade.banquetManage', icon: '🥂', path: '/hq/trade/banquets' },
      ]},
    ],
  },
  menu: {
    moduleId: 'menu', groups: [
      { label: '菜品管理', labelKey: 'menu.management', items: [
        { id: 'dish-list', label: '菜品列表', labelKey: 'menu.dishList', icon: '🍜', path: '/hq/menu/dishes' },
        { id: 'categories', label: '分类管理', labelKey: 'menu.categories', icon: '📂', path: '/hq/menu/categories' },
        { id: 'specs', label: '规格/做法', labelKey: 'menu.specs', icon: '🔧', path: '/hq/menu/specs' },
        { id: 'packages', label: '套餐组合', labelKey: 'menu.packages', icon: '📦', path: '/hq/menu/packages' },
        { id: 'pricing', label: '价格版本', labelKey: 'menu.pricing', icon: '💲', path: '/hq/menu/pricing' },
      ]},
      { label: '菜品分析', labelKey: 'menu.analysis', items: [
        { id: 'ranking', label: '菜品排名', labelKey: 'menu.ranking', icon: '🏆', path: '/hq/menu/ranking' },
        { id: 'bom', label: 'BOM 配方', labelKey: 'menu.bom', icon: '📐', path: '/hq/menu/bom' },
      ]},
      { label: 'AI 决策', labelKey: 'menu.aiDecision', items: [
        { id: 'menu-optimize', label: 'AI排菜建议', labelKey: 'menu.menuOptimize', icon: '🧠', path: '/hq/menu/optimize' },
        { id: 'dish-agent', label: '菜品智能体看板', labelKey: 'menu.dishAgent', icon: '🍳', path: '/hq/menu/dish-agent' },
        { id: 'kitchen-schedule', label: '厨房排班建议', labelKey: 'menu.kitchenSchedule', icon: '👨‍🍳', path: '/hq/menu/kitchen-schedule' },
      ]},
      { label: '研发', labelKey: 'menu.rd', items: [
        { id: 'new-dish', label: '新菜研发', labelKey: 'menu.newDish', icon: '🧪', path: '/hq/menu/rd' },
        { id: 'quality', label: '质量检测', labelKey: 'menu.quality', icon: '✅', path: '/hq/menu/quality' },
      ]},
    ],
  },
  store: {
    moduleId: 'store', groups: [
      { label: '组织与主体', labelKey: 'store.orgAndEntity', items: [
        { id: 'stores', label: '门店管理', labelKey: 'store.storeManage', icon: '🏪', path: '/hq/org/stores' },
        { id: 'brands', label: '品牌管理', labelKey: 'store.brandManage', icon: '🏷️', path: '/hq/org/brands' },
        { id: 'regions', label: '区域管理', labelKey: 'store.regionManage', icon: '🗺️', path: '/hq/org/regions' },
      ]},
      { label: '桌台与出品', labelKey: 'store.tableAndProduction', items: [
        { id: 'floor-tables', label: '桌台配置', labelKey: 'store.floorTables', icon: '🪑', path: '/hq/floor/tables' },
        { id: 'kitchen-stations', label: '档口配置', labelKey: 'store.kitchenStations', icon: '👨‍🍳', path: '/hq/kitchen/stations' },
        { id: 'print-rules', label: '打印方案', labelKey: 'store.printRules', icon: '🖨️', path: '/hq/print/rules' },
        { id: 'kds-dispatch', label: '出品路由', labelKey: 'store.kdsDispatch', icon: '🔀', path: '/hq/kds/dispatch' },
      ]},
      { label: '营业规则', labelKey: 'store.businessRules', items: [
        { id: 'business-day', label: '营业日配置', labelKey: 'store.businessDay', icon: '📅', path: '/hq/business-day/config' },
        { id: 'shifts', label: '班次配置', labelKey: 'store.shifts', icon: '🕐', path: '/hq/shifts/config' },
        { id: 'payment-channels', label: '支付渠道', labelKey: 'store.paymentChannels', icon: '💳', path: '/hq/payments/channels' },
        { id: 'billing-rules', label: '折扣/抹零规则', labelKey: 'store.billingRules', icon: '🧮', path: '/hq/billing/rules' },
        { id: 'invoice-rules', label: '发票规则', labelKey: 'store.invoiceRules', icon: '🧾', path: '/hq/invoice/rules' },
      ]},
      { label: '人员与权限', labelKey: 'store.staffAndRoles', items: [
        { id: 'roles', label: '角色权限', labelKey: 'store.roles', icon: '🔐', path: '/hq/iam/roles' },
        { id: 'staff', label: '员工档案', labelKey: 'store.staff', icon: '👤', path: '/hq/iam/staff' },
      ]},
      { label: '事件与任务', labelKey: 'store.eventsAndTasks', items: [
        { id: 'tasks', label: '任务中心', labelKey: 'store.taskCenter', icon: '📋', path: '/hq/tasks' },
        { id: 'events', label: '事件中心', labelKey: 'store.eventCenter', icon: '🔔', path: '/hq/events' },
        { id: 'audit-logs', label: '审计日志', labelKey: 'store.auditLogs', icon: '📜', path: '/hq/audit/logs' },
      ]},
    ],
  },
  member: {
    moduleId: 'member', groups: [
      { label: '会员管理', labelKey: 'member.management', items: [
        { id: 'member-list', label: '会员档案', labelKey: 'member.memberList', icon: '👥', path: '/hq/members' },
        { id: 'member-tags', label: '偏好标签', labelKey: 'member.memberTags', icon: '🏷️', path: '/hq/members/tags' },
        { id: 'consumption', label: '消费记录', labelKey: 'member.consumption', icon: '📊', path: '/hq/members/consumption' },
      ]},
      { label: '企业客户', labelKey: 'member.corporate', items: [
        { id: 'corporate', label: '协议单位', labelKey: 'member.corporate', icon: '🏢', path: '/hq/corporate-accounts' },
      ]},
      { label: '轻营销', labelKey: 'member.campaigns', items: [
        { id: 'coupons', label: '券核销', labelKey: 'member.coupon', icon: '🎫', path: '/hq/members/coupons' },
        { id: 'campaigns', label: '营销活动', labelKey: 'member.campaigns', icon: '📣', path: '/hq/members/campaigns' },
      ]},
    ],
  },
  analytics: {
    moduleId: 'analytics', groups: [
      { label: '驾驶舱', labelKey: 'analytics.cockpit', items: [
        { id: 'analytics-dashboard', label: '经营驾驶舱', labelKey: 'analytics.dashboard', icon: '🖥️', path: '/analytics/dashboard' },
      ]},
      { label: 'HQ总部看板', labelKey: 'analytics.hqBoard', items: [
        { id: 'hq-brand-overview', label: '多品牌总览', labelKey: 'analytics.brandOverview', icon: '🏢', path: '/analytics/hq/overview' },
        { id: 'hq-store-matrix', label: '门店绩效矩阵', labelKey: 'analytics.storeMatrix', icon: '📊', path: '/analytics/hq/stores' },
      ]},
      { label: '分析', labelKey: 'analytics.analysis', items: [
        { id: 'region-overview', label: '区域经营总览', labelKey: 'analytics.regionOverview', icon: '🗺️', path: '/hq/analytics/region-overview' },
        { id: 'finance-analysis', label: '财务分析', labelKey: 'analytics.financeAnalysis', icon: '💹', path: '/hq/analytics/finance' },
        { id: 'pl-report', label: '损益表P&L', labelKey: 'analytics.plReport', icon: '💹', path: '/hq/analytics/pl-report' },
        { id: 'member-analysis', label: '会员分析', labelKey: 'analytics.memberAnalysis', icon: '👥', path: '/hq/analytics/member' },
        { id: 'budget-tracker', label: '预算追踪', labelKey: 'analytics.budgetTracker', icon: '📊', path: '/hq/analytics/budget' },
      ]},
      { label: 'AI 经营', labelKey: 'analytics.aiOperations', items: [
        { id: 'nlq', label: 'AI 自然语言问数', labelKey: 'analytics.nlq', icon: '🔍', path: '/hq/analytics/nlq' },
        { id: 'revenue-optimize', label: '收益优化看板', labelKey: 'analytics.revenueOptimize', icon: '💡', path: '/hq/analytics/revenue-optimize' },
        { id: 'table-turnover', label: '翻台率分析', labelKey: 'analytics.tableTurnover', icon: '🔄', path: '/hq/analytics/table-turnover' },
      ]},
      { label: '经营洞察', labelKey: 'analytics.insights', items: [
        { id: 'store-insights', label: '门店经营洞察', labelKey: 'analytics.storeInsights', icon: '🏪', path: '/hq/insights/stores' },
        { id: 'period-analysis', label: '餐段分析', labelKey: 'analytics.periodAnalysis', icon: '🕐', path: '/hq/insights/periods' },
      ]},
    ],
  },
  growth: {
    moduleId: 'growth', groups: [
      { label: '增长中枢', labelKey: 'growth.center', items: [
        { id: 'growth-dashboard', label: '增长驾驶舱', labelKey: 'growth.dashboard', icon: '🚀', path: '/hq/growth/dashboard' },
      ]},
      { label: '会员中枢', labelKey: 'growth.memberCenter', items: [
        { id: 'member-dashboard', label: '会员驾驶舱', labelKey: 'growth.memberDashboard', icon: '📊', path: '/hq/growth/member-dashboard' },
        { id: 'member-segments', label: 'RFM分层', labelKey: 'growth.memberSegments', icon: '🎯', path: '/hq/growth/member-segments' },
        { id: 'coupon-benefits', label: '券权益中心', labelKey: 'growth.couponBenefits', icon: '🎟️', path: '/hq/growth/coupon-benefits' },
        { id: 'journey-designer', label: '旅程编排', labelKey: 'growth.journeyDesigner', icon: '🗺️', path: '/hq/growth/journey-designer' },
      ]},
      { label: '客户资产', labelKey: 'growth.customerAssets', items: [
        { id: 'customer-pool', label: '客户总池', labelKey: 'growth.customerPool', icon: '👥', path: '/hq/growth/customers' },
      ]},
      { label: '人群标签', labelKey: 'growth.segments', items: [
        { id: 'segments', label: '规则分群', labelKey: 'growth.segments', icon: '🎯', path: '/hq/growth/segments' },
        { id: 'segment-tags', label: '增长标签', labelKey: 'growth.segmentTags', icon: '🏷️', path: '/hq/growth/segment-tags' },
      ]},
      { label: '旅程编排', labelKey: 'growth.journeyTemplates', items: [
        { id: 'journey-templates', label: '旅程模板', labelKey: 'growth.journeyTemplates', icon: '📋', path: '/hq/growth/journey-templates' },
        { id: 'journey-runs', label: '运行中心', labelKey: 'growth.journeyRuns', icon: '▶️', path: '/hq/growth/journey-runs' },
        { id: 'journey-monitor', label: '旅程执行监控', labelKey: 'growth.journeyMonitor', icon: '🗺️', path: '/hq/growth/journey-monitor' },
      ]},
      { label: '触达与权益', labelKey: 'growth.offers', items: [
        { id: 'offer-packs', label: '权益策略台', labelKey: 'growth.offerPacks', icon: '🎁', path: '/hq/growth/offer-packs' },
        { id: 'offers', label: '优惠中心', labelKey: 'growth.offers', icon: '🎫', path: '/hq/growth/offers' },
        { id: 'channels', label: '渠道触达', labelKey: 'growth.channels', icon: '📡', path: '/hq/growth/channels' },
        { id: 'content', label: '内容中心', labelKey: 'growth.content', icon: '📝', path: '/hq/growth/content' },
      ]},
      { label: '私域复购Agent', labelKey: 'growth.agentWorkbench', items: [
        { id: 'agent-workbench', label: 'Agent工作台', labelKey: 'growth.agentWorkbench', icon: '🤖', path: '/hq/growth/agent-workbench' },
        { id: 'customer-brain', label: '客户大脑工作台', labelKey: 'growth.customerBrain', icon: '🧠', path: '/hq/growth/customer-brain' },
      ]},
      { label: '归因复盘', labelKey: 'growth.attribution', items: [
        { id: 'growth-roi', label: 'ROI总览', labelKey: 'growth.roi', icon: '💰', path: '/hq/growth/roi' },
        { id: 'journey-attribution', label: '旅程归因', labelKey: 'growth.journeyAttribution', icon: '📊', path: '/hq/growth/journey-attribution' },
      ]},
      { label: '集团视图', labelKey: 'growth.brandComparison', items: [
        { id: 'brand-comparison', label: '品牌对比', labelKey: 'growth.brandComparison', icon: '🏢', path: '/hq/growth/brand-comparison' },
        { id: 'store-ranking', label: '门店排行', labelKey: 'growth.storeRanking', icon: '🏪', path: '/hq/growth/store-ranking' },
        { id: 'cross-brand', label: '跨品牌增长', labelKey: 'growth.crossBrand', icon: '🔗', path: '/hq/growth/cross-brand' },
      ]},
      { label: '营销工具', labelKey: 'growth.marketingTools', items: [
        { id: 'referral', label: '裂变中心', labelKey: 'growth.referral', icon: '🔗', path: '/hq/growth/referral' },
        { id: 'group-buy', label: '团购管理', labelKey: 'growth.groupBuy', icon: '🛒', path: '/hq/growth/group-buy' },
        { id: 'stamp-card', label: '集章卡', labelKey: 'growth.stampCard', icon: '🎴', path: '/hq/growth/stamp-card' },
        { id: 'member-cards', label: '储值卡与积分', labelKey: 'growth.memberCards', icon: '💳', path: '/hq/growth/member-cards' },
      ]},
      { label: '配置', labelKey: 'growth.settings', items: [
        { id: 'growth-settings', label: '配置治理', labelKey: 'growth.settings', icon: '⚙️', path: '/hq/growth/settings' },
      ]},
    ],
  },
  finance: {
    moduleId: 'finance', groups: [
      { label: '财务分析', labelKey: 'finance.analysis', items: [
        { id: 'finance-analysis', label: '财务分析', labelKey: 'finance.financeAnalysis', icon: '💹', path: '/hq/analytics/finance' },
        { id: 'pl-report', label: '损益表 P&L', labelKey: 'finance.plReport', icon: '📊', path: '/hq/analytics/pl-report' },
        { id: 'budget-tracker', label: '预算追踪', labelKey: 'finance.budgetTracker', icon: '🎯', path: '/hq/analytics/budget' },
      ]},
      { label: '发票管理', labelKey: 'finance.invoice', items: [
        { id: 'e-invoice', label: '电子发票', labelKey: 'finance.einvoice', icon: '🧾', path: '/finance/invoices' },
      ]},
      { label: 'AI 稽核', labelKey: 'finance.audit', items: [
        { id: 'finance-audit', label: 'AI 财务稽核', labelKey: 'finance.audit', icon: '🔍', path: '/finance/audit' },
      ]},
    ],
  },
  org: {
    moduleId: 'org', groups: [
      { label: '组织管理', labelKey: 'org.manage', items: [
        { id: 'hr-dashboard', label: '人力中枢', labelKey: 'org.hrDashboard', icon: '👥', path: '/hq/org/hr' },
        { id: 'franchise', label: '加盟管理', labelKey: 'org.franchise', icon: '🏪', path: '/hq/org/franchise' },
      ]},
      { label: '人事管理', labelKey: 'org.hr', items: [
        { id: 'payroll-configs', label: '薪资方案配置', labelKey: 'org.payrollConfigs', icon: '⚙️', path: '/hq/org/payroll-configs' },
        { id: 'payroll-records', label: '月度薪资管理', labelKey: 'org.payrollRecords', icon: '💴', path: '/hq/org/payroll-records' },
        { id: 'payroll-manage', label: '薪资总览', labelKey: 'org.payrollManage', icon: '📋', path: '/hq/org/payroll-manage' },
        { id: 'attendance', label: '考勤管理', labelKey: 'org.attendance', icon: '🕐', path: '/hq/org/attendance' },
      ]},
    ],
  },
  ops: {
    moduleId: 'ops', groups: [
      { label: '经营管理', labelKey: 'ops.management', items: [
        { id: 'ops-dashboard', label: '经营驾驶舱', labelKey: 'ops.dashboard', icon: '📊', path: '/hq/ops/dashboard' },
        { id: 'store-analysis', label: '门店分析', labelKey: 'ops.storeAnalysis', icon: '🏪', path: '/hq/ops/store-analysis' },
        { id: 'dish-analysis', label: '菜品分析', labelKey: 'ops.dishAnalysis', icon: '🍜', path: '/hq/ops/dish-analysis' },
        { id: 'smart-specials', label: '今日特供', labelKey: 'ops.smartSpecials', icon: '🍽️', path: '/hq/ops/smart-specials' },
      ]},
      { label: '巡检质控', labelKey: 'ops.patrolAndQuality', items: [
        { id: 'patrol-inspection', label: 'AI巡店质检', labelKey: 'ops.patrolInspection', icon: '🔍', path: '/ops/patrol-inspection' },
      ]},
      { label: '实时监控', labelKey: 'ops.realtimeMonitor', items: [
        { id: 'cruise-monitor', label: '营业巡航', labelKey: 'ops.cruiseMonitor', icon: '🚢', path: '/hq/ops/cruise' },
        { id: 'peak-monitor', label: '高峰值守', labelKey: 'ops.peakMonitor', icon: '🔥', path: '/hq/ops/peak-monitor' },
        { id: 'daily-review', label: '日清追踪', labelKey: 'ops.dailyReview', icon: '📅', path: '/hq/ops/daily-review' },
      ]},
      { label: '管控', labelKey: 'ops.control', items: [
        { id: 'approvals', label: '审批中心', labelKey: 'ops.approvals', icon: '✅', count: 4, path: '/hq/ops/approvals' },
        { id: 'operation-plans', label: '高风险待确认', labelKey: 'ops.operationPlans', icon: '⚡', path: '/hq/ops/operation-plans' },
        { id: 'alerts', label: '预警中心', labelKey: 'ops.alerts', icon: '🚨', count: 5, path: '/hq/ops/alerts' },
        { id: 'rectification', label: '整改指挥', labelKey: 'ops.rectification', icon: '🎯', count: 0, path: '/hq/ops/rectification' },
        { id: 'store-health-radar', label: '健康度雷达', labelKey: 'ops.storeHealthRadar', icon: '📡', path: '/hq/store-health' },
        { id: 'review', label: '复盘中心', labelKey: 'ops.review', icon: '📋', path: '/hq/ops/review' },
        { id: 'regional', label: '区域追踪', labelKey: 'ops.regional', icon: '🗺️', count: 3, path: '/hq/ops/regional' },
        { id: 'briefings', label: '经营简报', labelKey: 'ops.briefings', icon: '📰', path: '/hq/ops/briefings' },
        { id: 'alert-rules', label: '预警规则', labelKey: 'ops.alertRules', icon: '⚙️', path: '/hq/ops/alert-rules' },
        { id: 'integrations', label: '集成健康', labelKey: 'ops.integrations', icon: '🔌', path: '/hq/ops/integrations' },
      ]},
      { label: '供应链', labelKey: 'ops.supply', items: [
        { id: 'inventory-intel', label: '智能补货', labelKey: 'ops.inventoryIntel', icon: '📦', path: '/hq/supply/inventory-intel' },
        { id: 'supply-chain', label: '收货与调拨', labelKey: 'ops.supplyChain', icon: '🚛', path: '/hq/supply/chain' },
        { id: 'procurement-ai', label: 'AI 采购建议', labelKey: 'ops.procurementAi', icon: '🤖', path: '/hq/supply/procurement-ai' },
        { id: 'wastage', label: '损耗分析', labelKey: 'ops.wastage', icon: '♻️', path: '/hq/supply/wastage' },
        { id: 'demand-forecast', label: '需求预测', labelKey: 'ops.demandForecast', icon: '📈', path: '/hq/supply/demand-forecast' },
      ]},
      { label: '配置', labelKey: 'ops.templates', items: [
        { id: 'settings', label: '模板配置', labelKey: 'ops.templates', icon: '⚙️', path: '/hq/ops/settings' },
        { id: 'receipt-editor', label: '小票模板', labelKey: 'ops.receiptEditor', icon: '🧾', path: '/receipt-editor' },
        { id: 'event-bus-health', label: '事件总线监控', labelKey: 'ops.eventBusHealth', icon: '🔄', path: '/hq/ops/event-bus-health' },
        { id: 'store-clone', label: '快速开店', labelKey: 'ops.storeClone', icon: '🏪', path: '/hq/ops/store-clone' },
      ]},
    ],
  },
  agent: {
    moduleId: 'agent', groups: [
      { label: 'AI 中枢', labelKey: 'agent.aiCenter', items: [
        { id: 'agent-hub', label: 'AI 中枢首页', labelKey: 'agent.hub', icon: '🤖', path: '/hq/agent/hub' },
        { id: 'agent-command', label: '运营大盘', labelKey: 'agent.command', icon: '🎯', path: '/hq/agent/command' },
        { id: 'agent-log', label: '行动日志', labelKey: 'agent.log', icon: '📋', path: '/hq/agent/log' },
        { id: 'agent-market', label: 'Agent 市场', labelKey: 'agent.market', icon: '🏪', path: '/hq/agent/market' },
        { id: 'agent-settings', label: '权限与授权', labelKey: 'agent.settings', icon: '⚙️', path: '/hq/agent/settings' },
      ]},
      { label: '分析工具', labelKey: 'agent.tools', items: [
        { id: 'daily-brief', label: 'AI 经营简报', labelKey: 'agent.dailyBrief', icon: '📰', path: '/hq/analytics/daily-brief' },
        { id: 'anomaly', label: '经营异常检测', labelKey: 'agent.anomalyDetection', icon: '🚨', path: '/hq/analytics/anomaly' },
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
