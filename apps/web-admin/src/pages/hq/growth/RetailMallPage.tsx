/**
 * RetailMallPage — 线上商城管理
 * 路由: /hq/growth/retail-mall
 * 商品管理 + 订单管理 + 数据看板
 */
import { useState } from 'react';

const BG_1 = '#112228';
const BG_2 = '#1a2a33';
const BRAND = '#FF6B2C';
const GREEN = '#52c41a';
const RED = '#ff4d4f';
const YELLOW = '#faad14';
const BLUE = '#1890ff';
const PURPLE = '#722ed1';
const TEXT_1 = '#ffffff';
const TEXT_2 = '#cccccc';
const TEXT_3 = '#999999';
const TEXT_4 = '#666666';

type TabKey = 'products' | 'orders' | 'analytics';

interface RetailProduct {
  id: string;
  name: string;
  category: string;
  priceFen: number;
  originalPriceFen: number;
  stock: number;
  sales: number;
  status: '在售' | '下架' | '草稿';
  imageUrl?: string;
  createdAt: string;
}

interface RetailOrder {
  id: string;
  customerName: string;
  customerPhone: string;
  itemCount: number;
  totalFen: number;
  status: '待支付' | '待发货' | '已发货' | '已完成' | '已取消';
  payMethod: string;
  createdAt: string;
  deliveryType: '快递' | '到店自提';
}

interface KPI {
  label: string;
  value: string;
  sub: string;
  trend?: 'up' | 'down';
}

const MOCK_KPIS: KPI[] = [
  { label: '在售商品', value: '32', sub: '共 5 个分类', trend: 'up' },
  { label: '本月订单', value: '486', sub: '环比 +23.5%', trend: 'up' },
  { label: '本月GMV', value: '¥12.8万', sub: '客单价 ¥263', trend: 'up' },
  { label: '发货及时率', value: '96.2%', sub: '超时 2 单', trend: 'up' },
];

const MOCK_PRODUCTS: RetailProduct[] = [
  { id: 'rp-001', name: '招牌海鲜大礼包', category: '海鲜礼盒', priceFen: 39800, originalPriceFen: 49800, stock: 120, sales: 86, status: '在售', createdAt: '2026-02-10' },
  { id: 'rp-002', name: '精选三文鱼礼盒', category: '海鲜礼盒', priceFen: 25800, originalPriceFen: 29800, stock: 85, sales: 142, status: '在售', createdAt: '2026-02-15' },
  { id: 'rp-003', name: '特制辣椒酱 500g', category: '调味品', priceFen: 3800, originalPriceFen: 3800, stock: 500, sales: 328, status: '在售', createdAt: '2026-01-20' },
  { id: 'rp-004', name: '手工水饺 40只装', category: '速冻食品', priceFen: 6800, originalPriceFen: 7800, stock: 0, sales: 56, status: '下架', createdAt: '2026-03-01' },
  { id: 'rp-005', name: '100元储值卡', category: '礼品卡', priceFen: 9500, originalPriceFen: 10000, stock: 999, sales: 210, status: '在售', createdAt: '2026-01-01' },
  { id: 'rp-006', name: '端午粽子礼盒', category: '节日特供', priceFen: 19800, originalPriceFen: 23800, stock: 200, sales: 0, status: '草稿', createdAt: '2026-03-28' },
];

const MOCK_ORDERS: RetailOrder[] = [
  { id: 'ro-001', customerName: '王**', customerPhone: '138****8001', itemCount: 2, totalFen: 65600, status: '已完成', payMethod: '微信支付', createdAt: '2026-04-01 10:23', deliveryType: '快递' },
  { id: 'ro-002', customerName: '李**', customerPhone: '139****9002', itemCount: 1, totalFen: 39800, status: '待发货', payMethod: '支付宝', createdAt: '2026-04-01 09:15', deliveryType: '快递' },
  { id: 'ro-003', customerName: '张**', customerPhone: '137****7003', itemCount: 3, totalFen: 11400, status: '已发货', payMethod: '微信支付', createdAt: '2026-03-31 16:40', deliveryType: '快递' },
  { id: 'ro-004', customerName: '赵**', customerPhone: '136****6004', itemCount: 1, totalFen: 9500, status: '待支付', payMethod: '-', createdAt: '2026-04-01 11:05', deliveryType: '到店自提' },
  { id: 'ro-005', customerName: '陈**', customerPhone: '135****5005', itemCount: 2, totalFen: 29600, status: '已取消', payMethod: '微信支付', createdAt: '2026-03-30 20:30', deliveryType: '快递' },
];

