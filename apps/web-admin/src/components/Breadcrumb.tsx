/**
 * Breadcrumb -- 基于当前路由自动生成面包屑导航
 * 首页 > 一级菜单 > 二级菜单 > 当前页
 */
import { useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

// ---------- 路由 -> 面包屑映射 ----------

interface BreadcrumbNode {
  label: string;
  path?: string; // 可点击跳转的路径，undefined 表示不可点击
}

/** 路径 -> 显示名映射表（从侧边栏菜单结构推导） */
const PATH_LABELS: Record<string, string> = {
  // 一级
  '/dashboard': '经营驾驶舱',
  '/store-health': '门店健康',
  '/agents': 'Agent 监控',
  '/daily-plan': '每日计划',

  // 交易
  '/trade': '交易管理',
  '/trade/orders': '订单列表',
  '/trade/payments': '支付记录',
  '/trade/settlements': '日结/班结',
  '/trade/refunds': '退款管理',
  '/hq/trade': '交易管理',
  '/hq/trade/delivery': '外卖聚合',
  '/delivery': '外卖',
  '/delivery/hub': '外卖管理中心',

  // 菜品
  '/menu': '菜品管理',
  '/menu/dishes': '菜品列表',
  '/menu/categories': '分类管理',
  '/menu/bom': 'BOM 配方',
  '/menu/ranking': '菜单排名',
  '/menu/pricing': '定价仿真',
  '/menu/specs': '规格管理',
  '/menu/sort': '排序管理',
  '/menu/batch': '批量操作',
  '/menu/optimize': 'AI排菜建议',
  '/menu/rd': '新菜研发',
  '/menu/quality': '质量检测',

  // 会员
  '/crm': 'CDP 会员列表',
  '/member': '会员管理',
  '/member/tiers': '等级体系',
  '/member/insight': 'AI 会员洞察',
  '/member/customer-service': '客服工单管理',

  // 增长
  '/growth': '增长营销',
  '/growth/campaigns': '活动管理',
  '/growth/crm-campaign': '私域运营生成',
  '/hq/growth': '增长营销',
  '/hq/growth/dashboard': '增长驾驶舱',
  '/hq/growth/roi': 'ROI总览',
  '/hq/growth/segments': '人群分层',
  '/hq/growth/journeys': '旅程管理',
  '/hq/growth/journey-monitor': '旅程执行监控',
  '/hq/growth/member-cards': '储值卡与积分',
  '/hq/growth/offers': '优惠中心',
  '/hq/growth/content': '内容中心',
  '/hq/growth/channels': '渠道中心',
  '/hq/growth/referral': '裂变中心',
  '/hq/growth/group-buy': '团购管理',
  '/hq/growth/stamp-card': '集章卡',
  '/hq/growth/xhs': '小红书运营',
  '/hq/growth/retail-mall': '零售商城',
  '/hq/growth/execution': '门店执行',

  // 分析
  '/analytics': '经营分析',
  '/analytics/hq-dashboard': '集团驾驶舱',
  '/analytics/dashboard': '经营驾驶舱',
  '/analytics/daily': '日报',
  '/analytics/kpi': 'KPI 监控',
  '/analytics/cost': '成本分析',
  '/analytics/waste': '损耗分析',
  '/analytics/dishes': '菜品分析',
  '/analytics/decisions': 'AI 决策',
  '/analytics/scenarios': '场景识别',
  '/hq/analytics': '经营分析',
  '/hq/analytics/finance': '财务分析',
  '/hq/analytics/pl-report': '损益表P&L',
  '/hq/analytics/member': '会员分析',
  '/hq/analytics/budget': '预算追踪',

  // 财务
  '/finance': '财务管理',
  '/finance/pnl-report': 'P&L 报表',
  '/finance/audit': 'AI 财务稽核',

  // 组织
  '/hq/org': '组织管理',
  '/hq/org/hr': '人力管理',
  '/franchise': '加盟管理',
  '/franchise/contracts': '合同管理',
  '/franchise-dashboard': '加盟驾驶舱',
  '/org': '组织人事',
  '/org/payroll-configs': '薪资方案配置',
  '/org/payroll-records': '月度薪资管理',
  '/org/attendance': '考勤管理',
  '/org/performance': '绩效考核',
  '/payroll-manage': '薪资总览',

  // 经营
  '/hq/ops': '运营管理',
  '/hq/ops/dashboard': '经营驾驶舱',
  '/hq/ops/store-analysis': '门店分析',
  '/hq/ops/dish-analysis': '菜品分析',
  '/hq/ops/smart-specials': '今日特供',
  '/hq/ops/cruise': '营业巡航',
  '/hq/ops/peak-monitor': '高峰值守',
  '/hq/ops/daily-review': '日清追踪',
  '/hq/ops/operation-plans': '高风险待确认',
  '/hq/ops/alerts': '异常中心',
  '/hq/ops/review': '复盘中心',
  '/hq/ops/regional': '区域追踪',
  '/hq/ops/store-clone': '快速开店',
  '/hq/ops/settings': '模板配置',
  '/hq/ops/event-bus-health': '事件总线监控',
  '/ops': '运营管理',
  '/ops/patrol-inspection': 'AI巡店质检',
  '/ops/reviews': '评价管理',
  '/ops/approval-center': '审批中心',

  // 供应链
  '/supply': '供应链',
  '/supply/dashboard': '供应链看板',
  '/supply/purchase-orders': '采购管理',
  '/supply/central-kitchen': '中央厨房',
  '/supply/expiry-alerts': '临期预警',
  '/supply/food-safety': '食安追溯',
  '/hq/supply': '供应链',
  '/hq/supply/inventory-intel': '智能补货',
  '/hq/supply/chain': '收货与调拨',

  // 门店
  '/store': '门店',
  '/store/manage': '门店管理',

  // 配置
  '/system': '系统',
  '/system/settings': '系统设置',
  '/receipt-editor': '小票模板',

  // 顶级分组
  '/hq': '总部',
};

/**
 * 根据当前路径生成面包屑链
 * 例如 /hq/growth/segments -> [首页, 增长营销, 人群分层]
 */
function buildBreadcrumbs(pathname: string): BreadcrumbNode[] {
  const crumbs: BreadcrumbNode[] = [{ label: '首页', path: '/dashboard' }];

  if (pathname === '/' || pathname === '/dashboard') {
    return crumbs;
  }

  // 先尝试精确匹配完整路径
  const fullLabel = PATH_LABELS[pathname];

  // 构建中间层级
  const segments = pathname.split('/').filter(Boolean);
  let accumulated = '';

  for (let i = 0; i < segments.length; i++) {
    accumulated += '/' + segments[i];
    const label = PATH_LABELS[accumulated];

    if (i === segments.length - 1) {
      // 最后一段：当前页面
      crumbs.push({ label: fullLabel ?? label ?? segments[i] });
    } else if (label) {
      // 中间层级有映射
      crumbs.push({ label, path: accumulated });
    }
  }

  // 去重：如果相邻两个 label 相同则保留后者
  const deduped: BreadcrumbNode[] = [crumbs[0]];
  for (let i = 1; i < crumbs.length; i++) {
    if (crumbs[i].label !== crumbs[i - 1].label) {
      deduped.push(crumbs[i]);
    }
  }

  return deduped;
}

// ---------- 组件 ----------

export function Breadcrumb() {
  const location = useLocation();
  const navigate = useNavigate();

  const crumbs = useMemo(() => buildBreadcrumbs(location.pathname), [location.pathname]);

  if (crumbs.length <= 1) return null; // 首页不显示面包屑

  return (
    <nav
      aria-label="breadcrumb"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 12,
        color: 'var(--text-4, #666)',
        marginBottom: 16,
        flexWrap: 'wrap',
      }}
    >
      {crumbs.map((crumb, idx) => {
        const isLast = idx === crumbs.length - 1;
        return (
          <span key={idx} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            {idx > 0 && (
              <span style={{ color: 'var(--text-4, #555)', fontSize: 10 }}>/</span>
            )}
            {isLast ? (
              <span style={{ color: 'var(--text-1, #fff)', fontWeight: 600 }}>
                {crumb.label}
              </span>
            ) : (
              <span
                onClick={() => crumb.path && navigate(crumb.path)}
                style={{
                  cursor: crumb.path ? 'pointer' : 'default',
                  color: 'var(--text-3, #999)',
                  transition: 'color 0.15s',
                }}
                onMouseEnter={(e) => {
                  if (crumb.path) e.currentTarget.style.color = 'var(--brand, #ff6b2c)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.color = 'var(--text-3, #999)';
                }}
              >
                {crumb.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
