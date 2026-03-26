import React, { useState, useMemo } from 'react';

const BRAND = '#FF6B2C';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Types
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

interface AppItem {
  id: string;
  name: string;
  category: string;
  categoryKey: string;
  developer: string;
  company: string;
  description: string;
  rating: number;
  ratingCount: number;
  installs: number;
  installsDisplay: string;
  tags: string[];
  pricingModel: string;
  priceDisplay: string;
  priceFen: number;
  version: string;
  iconBg: string;
  iconEmoji: string;
}

interface CategoryDef {
  key: string;
  name: string;
  icon: string;
  description: string;
  color: string;
}

type SortOption = 'popularity' | 'newest' | 'rating' | 'price';

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Categories
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const CATEGORIES: CategoryDef[] = [
  { key: 'supply_chain', name: '供应链对接', icon: '🚚', description: '供应商ERP集成、采购管理', color: '#3b82f6' },
  { key: 'delivery', name: '外卖聚合', icon: '🛵', description: '美团/饿了么/抖音统一管理', color: '#f59e0b' },
  { key: 'finance', name: '财务税务', icon: '🧮', description: '金蝶/用友/税务申报对接', color: '#22c55e' },
  { key: 'ai_addon', name: 'AI增值', icon: '🧠', description: '语音点餐/AR菜单/智能客服', color: '#a855f7' },
  { key: 'iot', name: 'IoT设备', icon: '📡', description: '温控/称重/能耗监测集成', color: '#06b6d4' },
  { key: 'analytics', name: '行业数据', icon: '📊', description: '行业报告/竞品分析/趋势预测', color: '#6366f1' },
  { key: 'marketing', name: '营销工具', icon: '📣', description: '私域运营/社交裂变/短视频', color: '#ec4899' },
  { key: 'hr', name: '人力资源', icon: '👥', description: '招聘/培训/绩效/社保', color: '#14b8a6' },
  { key: 'payment', name: '支付集成', icon: '💳', description: '聚合支付/数字货币/分期', color: '#f97316' },
  { key: 'compliance', name: '合规安全', icon: '🛡️', description: '食安审计/证照管理/消防', color: '#ef4444' },
];