const fen = (v: number) => `¥${(v / 100).toFixed(2)}`;

export function RetailMallPage() {
  const [tab, setTab] = useState<TabKey>('products');

  const tabs: { key: TabKey; label: string }[] = [
    { key: 'products', label: '商品管理' },
    { key: 'orders', label: '订单管理' },
    { key: 'analytics', label: '数据看板' },
  ];

  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', color: TEXT_1, fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' }}>
      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>线上商城</h1>
          <div style={{ fontSize: 13, color: TEXT_3, marginTop: 4 }}>零售商品·礼品卡·预制菜·周边</div>
        </div>
        <button style={{ background: BRAND, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>+ 添加商品</button>
      </div>

      {/* KPIs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
        {MOCK_KPIS.map(k => (
          <div key={k.label} style={{ background: BG_2, borderRadius: 8, padding: 16 }}>
            <div style={{ fontSize: 13, color: TEXT_3 }}>{k.label}</div>
            <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{k.value}</div>
            <div style={{ fontSize: 12, color: k.trend === 'up' ? GREEN : RED, marginTop: 4 }}>↑ {k.sub}</div>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: BG_2, borderRadius: 8, padding: 4, width: 'fit-content' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)}
            style={{
              padding: '8px 20px', fontSize: 14, fontWeight: tab === t.key ? 600 : 400, cursor: 'pointer',
              border: 'none', borderRadius: 6,
              background: tab === t.key ? BRAND : 'transparent',
              color: tab === t.key ? '#fff' : TEXT_3,
            }}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'products' && <ProductsTab />}
      {tab === 'orders' && <OrdersTab />}
      {tab === 'analytics' && <AnalyticsTab />}
    </div>
  );
}

function ProductsTab() {
  return (
    <div style={{ background: BG_2, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', display: 'flex', gap: 8, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <input placeholder="搜索商品名称" style={{ flex: 1, padding: '6px 12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: TEXT_1, fontSize: 13, outline: 'none' }} />
        {['全部', '在售', '下架', '草稿'].map(f => (
          <button key={f} style={{ padding: '6px 12px', background: f === '全部' ? 'rgba(255,107,44,0.15)' : 'transparent', color: f === '全部' ? BRAND : TEXT_3, border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>{f}</button>
        ))}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
            {['商品名称', '分类', '售价', '原价', '库存', '销量', '状态', '操作'].map(h => (
              <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MOCK_PRODUCTS.map(p => (
            <tr key={p.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '14px 16px', fontWeight: 500 }}>{p.name}</td>
              <td style={{ padding: '14px 16px', color: TEXT_3 }}>{p.category}</td>
              <td style={{ padding: '14px 16px', color: RED, fontWeight: 600 }}>{fen(p.priceFen)}</td>
              <td style={{ padding: '14px 16px', color: TEXT_4, textDecoration: p.priceFen < p.originalPriceFen ? 'line-through' : 'none' }}>{fen(p.originalPriceFen)}</td>
              <td style={{ padding: '14px 16px', color: p.stock === 0 ? RED : p.stock < 10 ? YELLOW : TEXT_1 }}>{p.stock}</td>
              <td style={{ padding: '14px 16px' }}>{p.sales}</td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{
                  padding: '2px 10px', borderRadius: 12, fontSize: 12,
                  background: p.status === '在售' ? 'rgba(82,196,26,0.15)' : p.status === '下架' ? 'rgba(255,77,79,0.15)' : 'rgba(255,255,255,0.06)',
                  color: p.status === '在售' ? GREEN : p.status === '下架' ? RED : TEXT_4,
                }}>{p.status}</span>
              </td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{ color: BLUE, cursor: 'pointer', marginRight: 12 }}>编辑</span>
                {p.status === '在售'
                  ? <span style={{ color: YELLOW, cursor: 'pointer' }}>下架</span>
                  : <span style={{ color: GREEN, cursor: 'pointer' }}>上架</span>
                }
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OrdersTab() {
  return (
    <div style={{ background: BG_2, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', display: 'flex', gap: 8, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <input placeholder="搜索订单号 / 手机号" style={{ flex: 1, padding: '6px 12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: TEXT_1, fontSize: 13, outline: 'none' }} />
        {['全部', '待支付', '待发货', '已发货', '已完成'].map(f => (
          <button key={f} style={{ padding: '6px 12px', background: f === '全部' ? 'rgba(255,107,44,0.15)' : 'transparent', color: f === '全部' ? BRAND : TEXT_3, border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>{f}</button>
        ))}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
            {['订单号', '顾客', '商品数', '总金额', '支付方式', '配送', '状态', '下单时间', '操作'].map(h => (
              <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MOCK_ORDERS.map(o => (
            <tr key={o.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
              <td style={{ padding: '14px 16px', fontFamily: 'monospace', fontSize: 13 }}>{o.id}</td>
              <td style={{ padding: '14px 16px' }}>{o.customerName} <span style={{ color: TEXT_4, fontSize: 12 }}>{o.customerPhone}</span></td>
              <td style={{ padding: '14px 16px' }}>{o.itemCount}</td>
              <td style={{ padding: '14px 16px', fontWeight: 600 }}>{fen(o.totalFen)}</td>
              <td style={{ padding: '14px 16px', color: TEXT_3 }}>{o.payMethod}</td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{ fontSize: 12, padding: '2px 8px', borderRadius: 4, background: o.deliveryType === '快递' ? 'rgba(24,144,255,0.1)' : 'rgba(114,46,209,0.1)', color: o.deliveryType === '快递' ? BLUE : PURPLE }}>{o.deliveryType}</span>
              </td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{
                  padding: '2px 10px', borderRadius: 12, fontSize: 12,
                  background: o.status === '已完成' ? 'rgba(82,196,26,0.15)' : o.status === '待发货' ? 'rgba(250,173,20,0.15)' : o.status === '已发货' ? 'rgba(24,144,255,0.15)' : o.status === '已取消' ? 'rgba(255,255,255,0.06)' : 'rgba(255,77,79,0.15)',
                  color: o.status === '已完成' ? GREEN : o.status === '待发货' ? YELLOW : o.status === '已发货' ? BLUE : o.status === '已取消' ? TEXT_4 : RED,
                }}>{o.status}</span>
              </td>
              <td style={{ padding: '14px 16px', color: TEXT_3, fontSize: 13 }}>{o.createdAt}</td>
              <td style={{ padding: '14px 16px' }}>
                <span style={{ color: BLUE, cursor: 'pointer' }}>详情</span>
                {o.status === '待发货' && <span style={{ color: GREEN, cursor: 'pointer', marginLeft: 12 }}>发货</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AnalyticsTab() {
  const categoryData = [
    { name: '海鲜礼盒', sales: 228, revenue: 149260 },
    { name: '调味品', sales: 328, revenue: 124640 },
    { name: '礼品卡', sales: 210, revenue: 199500 },
    { name: '速冻食品', sales: 56, revenue: 38080 },
  ];
  const maxRevenue = Math.max(...categoryData.map(d => d.revenue));

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div style={{ background: BG_2, borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>分类销售排行</h3>
        {categoryData.map((d, i) => (
          <div key={d.name} style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
              <span style={{ color: TEXT_2 }}><span style={{ color: i < 2 ? BRAND : TEXT_4, fontWeight: 700, marginRight: 6 }}>{i + 1}</span>{d.name}</span>
              <span style={{ fontWeight: 600 }}>{fen(d.revenue)}</span>
            </div>
            <div style={{ height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
              <div style={{ width: `${(d.revenue / maxRevenue) * 100}%`, height: '100%', background: i === 0 ? BRAND : i === 1 ? BLUE : i === 2 ? GREEN : PURPLE, borderRadius: 3 }} />
            </div>
            <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>{d.sales} 件售出</div>
          </div>
        ))}
      </div>
      <div style={{ background: BG_2, borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>运营指标</h3>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          {[
            { label: '退货率', value: '2.1%', status: 'good' },
            { label: '平均发货时长', value: '1.2天', status: 'good' },
            { label: '好评率', value: '98.5%', status: 'good' },
            { label: '复购率', value: '35.2%', status: 'normal' },
            { label: '购物车转化率', value: '62.8%', status: 'normal' },
            { label: '客诉率', value: '0.8%', status: 'good' },
          ].map(m => (
            <div key={m.label} style={{ padding: 14, background: 'rgba(255,255,255,0.03)', borderRadius: 8 }}>
              <div style={{ fontSize: 12, color: TEXT_3 }}>{m.label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4, color: m.status === 'good' ? GREEN : TEXT_1 }}>{m.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
