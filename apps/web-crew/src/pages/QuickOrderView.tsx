/**
 * 快速点餐入口 — 底部Tab"点餐"
 * 两种方式开始点餐：扫码直接开台 / 从在座桌台列表加菜
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { TXButton, TXCard } from '@tx/touch';
import { fetchActiveOrders, type ActiveOrder } from '../api/index';

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  muted: '#5F5E5A',
  text: '#E2EAE8',
  white: '#FFFFFF',
  green: '#0F6E56',
};

export function QuickOrderView() {
  const navigate = useNavigate();
  const storeId = (window as any).__STORE_ID__ || 'store_001';

  const [orders, setOrders] = useState<ActiveOrder[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    fetchActiveOrders(storeId)
      .then(res => setOrders(res.items))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [storeId]);

  useEffect(() => { load(); }, [load]);

  const handleScan = () => {
    if ((window as any).TXBridge) {
      (window as any).TXBridge.scan();
      (window as any).TXBridge.onScanResult = (result: string) => {
        // 解析 txos://table/store_001/A01 或直接 A01
        let tableNo = '';
        if (result.startsWith('txos://table/')) {
          tableNo = result.split('/').pop() || '';
        } else if (/^[A-Za-z0-9]{2,6}$/.test(result.trim())) {
          tableNo = result.trim().toUpperCase();
        }
        if (tableNo) navigate(`/open-table?table=${encodeURIComponent(tableNo)}&prefilled=true`);
      };
    } else {
      const mock = prompt('开发模式 - 输入桌台号（如 A01）:');
      if (mock) navigate(`/open-table?table=${encodeURIComponent(mock.trim().toUpperCase())}&prefilled=true`);
    }
  };

  return (
    <div style={{ background: C.bg, minHeight: '100vh', paddingBottom: 80 }}>
      {/* 标题 */}
      <div style={{ padding: '20px 16px 12px' }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: C.white }}>点餐</h2>
        <p style={{ margin: '4px 0 0', fontSize: 16, color: C.muted }}>扫码开台或为在座桌台加菜</p>
      </div>

      {/* 扫码开台 大按钮 */}
      <div style={{ padding: '0 16px 20px' }}>
        {/* TXButton large fullwidth — 主操作，单手拇指底部区域 */}
        <TXButton
          variant="primary"
          size="large"
          icon={<span style={{ fontSize: 28 }}>📷</span>}
          onPress={handleScan}
          style={{ width: '100%', letterSpacing: 1, fontSize: 20 }}
        >
          扫码开台
        </TXButton>

        {/* TXButton secondary fullwidth — 手动开台 */}
        <TXButton
          variant="secondary"
          size="normal"
          onPress={() => navigate('/open-table')}
          style={{ width: '100%', marginTop: 10, fontSize: 18 }}
        >
          手动选台开台
        </TXButton>
      </div>

      {/* 在座桌台 加菜区 */}
      <div style={{ padding: '0 16px' }}>
        <div style={{ fontSize: 17, fontWeight: 600, color: C.text, marginBottom: 12 }}>
          在座桌台 — 快速加菜
        </div>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 32, color: C.muted, fontSize: 16 }}>加载中...</div>
        ) : orders.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: 32, color: C.muted, fontSize: 16,
            background: C.card, borderRadius: 12, border: `1px solid ${C.border}`,
          }}>
            暂无在座桌台
          </div>
        ) : (
          orders.map(order => {
            const elapsedMin = Math.floor(
              (Date.now() - new Date(order.created_at).getTime()) / 60000
            );
            return (
              /* TXCard — 在座桌台加菜卡片，触控按压反馈 */
              <TXCard
                key={order.order_id}
                onPress={() => navigate(`/order-full?table=${encodeURIComponent(order.table_no)}&order_id=${encodeURIComponent(order.order_id)}&guests=0`)}
                style={{
                  padding: 16,
                  marginBottom: 10,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  background: C.card,
                }}
              >
                <div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: C.white }}>{order.table_no} 桌</div>
                  <div style={{ fontSize: 16, color: C.muted, marginTop: 4 }}>
                    {order.item_count} 道 · ¥{(order.total_fen / 100).toFixed(0)} · {elapsedMin}分钟
                  </div>
                </div>
                {/* TXButton — 加菜，min-height 56px (TXButton normal) */}
                <TXButton
                  variant="secondary"
                  size="normal"
                  onPress={() => navigate(`/order-full?table=${encodeURIComponent(order.table_no)}&order_id=${encodeURIComponent(order.order_id)}&guests=0`)}
                  style={{ minWidth: 72, padding: '0 12px', fontSize: 16 }}
                >
                  加菜
                </TXButton>
              </TXCard>
            );
          })
        )}
      </div>
    </div>
  );
}
