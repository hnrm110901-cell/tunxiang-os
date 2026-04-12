/**
 * RetailMallPage — 零售商城管理
 * 路由: /hq/growth/retail-mall
 * 商品管理 + 订单管理 + KPI看板
 */
import { useState, useEffect, useCallback } from 'react';
import { txFetchData } from '../../../api';

const BG_1 = '#0d1e28';
const BG_2 = '#1a2a33';
const BG_3 = '#223040';
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
  price_fen: number;
  original_price_fen: number;
  stock: number;
  sales: number;
  status: '在售' | '下架' | '草稿';
  image_url?: string;
  created_at: string;
}

interface RetailOrder {
  id: string;
  customer_name: string;
  customer_phone: string;
  item_count: number;
  total_fen: number;
  status: '待支付' | '待发货' | '已发货' | '已完成' | '已取消';
  pay_method: string;
  created_at: string;
  delivery_type: '快递' | '到店自提';
}

interface RetailKPI {
  product_count: number;
  order_count: number;
  gmv_fen: number;
  avg_order_fen: number;
  period: string;
}

interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

const fen = (v: number) => `¥${(v / 100).toFixed(2)}`;
const fenShort = (v: number) => v >= 10000000 ? `¥${(v / 10000 / 100).toFixed(1)}万` : fen(v);

