/**
 * 管理中心 — 店长/楼面经理功能入口聚合页
 * 路由：/sm/management
 *
 * 聚合 D1-D4 所有P0-P3 新功能，按业务域分区
 */
import React from 'react';
import { Link } from 'react-router-dom';
import styles from './ManagementHub.module.css';

interface Tile {
  name: string;
  desc: string;
  icon: string;
  to: string;
  isNew?: boolean;
}

interface Section {
  title: string;
  tag?: string;
  tiles: Tile[];
}

const SECTIONS: Section[] = [
  {
    title: 'POS 收银运营',
    tag: 'D1',
    tiles: [
      { name: '收银台', desc: '开台/点菜/结算全流程', icon: '💳', to: '/floor/cashier' },
      { name: '楼面管理', desc: '桌台实时状态/开台转台', icon: '🗺️', to: '/floor/manage' },
      { name: '快餐叫号屏', desc: '烹饪中/待取餐大屏', icon: '📢', to: '/floor/queue-board' },
      { name: '收银日结', desc: '班次汇总/现金差异', icon: '📅', to: '/floor/checkout' },
      { name: 'KPI预警阈值', desc: '成本率/损耗告警配置', icon: '⚠️', to: '/alert-thresholds' },
    ],
  },
  {
    title: '厨房管理',
    tag: 'D2',
    tiles: [
      { name: '厨房大屏', desc: 'KDS三列看板/超时追踪', icon: '🍳', to: '/kds/display', isNew: true },
      { name: '厨房手持站', desc: '手机扫码接单/催菜', icon: '📱', to: '/kds/mobile', isNew: true },
      { name: '厨师长驾驶舱', desc: '档口表现/慢菜分析', icon: '📊', to: '/kds/dashboard', isNew: true },
      { name: '沽清管理', desc: '菜品缺货实时标记', icon: '🚫', to: '/chef/soldout' },
      { name: '食品安全', desc: '追溯+健康证+检查', icon: '✅', to: '/food-safety' },
    ],
  },
  {
    title: '会员CRM运营',
    tag: 'D3',
    tiles: [
      { name: '储值卡管理', desc: '开卡/充值/消费/冻结', icon: '💰', to: '/crm/stored-value', isNew: true },
      { name: '积分管理', desc: '会员积分/规则配置', icon: '⭐', to: '/crm/points', isNew: true },
      { name: '挂账账户', desc: '企业授信/还款/账龄', icon: '📒', to: '/crm/credit-accounts', isNew: true },
      { name: '存酒管理', desc: '寄存酒追踪/开瓶消费', icon: '🍾', to: '/crm/wine-storage', isNew: true },
      { name: '押金管理', desc: '预定押金/抵扣/退还', icon: '🔒', to: '/crm/deposits', isNew: true },
      { name: '会员档案', desc: '360画像/偏好/忌口', icon: '👤', to: '/customer360' },
      { name: '私域健康分', desc: '5维度私域经营诊断', icon: '💚', to: '/sm/private-domain-health' },
      { name: '流失预警', desc: 'AI召回+一键发券', icon: '📉', to: '/sm/dormant-recovery' },
    ],
  },
  {
    title: '菜品与菜单',
    tag: 'D4',
    tiles: [
      { name: '菜品管理', desc: '创建/分类/定价/上下架', icon: '🍽️', to: '/dish-management' },
      { name: 'BOM 配方', desc: '物料清单+成本核算', icon: '📋', to: '/bom-management' },
      { name: '活鲜称重', desc: '海鲜池/称重/损耗分析', icon: '🦞', to: '/menu/live-seafood', isNew: true },
      { name: '渠道菜单', desc: '美团/饿了么/抖音同步', icon: '🔄', to: '/menu/channel-menu', isNew: true },
      { name: '菜品健康分', desc: '毛利率/点击率/人气', icon: '💎', to: '/dish-health' },
      { name: '动态定价', desc: '时段/库存/活动定价', icon: '📈', to: '/dish-pricing' },
    ],
  },
  {
    title: '库存与供应链',
    tiles: [
      { name: '库存盘点', desc: '实时库存/批次追溯', icon: '📦', to: '/inventory' },
      { name: '采购订单', desc: '创建采购单/审批', icon: '🛒', to: '/supply-chain' },
      { name: '供应商', desc: '供应商档案/评分', icon: '🏭', to: '/supply-chain' },
      { name: '损耗事件', desc: '废料/过期/盘亏记录', icon: '🗑️', to: '/waste-events' },
    ],
  },
  {
    title: '人事合规',
    tag: 'D9/D11',
    tiles: [
      { name: '培训课程', desc: '课程/课件/报名/进度', icon: '🎓', to: '/hr/training/courses', isNew: true },
      { name: '健康证扫描', desc: '30/15/7/1天分级预警', icon: '🩺', to: '/compliance', isNew: true },
      { name: '劳动合同', desc: '60/30/15天到期预警', icon: '📝', to: '/contract-management', isNew: true },
    ],
  },
  {
    title: '报表与决策',
    tiles: [
      { name: '利润看板', desc: '收入/成本/毛利实时', icon: '💹', to: '/profit-dashboard' },
      { name: '决策中枢', desc: 'Top3决策+影响¥', icon: '🧠', to: '/decision' },
      { name: '月度报告', desc: '经营月报/HTML导出', icon: '📄', to: '/monthly-report' },
      { name: '成本真相', desc: '成本率/损耗/人力', icon: '🔍', to: '/cost-truth' },
    ],
  },
];

export default function ManagementHub() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div className={styles.title}>🏪 管理中心</div>
        <div className={styles.subtitle}>
          智链经营助手 · 全链路运营工具 · 共 {SECTIONS.reduce((s, sec) => s + sec.tiles.length, 0)} 个功能入口
        </div>
      </div>

      {SECTIONS.map((sec) => (
        <div key={sec.title} className={styles.section}>
          <div className={styles.sectionTitle}>
            <span>{sec.title}</span>
            {sec.tag && <span className={styles.sectionTag}>{sec.tag}</span>}
          </div>
          <div className={styles.grid}>
            {sec.tiles.map((t) => (
              <Link key={t.to} to={t.to} className={styles.tile}>
                <div className={styles.tileIcon}>{t.icon}</div>
                <div className={styles.tileName}>
                  {t.name}
                  {t.isNew && <span className={styles.newBadge}>NEW</span>}
                </div>
                <div className={styles.tileDesc}>{t.desc}</div>
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
