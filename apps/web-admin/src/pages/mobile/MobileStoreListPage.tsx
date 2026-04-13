/**
 * 移动端门店列表
 * 路由: /m/stores
 * API: tx-analytics :8009 /api/v1/analytics/store-list
 *
 * 功能：
 * - 门店卡片列表（名称/状态/今日营业额）
 * - 点击进入门店详情（桌态页面）
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { MobileLayout } from '../../components/MobileLayout';
import { txFetchData } from '../../api/client';
import { formatPrice } from '@tx-ds/utils';

// ─── 类型 ───

interface StoreItem {
  store_id: string;
  store_name: string;
  address: string;
  online: boolean;
  today_revenue_fen: number;
  today_customer_count: number;
  today_order_count: number;
  table_total: number;
  table_occupied: number;
}

// ─── Mock 数据 ───

const MOCK_STORES: StoreItem[] = [
  {
    store_id: 's1',
    store_name: '五一广场店',
    address: '长沙市芙蓉区五一大道128号',
    online: true,
    today_revenue_fen: 528000,
    today_customer_count: 68,
    today_order_count: 42,
    table_total: 20,
    table_occupied: 12,
  },
  {
    store_id: 's2',
    store_name: '解放西路店',
    address: '长沙市天心区解放西路256号',
    online: true,
    today_revenue_fen: 412000,
    today_customer_count: 55,
    today_order_count: 38,
    table_total: 16,
    table_occupied: 9,
  },
  {
    store_id: 's3',
    store_name: '湘江新区店',
    address: '长沙市岳麓区梅溪湖路88号',
    online: false,
    today_revenue_fen: 0,
    today_customer_count: 0,
    today_order_count: 0,
    table_total: 24,
    table_occupied: 0,
  },
  {
    store_id: 's4',
    store_name: '梅溪湖店',
    address: '长沙市岳麓区梅溪湖环路168号',
    online: true,
    today_revenue_fen: 318000,
    today_customer_count: 33,
    today_order_count: 25,
    table_total: 14,
    table_occupied: 6,
  },
];

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
const fen2yuan = (fen: number) =>
  (fen / 100).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 0 });

// ─── 门店卡片 ───

function StoreCard({ store, onClick }: { store: StoreItem; onClick: () => void }) {
  const occupancyPct = store.table_total > 0
    ? Math.round((store.table_occupied / store.table_total) * 100)
    : 0;

  return (
    <button
      onClick={onClick}
      style={{
        background: '#fff',
        borderRadius: 12,
        padding: 16,
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
        border: 'none',
        cursor: 'pointer',
        textAlign: 'left',
        width: '100%',
        transition: 'transform 0.15s',
      }}
    >
      {/* 头部：名称 + 状态 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 10,
            height: 10,
            borderRadius: '50%',
            background: store.online ? '#0F6E56' : '#B4B2A9',
            flexShrink: 0,
            boxShadow: store.online ? '0 0 6px rgba(15,110,86,0.4)' : 'none',
          }} />
          <span style={{ fontSize: 16, fontWeight: 600, color: '#2C2C2A' }}>
            {store.store_name}
          </span>
        </div>
        <span style={{
          fontSize: 11,
          fontWeight: 600,
          color: store.online ? '#0F6E56' : '#B4B2A9',
          background: store.online ? '#ECFDF5' : '#F0EDE6',
          padding: '3px 8px',
          borderRadius: 10,
        }}>
          {store.online ? '营业中' : '离线'}
        </span>
      </div>

      {/* 地址 */}
      <div style={{ fontSize: 12, color: '#B4B2A9', marginBottom: 12 }}>
        {store.address}
      </div>

      {/* 今日营业额 */}
      <div style={{
        fontSize: 24,
        fontWeight: 700,
        color: store.online ? '#FF6B35' : '#B4B2A9',
        marginBottom: 12,
        lineHeight: 1.1,
      }}>
        <span style={{ fontSize: 15, fontWeight: 600 }}>¥</span>
        {fen2yuan(store.today_revenue_fen)}
      </div>

      {/* 底部指标 */}
      <div style={{
        display: 'flex',
        gap: 0,
        borderTop: '1px solid #F0EDE6',
        paddingTop: 10,
      }}>
        {[
          { label: '客流', value: `${store.today_customer_count}人` },
          { label: '订单', value: `${store.today_order_count}单` },
          { label: '上座率', value: `${occupancyPct}%` },
        ].map((item, idx) => (
          <div key={item.label} style={{
            flex: 1,
            textAlign: 'center',
            borderRight: idx < 2 ? '1px solid #F0EDE6' : 'none',
          }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: store.online ? '#2C2C2A' : '#B4B2A9' }}>
              {item.value}
            </div>
            <div style={{ fontSize: 11, color: '#B4B2A9', marginTop: 2 }}>{item.label}</div>
          </div>
        ))}
      </div>
    </button>
  );
}