function useRetailProducts() {
  const [products, setProducts] = useState<RetailProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [empty, setEmpty] = useState(false);

  const load = useCallback((page = 1) => {
    setLoading(true);
    txFetchData<PaginatedResponse<RetailProduct>>(`/api/v1/menu/dishes?channel=retail&page=${page}&size=20`)
      .then(data => {
        setProducts(data.items || []);
        setTotal(data.total || 0);
        setEmpty((data.items || []).length === 0);
      })
      .catch(() => {
        setProducts([]);
        setTotal(0);
        setEmpty(true);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(1); }, [load]);

  return { products, total, loading, empty, reload: load };
}

function useRetailOrders() {
  const [orders, setOrders] = useState<RetailOrder[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [empty, setEmpty] = useState(false);

  const load = useCallback((page = 1, status?: string) => {
    setLoading(true);
    const qs = status && status !== '全部' ? `&status=${encodeURIComponent(status)}` : '';
    txFetchData<PaginatedResponse<RetailOrder>>(`/api/v1/trade/orders?channel=retail&page=${page}&size=20${qs}`)
      .then(data => {
        setOrders(data.items || []);
        setTotal(data.total || 0);
        setEmpty((data.items || []).length === 0);
      })
      .catch(() => {
        setOrders([]);
        setTotal(0);
        setEmpty(true);
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(1); }, [load]);

  return { orders, total, loading, empty, reload: load };
}

function useRetailKPI() {
  const [kpi, setKpi] = useState<RetailKPI | null>(null);

  useEffect(() => {
    txFetchData<RetailKPI>('/api/v1/analytics/retail/kpi')
      .then(setKpi)
      .catch(() => setKpi(null));
  }, []);

  return kpi;
}

export function RetailMallPage() {
  const { products, loading: productsLoading, empty: productsEmpty } = useRetailProducts();
  const [tab, setTab] = useState<TabKey>('products');

  // 若商品和订单都无数据，展示引导页
  const showGuide = productsEmpty && !productsLoading;

  return (
    <div style={{ padding: 24, background: BG_1, minHeight: '100vh', color: TEXT_1, fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif' }}>
      {/* Header */}
      <div style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 8, background: BRAND, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>🛒</div>
          <div>
            <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>零售商城</h1>
            <div style={{ fontSize: 13, color: TEXT_3, marginTop: 2 }}>礼盒 · 预制菜 · 储值卡 · 周边</div>
          </div>
        </div>
        <button style={{ background: BRAND, color: '#fff', border: 'none', borderRadius: 6, padding: '8px 20px', fontSize: 14, fontWeight: 600, cursor: 'pointer' }}>
          + 上架商品
        </button>
      </div>

      {/* KPI 卡片 */}
      <KPICards />

      {showGuide ? (
        <EmptyGuide />
      ) : (
        <>
          {/* Tabs */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 20, background: BG_2, borderRadius: 8, padding: 4, width: 'fit-content' }}>
            {([
              { key: 'products' as TabKey, label: '商品管理' },
              { key: 'orders' as TabKey, label: '订单管理' },
              { key: 'analytics' as TabKey, label: '数据看板' },
            ]).map(t => (
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
        </>
      )}
    </div>
  );
}

/* ─── KPI 卡片 ─── */
function KPICards() {
  const kpi = useRetailKPI();

  const cards = kpi
    ? [
        { label: '在售商品', value: String(kpi.product_count), sub: `零售渠道`, color: GREEN },
        { label: '本月订单', value: String(kpi.order_count), sub: `统计周期: ${kpi.period}`, color: BLUE },
        { label: '本月GMV', value: fenShort(kpi.gmv_fen), sub: `客单价 ${fen(kpi.avg_order_fen)}`, color: BRAND },
        { label: '商城状态', value: '运营中', sub: '零售渠道正常', color: GREEN },
      ]
    : [
        { label: '在售商品', value: '--', sub: '加载中', color: TEXT_4 },
        { label: '本月订单', value: '--', sub: '加载中', color: TEXT_4 },
        { label: '本月GMV', value: '--', sub: '加载中', color: TEXT_4 },
        { label: '商城状态', value: '--', sub: '加载中', color: TEXT_4 },
      ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
      {cards.map(c => (
        <div key={c.label} style={{ background: BG_2, borderRadius: 8, padding: 16 }}>
          <div style={{ fontSize: 13, color: TEXT_3 }}>{c.label}</div>
          <div style={{ fontSize: 28, fontWeight: 700, marginTop: 4 }}>{c.value}</div>
          <div style={{ fontSize: 12, color: c.color, marginTop: 4 }}>{c.sub}</div>
        </div>
      ))}
    </div>
  );
}

/* ─── 空状态引导 ─── */
function EmptyGuide() {
  const steps = [
    { step: '01', title: '开通零售渠道', desc: '在系统配置中开启零售商城功能，绑定微信小商店或独立商城域名' },
    { step: '02', title: '上架第一批商品', desc: '从门店菜品库中选择预制菜、礼品卡或周边商品，设置零售价格' },
    { step: '03', title: '配置物流方案', desc: '设置快递合作方和到店自提规则，支持全国配送或同城服务' },
    { step: '04', title: '接入支付渠道', desc: '配置微信支付、支付宝等在线支付，支持分期和积分抵扣' },
  ];

  return (
    <div>
      <div style={{ background: 'linear-gradient(135deg, rgba(255,107,44,0.1), rgba(24,144,255,0.06))', border: '1px solid rgba(255,107,44,0.2)', borderRadius: 12, padding: '16px 20px', marginBottom: 24 }}>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>零售商城搭建中</div>
        <div style={{ fontSize: 13, color: TEXT_3 }}>暂无零售渠道数据，完成以下步骤即可开始销售</div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16, marginBottom: 32 }}>
        {steps.map(s => (
          <div key={s.step} style={{ background: BG_2, borderRadius: 12, padding: 20, display: 'flex', gap: 16, alignItems: 'flex-start' }}>
            <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'rgba(255,107,44,0.15)', color: BRAND, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700, flexShrink: 0 }}>{s.step}</div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>{s.title}</div>
              <div style={{ fontSize: 13, color: TEXT_3, lineHeight: 1.5 }}>{s.desc}</div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ textAlign: 'center' }}>
        <button style={{ background: BRAND, color: '#fff', border: 'none', borderRadius: 8, padding: '12px 36px', fontSize: 15, fontWeight: 600, cursor: 'pointer' }}>
          开始搭建商城
        </button>
      </div>
    </div>
  );
}

/* ─── 商品管理 Tab ─── */
function ProductsTab() {
  const { products, total, loading, reload } = useRetailProducts();
  const [filter, setFilter] = useState('全部');
  const [search, setSearch] = useState('');

  const filtered = products.filter(p => {
    const matchStatus = filter === '全部' || p.status === filter;
    const matchSearch = !search || p.name.includes(search);
    return matchStatus && matchSearch;
  });

  const handleStatusToggle = async (p: RetailProduct) => {
    const newStatus = p.status === '在售' ? '下架' : '在售';
    try {
      await txFetchData(`/api/v1/menu/dishes/${p.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status: newStatus, channel: 'retail' }),
      });
      reload();
    } catch {
      // 操作失败静默处理，后续可加 toast
    }
  };

  return (
    <div style={{ background: BG_2, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', display: 'flex', gap: 8, borderBottom: '1px solid rgba(255,255,255,0.06)', alignItems: 'center' }}>
        <input
          placeholder="搜索商品名称"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, padding: '6px 12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: TEXT_1, fontSize: 13, outline: 'none' }}
        />
        {['全部', '在售', '下架', '草稿'].map(f => (
          <button key={f} onClick={() => setFilter(f)}
            style={{ padding: '6px 12px', background: filter === f ? 'rgba(255,107,44,0.15)' : 'transparent', color: filter === f ? BRAND : TEXT_3, border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
            {f}
          </button>
        ))}
        <span style={{ fontSize: 12, color: TEXT_4 }}>共 {total} 件</span>
      </div>

      {loading && <div style={{ textAlign: 'center', padding: 40, color: TEXT_3 }}>加载商品...</div>}

      {!loading && filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: 60, color: TEXT_3 }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📦</div>
          <div>暂无{filter !== '全部' ? filter : ''}商品</div>
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
              {['商品名称', '分类', '售价', '原价', '库存', '销量', '状态', '操作'].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(p => (
              <tr key={p.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '14px 16px', fontWeight: 500 }}>{p.name}</td>
                <td style={{ padding: '14px 16px', color: TEXT_3 }}>{p.category}</td>
                <td style={{ padding: '14px 16px', color: RED, fontWeight: 600 }}>{fen(p.price_fen)}</td>
                <td style={{ padding: '14px 16px', color: TEXT_4, textDecoration: p.price_fen < p.original_price_fen ? 'line-through' : 'none' }}>
                  {fen(p.original_price_fen)}
                </td>
                <td style={{ padding: '14px 16px', color: p.stock === 0 ? RED : p.stock < 10 ? YELLOW : TEXT_1 }}>
                  {p.stock === 0 ? '缺货' : p.stock}
                </td>
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
                  {p.status !== '草稿' && (
                    <span onClick={() => handleStatusToggle(p)}
                      style={{ color: p.status === '在售' ? YELLOW : GREEN, cursor: 'pointer' }}>
                      {p.status === '在售' ? '下架' : '上架'}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/* ─── 订单管理 Tab ─── */
function OrdersTab() {
  const { orders, total, loading, reload } = useRetailOrders();
  const [filter, setFilter] = useState('全部');
  const [search, setSearch] = useState('');

  const handleFilterChange = useCallback((f: string) => {
    setFilter(f);
    reload(1, f);
  }, [reload]);

  const filtered = orders.filter(o =>
    !search || o.id.includes(search) || o.customer_phone.includes(search)
  );

  const handleShip = async (orderId: string) => {
    try {
      await txFetchData(`/api/v1/trade/orders/${orderId}/ship`, { method: 'POST' });
      reload();
    } catch {
      // 静默处理
    }
  };

  return (
    <div style={{ background: BG_2, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '12px 16px', display: 'flex', gap: 8, borderBottom: '1px solid rgba(255,255,255,0.06)', alignItems: 'center' }}>
        <input
          placeholder="搜索订单号 / 手机号"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ flex: 1, padding: '6px 12px', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 6, color: TEXT_1, fontSize: 13, outline: 'none' }}
        />
        {['全部', '待支付', '待发货', '已发货', '已完成'].map(f => (
          <button key={f} onClick={() => handleFilterChange(f)}
            style={{ padding: '6px 12px', background: filter === f ? 'rgba(255,107,44,0.15)' : 'transparent', color: filter === f ? BRAND : TEXT_3, border: 'none', borderRadius: 6, fontSize: 13, cursor: 'pointer' }}>
            {f}
          </button>
        ))}
        <span style={{ fontSize: 12, color: TEXT_4 }}>共 {total} 单</span>
      </div>

      {loading && <div style={{ textAlign: 'center', padding: 40, color: TEXT_3 }}>加载订单...</div>}

      {!loading && filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: 60, color: TEXT_3 }}>
          <div style={{ fontSize: 32, marginBottom: 12 }}>📋</div>
          <div>暂无{filter !== '全部' ? filter : ''}订单</div>
        </div>
      )}

      {!loading && filtered.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
          <thead>
            <tr style={{ background: 'rgba(255,255,255,0.04)' }}>
              {['订单号', '顾客', '商品数', '总金额', '支付方式', '配送', '状态', '下单时间', '操作'].map(h => (
                <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: TEXT_3, fontWeight: 500, borderBottom: '1px solid rgba(255,255,255,0.06)' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map(o => (
              <tr key={o.id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '14px 16px', fontFamily: 'monospace', fontSize: 13, color: TEXT_2 }}>{o.id}</td>
                <td style={{ padding: '14px 16px' }}>
                  {o.customer_name} <span style={{ color: TEXT_4, fontSize: 12 }}>{o.customer_phone}</span>
                </td>
                <td style={{ padding: '14px 16px' }}>{o.item_count}</td>
                <td style={{ padding: '14px 16px', fontWeight: 600 }}>{fen(o.total_fen)}</td>
                <td style={{ padding: '14px 16px', color: TEXT_3 }}>{o.pay_method || '--'}</td>
                <td style={{ padding: '14px 16px' }}>
                  <span style={{
                    fontSize: 12, padding: '2px 8px', borderRadius: 4,
                    background: o.delivery_type === '快递' ? 'rgba(24,144,255,0.1)' : 'rgba(114,46,209,0.1)',
                    color: o.delivery_type === '快递' ? BLUE : PURPLE,
                  }}>{o.delivery_type}</span>
                </td>
                <td style={{ padding: '14px 16px' }}>
                  <span style={{
                    padding: '2px 10px', borderRadius: 12, fontSize: 12,
                    background: o.status === '已完成' ? 'rgba(82,196,26,0.15)' : o.status === '待发货' ? 'rgba(250,173,20,0.15)' : o.status === '已发货' ? 'rgba(24,144,255,0.15)' : o.status === '已取消' ? 'rgba(255,255,255,0.06)' : 'rgba(255,77,79,0.15)',
                    color: o.status === '已完成' ? GREEN : o.status === '待发货' ? YELLOW : o.status === '已发货' ? BLUE : o.status === '已取消' ? TEXT_4 : RED,
                  }}>{o.status}</span>
                </td>
                <td style={{ padding: '14px 16px', color: TEXT_3, fontSize: 13 }}>{o.created_at}</td>
                <td style={{ padding: '14px 16px' }}>
                  <span style={{ color: BLUE, cursor: 'pointer' }}>详情</span>
                  {o.status === '待发货' && (
                    <span onClick={() => handleShip(o.id)}
                      style={{ color: GREEN, cursor: 'pointer', marginLeft: 12 }}>
                      发货
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/* ─── 数据看板 Tab ─── */
function AnalyticsTab() {
  const [categoryData, setCategoryData] = useState<Array<{ name: string; sales: number; revenue: number }>>([]);
  const [metrics, setMetrics] = useState<Array<{ label: string; value: string; status: 'good' | 'normal' | 'bad' }>>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    txFetchData<{ categories: typeof categoryData; metrics: typeof metrics }>('/api/v1/analytics/retail/detail')
      .then(data => {
        setCategoryData(data.categories || []);
        setMetrics(data.metrics || []);
      })
      .catch(() => {
        setCategoryData([]);
        setMetrics([]);
      })
      .finally(() => setLoading(false));
  }, []);

  const maxRevenue = categoryData.length > 0 ? Math.max(...categoryData.map(d => d.revenue)) : 1;
  const barColors = [BRAND, BLUE, GREEN, PURPLE, YELLOW];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      {/* 分类销售排行 */}
      <div style={{ background: BG_2, borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>分类销售排行</h3>
        {loading && <div style={{ textAlign: 'center', padding: 40, color: TEXT_3 }}>加载中...</div>}
        {!loading && categoryData.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: TEXT_3 }}>暂无分类数据</div>
        )}
        {!loading && categoryData.map((d, i) => (
          <div key={d.name} style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 4 }}>
              <span style={{ color: TEXT_2 }}>
                <span style={{ color: i < 2 ? BRAND : TEXT_4, fontWeight: 700, marginRight: 6 }}>{i + 1}</span>
                {d.name}
              </span>
              <span style={{ fontWeight: 600 }}>{fen(d.revenue)}</span>
            </div>
            <div style={{ height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3 }}>
              <div style={{ width: `${(d.revenue / maxRevenue) * 100}%`, height: '100%', background: barColors[i % barColors.length], borderRadius: 3, transition: 'width 0.3s ease' }} />
            </div>
            <div style={{ fontSize: 11, color: TEXT_4, marginTop: 2 }}>{d.sales} 件售出</div>
          </div>
        ))}
      </div>

      {/* 运营指标 */}
      <div style={{ background: BG_2, borderRadius: 8, padding: 20 }}>
        <h3 style={{ margin: '0 0 16px', fontSize: 15, fontWeight: 600 }}>运营指标</h3>
        {loading && <div style={{ textAlign: 'center', padding: 40, color: TEXT_3 }}>加载中...</div>}
        {!loading && metrics.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: TEXT_3 }}>暂无指标数据</div>
        )}
        {!loading && metrics.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {metrics.map(m => (
              <div key={m.label} style={{ padding: 14, background: BG_3, borderRadius: 8 }}>
                <div style={{ fontSize: 12, color: TEXT_3 }}>{m.label}</div>
                <div style={{
                  fontSize: 22, fontWeight: 700, marginTop: 4,
                  color: m.status === 'good' ? GREEN : m.status === 'bad' ? RED : TEXT_1,
                }}>{m.value}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* GMV 趋势占位 */}
      <div style={{ background: BG_2, borderRadius: 8, padding: 20, gridColumn: '1 / -1' }}>
        <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 600 }}>GMV 趋势</h3>
        <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', color: TEXT_4, fontSize: 13 }}>
          图表接入中 — 数据已就绪，图表组件规划中
        </div>
      </div>
    </div>
  );
}
