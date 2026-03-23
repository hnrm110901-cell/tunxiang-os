import React, { useState } from 'react';

const BRAND = '#FF6B2C';

interface AppItem {
  name: string;
  category: string;
  developer: string;
  description: string;
  rating: number;
  installs: string;
  tags: string[];
  price: string;
}

const CATEGORIES = ['全部', '供应链对接', '外卖聚合', '财务税务', 'AI增值'];

const APPS: AppItem[] = [
  // 供应链对接
  { name: '美菜供应链直连', category: '供应链对接', developer: '美菜网', description: '一键对接美菜供应链，自动下单补货，价格实时同步', rating: 4.7, installs: '3,200+', tags: ['采购', '自动补货'], price: '免费' },
  { name: '快驴进货连接器', category: '供应链对接', developer: '美团快驴', description: '快驴进货平台数据打通，采购单/入库单自动流转', rating: 4.5, installs: '2,800+', tags: ['采购', '库存'], price: '99元/月' },
  { name: '蜀海供应链集成', category: '供应链对接', developer: '蜀海科技', description: '海底捞旗下供应链平台，冷链配送全程可追溯', rating: 4.8, installs: '1,500+', tags: ['冷链', '溯源'], price: '免费' },

  // 外卖聚合
  { name: '三平台外卖聚合', category: '外卖聚合', developer: '聚食汇', description: '美团/饿了么/抖音外卖订单统一接收，自动接单派单', rating: 4.6, installs: '8,500+', tags: ['接单', '多平台'], price: '199元/月' },
  { name: '外卖数据分析助手', category: '外卖聚合', developer: '数析科技', description: '跨平台外卖经营数据汇总分析，竞品监控，智能定价建议', rating: 4.4, installs: '2,100+', tags: ['分析', '定价'], price: '149元/月' },

  // 财务税务
  { name: '智能发票管理', category: '财务税务', developer: '票易通', description: '电子发票自动开具，进项发票OCR识别，税务申报辅助', rating: 4.5, installs: '4,200+', tags: ['发票', '税务'], price: '99元/月' },
  { name: '餐饮财务记账', category: '财务税务', developer: '食算科技', description: '餐饮行业专属记账工具，自动生成损益表/资产负债表', rating: 4.3, installs: '3,100+', tags: ['记账', '报表'], price: '199元/月' },
  { name: '银企直连对账', category: '财务税务', developer: '云账房', description: '对接主流银行，流水自动匹配，日清日结', rating: 4.6, installs: '1,800+', tags: ['对账', '银行'], price: '299元/月' },

  // AI增值
  { name: 'AI 智能排班', category: 'AI增值', developer: '屯象Labs', description: '基于历史客流预测，自动生成最优排班方案，降低人力成本15%+', rating: 4.8, installs: '2,600+', tags: ['排班', '预测'], price: '299元/月' },
  { name: 'AI 菜单优化师', category: 'AI增值', developer: '屯象Labs', description: '分析销售数据与顾客偏好，推荐菜品定价/组合/上下架策略', rating: 4.7, installs: '1,900+', tags: ['菜单', '优化'], price: '199元/月' },
  { name: 'AI 客服机器人', category: 'AI增值', developer: '智语科技', description: '外卖平台自动回复，顾客投诉智能分类处理，好评率提升20%', rating: 4.4, installs: '3,400+', tags: ['客服', '外卖'], price: '149元/月' },
];

const CATEGORY_COLORS: Record<string, string> = {
  '供应链对接': '#3b82f6',
  '外卖聚合': '#f59e0b',
  '财务税务': '#22c55e',
  'AI增值': '#a855f7',
};

export default function MarketplacePage() {
  const [activeCategory, setActiveCategory] = useState('全部');

  const filtered = activeCategory === '全部' ? APPS : APPS.filter((a) => a.category === activeCategory);

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '40px 24px 80px' }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, color: '#111', marginBottom: 8 }}>应用市场</h1>
      <p style={{ fontSize: 15, color: '#6b7280', marginBottom: 28 }}>
        发现优质第三方插件，扩展屯象OS的能力边界
      </p>

      {/* Category Tabs */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 28 }}>
        {CATEGORIES.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            style={{
              padding: '8px 18px', borderRadius: 20, fontSize: 14, fontWeight: 500, cursor: 'pointer',
              border: activeCategory === cat ? 'none' : '1px solid #d1d5db',
              background: activeCategory === cat ? BRAND : '#fff',
              color: activeCategory === cat ? '#fff' : '#4b5563',
            }}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* App Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20 }}>
        {filtered.map((app) => (
          <div
            key={app.name}
            style={{
              background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12,
              padding: 24, display: 'flex', flexDirection: 'column',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: '#111', marginBottom: 4 }}>{app.name}</div>
                <div style={{ fontSize: 12, color: '#9ca3af' }}>{app.developer}</div>
              </div>
              <span style={{
                padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
                color: '#fff', background: CATEGORY_COLORS[app.category] || '#6b7280',
              }}>{app.category}</span>
            </div>

            <p style={{ fontSize: 13, color: '#4b5563', lineHeight: 1.6, marginBottom: 16, flex: 1 }}>
              {app.description}
            </p>

            <div style={{ display: 'flex', gap: 6, marginBottom: 14 }}>
              {app.tags.map((t) => (
                <span key={t} style={{ padding: '2px 8px', background: '#f3f4f6', borderRadius: 4, fontSize: 11, color: '#6b7280' }}>
                  {t}
                </span>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: 14, borderTop: '1px solid #f3f4f6' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#f59e0b' }}>
                  {'*'.repeat(Math.round(app.rating))} {app.rating}
                </span>
                <span style={{ fontSize: 12, color: '#9ca3af' }}>{app.installs} 安装</span>
              </div>
              <span style={{ fontSize: 13, fontWeight: 600, color: app.price === '免费' ? '#22c55e' : '#111' }}>
                {app.price}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