// ─── 主组件 ───

export function MobileStoreListPage() {
  const navigate = useNavigate();
  const [stores, setStores] = useState<StoreItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'online' | 'offline'>('all');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    txFetchData<StoreItem[]>('/api/v1/analytics/store-list')
      .then(res => {
        if (!cancelled) setStores(res.data ?? MOCK_STORES);
      })
      .catch(() => {
        if (!cancelled) setStores(MOCK_STORES);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  const filtered = stores.filter(s => {
    if (filter === 'online') return s.online;
    if (filter === 'offline') return !s.online;
    return true;
  });

  const onlineCount = stores.filter(s => s.online).length;
  const offlineCount = stores.filter(s => !s.online).length;

  return (
    <MobileLayout title="门店管理">
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>

        {/* 汇总 */}
        <div style={{
          display: 'flex',
          gap: 8,
          background: '#fff',
          borderRadius: 10,
          padding: '12px 14px',
          boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
        }}>
          <div style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#2C2C2A' }}>{stores.length}</div>
            <div style={{ fontSize: 11, color: '#B4B2A9' }}>全部门店</div>
          </div>
          <div style={{ width: 1, background: '#F0EDE6' }} />
          <div style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#0F6E56' }}>{onlineCount}</div>
            <div style={{ fontSize: 11, color: '#B4B2A9' }}>在线</div>
          </div>
          <div style={{ width: 1, background: '#F0EDE6' }} />
          <div style={{ flex: 1, textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 700, color: offlineCount > 0 ? '#A32D2D' : '#B4B2A9' }}>{offlineCount}</div>
            <div style={{ fontSize: 11, color: '#B4B2A9' }}>离线</div>
          </div>
        </div>

        {/* 筛选条 */}
        <div style={{ display: 'flex', gap: 8 }}>
          {([
            { key: 'all', label: '全部' },
            { key: 'online', label: '在线' },
            { key: 'offline', label: '离线' },
          ] as const).map(opt => {
            const isActive = filter === opt.key;
            return (
              <button
                key={opt.key}
                onClick={() => setFilter(opt.key)}
                style={{
                  flex: 1,
                  padding: '8px 0',
                  border: 'none',
                  borderRadius: 8,
                  background: isActive ? '#FF6B35' : '#fff',
                  color: isActive ? '#fff' : '#5F5E5A',
                  fontSize: 13,
                  fontWeight: isActive ? 600 : 400,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                  boxShadow: isActive ? 'none' : '0 1px 2px rgba(0,0,0,0.05)',
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>

        {/* 门店列表 */}
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[1, 2, 3].map(i => (
              <div key={i} style={{
                height: 160,
                background: '#E8E6E1',
                borderRadius: 12,
                animation: 'pulse 1.5s ease-in-out infinite',
              }} />
            ))}
            <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }`}</style>
          </div>
        ) : filtered.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {filtered.map(store => (
              <StoreCard
                key={store.store_id}
                store={store}
                onClick={() => navigate(`/m/tables?store=${store.store_id}`)}
              />
            ))}
          </div>
        ) : (
          <div style={{
            textAlign: 'center',
            padding: '40px 0',
            color: '#B4B2A9',
            fontSize: 14,
          }}>
            暂无{filter === 'online' ? '在线' : filter === 'offline' ? '离线' : ''}门店
          </div>
        )}

        {/* 底部留白 */}
        <div style={{ height: 8 }} />
      </div>
    </MobileLayout>
  );
}