const CATEGORY_MAP: Record<string, CategoryDef> = {};
for (const cat of CATEGORIES) {
  CATEGORY_MAP[cat.key] = cat;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Seed Apps (matches backend data)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const APPS: AppItem[] = [
  {
    id: 'app_meituan_delivery',
    name: '美团外卖聚合',
    categoryKey: 'delivery',
    category: '外卖聚合',
    developer: '美团外卖开放平台',
    company: '北京三快在线科技有限公司',
    description: '美团外卖官方对接插件。自动接单、订单状态同步、配送轨迹追踪、差评预警、经营数据看板。支持多店统一管理，日均处理10万+订单。',
    rating: 4.7,
    ratingCount: 328,
    installs: 8560,
    installsDisplay: '8,560+',
    tags: ['自动接单', '配送追踪', '差评预警'],
    pricingModel: 'monthly',
    priceDisplay: '299元/月/门店',
    priceFen: 29900,
    version: '2.4.1',
    iconBg: '#FEF3C7',
    iconEmoji: '🛵',
  },
  {
    id: 'app_kingdee_voucher',
    name: '金蝶云凭证',
    categoryKey: 'finance',
    category: '财务税务',
    developer: '金蝶云星辰',
    company: '深圳市金蝶软件科技有限公司',
    description: '屯象OS经营数据自动生成金蝶记账凭证。日结数据自动推送金蝶云星辰，支持多品牌合并报表，省去财务手工录入。',
    rating: 4.5,
    ratingCount: 186,
    installs: 3240,
    installsDisplay: '3,240+',
    tags: ['自动凭证', '合并报表', '金蝶对接'],
    pricingModel: 'monthly',
    priceDisplay: '199元/月/门店',
    priceFen: 19900,
    version: '1.8.0',
    iconBg: '#DBEAFE',
    iconEmoji: '🧮',
  },
  {
    id: 'app_voice_ordering',
    name: '智能语音点餐',
    categoryKey: 'ai_addon',
    category: 'AI增值',
    developer: '屯象AI实验室',
    company: '屯象科技（湖南）有限公司',
    description: '基于屯象AI引擎的语音点餐能力。顾客用自然语言下单，支持方言识别（湘/粤/川）、模糊菜名匹配、智能推荐加购。',
    rating: 4.8,
    ratingCount: 412,
    installs: 2150,
    installsDisplay: '2,150+',
    tags: ['语音识别', '方言支持', '智能推荐'],
    pricingModel: 'usage_based',
    priceDisplay: '0.1元/次调用',
    priceFen: 10,
    version: '3.1.2',
    iconBg: '#F3E8FF',
    iconEmoji: '🧠',
  },
  {
    id: 'app_seafood_tank',
    name: '海鲜池温控',
    categoryKey: 'iot',
    category: 'IoT设备',
    developer: '海蓝物联',
    company: '广州海蓝物联科技有限公司',
    description: '海鲜池水温/盐度/溶氧实时监测。异常自动报警，历史数据趋势分析，设备远程控制。减少海鲜损耗30%+。',
    rating: 4.6,
    ratingCount: 95,
    installs: 680,
    installsDisplay: '680+',
    tags: ['实时监测', '异常报警', '远程控制'],
    pricingModel: 'per_store',
    priceDisplay: '99元/门店/月',
    priceFen: 9900,
    version: '1.5.3',
    iconBg: '#CFFAFE',
    iconEmoji: '🌊',
  },
  {
    id: 'app_food_safety',
    name: '食安巡检助手',
    categoryKey: 'compliance',
    category: '合规安全',
    developer: '食安卫士',
    company: '杭州食安卫士科技有限公司',
    description: '食品安全巡检数字化工具。每日巡检清单、拍照留痕、自动生成合规报告。对接市监局明厨亮灶系统，证照到期自动提醒。',
    rating: 4.9,
    ratingCount: 520,
    installs: 12300,
    installsDisplay: '12,300+',
    tags: ['巡检清单', '拍照留痕', '明厨亮灶'],
    pricingModel: 'free',
    priceDisplay: '免费',
    priceFen: 0,
    version: '2.0.1',
    iconBg: '#FEE2E2',
    iconEmoji: '🛡️',
  },
  {
    id: 'app_douyin_marketing',
    name: '抖音营销',
    categoryKey: 'marketing',
    category: '营销工具',
    developer: '抖音本地生活',
    company: '北京字节跳动科技有限公司',
    description: '抖音本地生活一站式营销。团购券创建与核销、达人探店邀约管理、短视频素材库、直播预约引流。ROI数据实时追踪。',
    rating: 4.4,
    ratingCount: 267,
    installs: 4820,
    installsDisplay: '4,820+',
    tags: ['团购券', '达人探店', 'ROI追踪'],
    pricingModel: 'monthly',
    priceDisplay: '399元/月',
    priceFen: 39900,
    version: '1.9.4',
    iconBg: '#FCE7F3',
    iconEmoji: '📣',
  },
  {
    id: 'app_supplier_direct',
    name: '供应商直连',
    categoryKey: 'supply_chain',
    category: '供应链对接',
    developer: '供直达',
    company: '成都供直达科技有限公司',
    description: '餐企与供应商直连平台。基础功能免费：供应商目录、询比价、下单。高级版：智能补货预测、合同管理、质检追溯。',
    rating: 4.3,
    ratingCount: 142,
    installs: 1890,
    installsDisplay: '1,890+',
    tags: ['供应商目录', '询比价', '智能补货'],
    pricingModel: 'freemium',
    priceDisplay: '基础免费',
    priceFen: 0,
    version: '2.2.0',
    iconBg: '#DBEAFE',
    iconEmoji: '🚚',
  },
];

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Sort options
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const SORT_OPTIONS: { key: SortOption; label: string }[] = [
  { key: 'popularity', label: '热门' },
  { key: 'newest', label: '最新' },
  { key: 'rating', label: '评分' },
  { key: 'price', label: '价格' },
];

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Star renderer
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function renderStars(rating: number): string {
  const full = Math.floor(rating);
  const half = rating - full >= 0.5 ? 1 : 0;
  const empty = 5 - full - half;
  return '\u2605'.repeat(full) + (half ? '\u00BD' : '') + '\u2606'.repeat(empty);
}

function formatInstalls(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}万+`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}K+`;
  return `${n}+`;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
//  Component
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

export default function MarketplacePage() {
  const [activeCategory, setActiveCategory] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortBy, setSortBy] = useState<SortOption>('popularity');

  const filtered = useMemo(() => {
    let result = [...APPS];

    // Category filter
    if (activeCategory) {
      result = result.filter((a) => a.categoryKey === activeCategory);
    }

    // Search filter
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      result = result.filter(
        (a) =>
          a.name.toLowerCase().includes(q) ||
          a.description.toLowerCase().includes(q) ||
          a.category.toLowerCase().includes(q) ||
          a.developer.toLowerCase().includes(q) ||
          a.tags.some((t) => t.toLowerCase().includes(q))
      );
    }

    // Sort
    switch (sortBy) {
      case 'popularity':
        result.sort((a, b) => b.installs - a.installs);
        break;
      case 'newest':
        result.sort((a, b) => b.version.localeCompare(a.version));
        break;
      case 'rating':
        result.sort((a, b) => b.rating - a.rating);
        break;
      case 'price':
        result.sort((a, b) => a.priceFen - b.priceFen);
        break;
    }

    return result;
  }, [activeCategory, searchQuery, sortBy]);

  return (
    <div style={{ display: 'flex', maxWidth: 1280, margin: '0 auto', padding: '32px 24px 80px', gap: 28 }}>

      {/* ── Left sidebar: categories ── */}
      <aside style={{ width: 220, flexShrink: 0 }}>
        <h3 style={{ fontSize: 13, fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>
          应用分类
        </h3>

        {/* All button */}
        <button
          onClick={() => setActiveCategory(null)}
          style={{
            display: 'flex', alignItems: 'center', gap: 10, width: '100%',
            padding: '10px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
            fontSize: 14, fontWeight: activeCategory === null ? 600 : 400,
            color: activeCategory === null ? BRAND : '#374151',
            background: activeCategory === null ? '#FFF5F0' : 'transparent',
            marginBottom: 4, textAlign: 'left',
          }}
        >
          <span style={{ fontSize: 16 }}>📦</span>
          <span>全部应用</span>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: '#9ca3af' }}>{APPS.length}</span>
        </button>

        {CATEGORIES.map((cat) => {
          const count = APPS.filter((a) => a.categoryKey === cat.key).length;
          const isActive = activeCategory === cat.key;
          return (
            <button
              key={cat.key}
              onClick={() => setActiveCategory(isActive ? null : cat.key)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                padding: '10px 14px', borderRadius: 8, border: 'none', cursor: 'pointer',
                fontSize: 14, fontWeight: isActive ? 600 : 400,
                color: isActive ? cat.color : '#374151',
                background: isActive ? `${cat.color}10` : 'transparent',
                marginBottom: 4, textAlign: 'left',
              }}
            >
              <span style={{ fontSize: 16 }}>{cat.icon}</span>
              <span>{cat.name}</span>
              {count > 0 && (
                <span style={{ marginLeft: 'auto', fontSize: 12, color: '#9ca3af' }}>{count}</span>
              )}
            </button>
          );
        })}
      </aside>

      {/* ── Main content ── */}
      <div style={{ flex: 1, minWidth: 0 }}>

        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: '#111', marginBottom: 6 }}>
            应用市场
          </h1>
          <p style={{ fontSize: 15, color: '#6b7280', margin: 0 }}>
            发现优质第三方应用，扩展屯象OS的能力边界 — 供应链、外卖、财务、AI、IoT 一站集成
          </p>
        </div>

        {/* Search + Sort bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
          {/* Search */}
          <div style={{ flex: 1, position: 'relative' }}>
            <input
              type="text"
              placeholder="搜索应用名称、开发者、功能..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%', padding: '10px 16px 10px 40px', borderRadius: 10,
                border: '1px solid #d1d5db', fontSize: 14, outline: 'none',
                background: '#fff', boxSizing: 'border-box',
              }}
            />
            <span style={{
              position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)',
              fontSize: 16, color: '#9ca3af', pointerEvents: 'none',
            }}>
              🔍
            </span>
          </div>

          {/* Sort */}
          <div style={{ display: 'flex', gap: 4, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 3 }}>
            {SORT_OPTIONS.map((opt) => (
              <button
                key={opt.key}
                onClick={() => setSortBy(opt.key)}
                style={{
                  padding: '6px 14px', borderRadius: 8, fontSize: 13, fontWeight: 500,
                  cursor: 'pointer', border: 'none',
                  background: sortBy === opt.key ? BRAND : 'transparent',
                  color: sortBy === opt.key ? '#fff' : '#6b7280',
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Active category banner */}
        {activeCategory && CATEGORY_MAP[activeCategory] && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px',
            background: '#fff', border: `1px solid ${CATEGORY_MAP[activeCategory].color}30`,
            borderRadius: 10, marginBottom: 20,
          }}>
            <span style={{ fontSize: 28 }}>{CATEGORY_MAP[activeCategory].icon}</span>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#111' }}>
                {CATEGORY_MAP[activeCategory].name}
              </div>
              <div style={{ fontSize: 13, color: '#6b7280' }}>
                {CATEGORY_MAP[activeCategory].description}
              </div>
            </div>
            <button
              onClick={() => setActiveCategory(null)}
              style={{
                marginLeft: 'auto', padding: '4px 12px', borderRadius: 6,
                border: '1px solid #d1d5db', background: '#fff', fontSize: 12,
                color: '#6b7280', cursor: 'pointer',
              }}
            >
              清除筛选
            </button>
          </div>
        )}

        {/* Results count */}
        <div style={{ fontSize: 13, color: '#9ca3af', marginBottom: 16 }}>
          共 {filtered.length} 个应用
          {searchQuery && <span> — 搜索 "{searchQuery}"</span>}
        </div>

        {/* App Grid */}
        {filtered.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: '80px 0', color: '#9ca3af',
          }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>📭</div>
            <div style={{ fontSize: 16, fontWeight: 500 }}>没有找到匹配的应用</div>
            <div style={{ fontSize: 13, marginTop: 4 }}>试试其他关键词或分类</div>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320, 1fr))', gap: 18 }}>
            {filtered.map((app) => {
              const catDef = CATEGORY_MAP[app.categoryKey];
              return (
                <div
                  key={app.id}
                  style={{
                    background: '#fff', border: '1px solid #e5e7eb', borderRadius: 14,
                    padding: 22, display: 'flex', flexDirection: 'column',
                    transition: 'box-shadow .2s, border-color .2s', cursor: 'pointer',
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLDivElement).style.boxShadow = '0 4px 16px rgba(0,0,0,0.08)';
                    (e.currentTarget as HTMLDivElement).style.borderColor = '#c7c7c7';
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLDivElement).style.boxShadow = 'none';
                    (e.currentTarget as HTMLDivElement).style.borderColor = '#e5e7eb';
                  }}
                >
                  {/* Top row: icon + name + category badge */}
                  <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 14 }}>
                    {/* App icon */}
                    <div style={{
                      width: 48, height: 48, borderRadius: 12, background: app.iconBg,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 24, flexShrink: 0,
                    }}>
                      {app.iconEmoji}
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <div style={{
                          fontSize: 16, fontWeight: 700, color: '#111',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}>
                          {app.name}
                        </div>
                        <span style={{ fontSize: 11, color: '#9ca3af' }}>v{app.version}</span>
                      </div>
                      <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 2 }}>
                        {app.developer}
                      </div>
                    </div>

                    {/* Category badge */}
                    {catDef && (
                      <span style={{
                        padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
                        color: '#fff', background: catDef.color, whiteSpace: 'nowrap', flexShrink: 0,
                      }}>
                        {catDef.name}
                      </span>
                    )}
                  </div>

                  {/* Description */}
                  <p style={{
                    fontSize: 13, color: '#4b5563', lineHeight: 1.7, marginBottom: 14, flex: 1,
                    display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  } as React.CSSProperties}>
                    {app.description}
                  </p>

                  {/* Tags */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
                    {app.tags.map((t) => (
                      <span key={t} style={{
                        padding: '2px 10px', background: '#f3f4f6', borderRadius: 6,
                        fontSize: 11, color: '#6b7280',
                      }}>
                        {t}
                      </span>
                    ))}
                  </div>

                  {/* Footer: rating + installs + price */}
                  <div style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    paddingTop: 14, borderTop: '1px solid #f3f4f6',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: '#f59e0b' }}>
                        {renderStars(app.rating)} {app.rating}
                      </span>
                      <span style={{ fontSize: 12, color: '#9ca3af' }}>
                        {formatInstalls(app.installs)} 安装
                      </span>
                    </div>
                    <span style={{
                      fontSize: 14, fontWeight: 700,
                      color: app.priceFen === 0 ? '#22c55e' : '#111',
                    }}>
                      {app.priceDisplay}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
