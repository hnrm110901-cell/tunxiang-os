/**
 * 结算页面 — 对接 tx-trade 支付 API + 打印
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import { settleOrder, createPayment, printReceipt as apiPrintReceipt } from '../api/tradeApi';
import { printReceipt as bridgePrint, openCashBox } from '../bridge/TXBridge';

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

const PAYMENT_METHODS = [
  { key: 'wechat', label: '微信支付', color: '#07C160' },
  { key: 'alipay', label: '支付宝', color: '#1677FF' },
  { key: 'cash', label: '现金', color: '#faad14' },
  { key: 'unionpay', label: '银联刷卡', color: '#e6002d' },
  { key: 'credit_account', label: '挂账', color: '#722ed1' },
  { key: 'member_balance', label: '会员余额', color: '#13c2c2' },
];

export function SettlePage() {
  const navigate = useNavigate();
  const { items, totalFen, discountFen, tableNo, orderId, clear } = useOrderStore();
  const finalFen = totalFen - discountFen;
  const [paying, setPaying] = useState(false);

  const handlePay = async (method: string) => {
    if (paying) return;
    setPaying(true);

    try {
      // 1. 创建支付记录
      if (orderId) {
        await createPayment(orderId, method, finalFen);
      }

      // 2. 结算订单
      if (orderId) {
        await settleOrder(orderId);
      }

      // 3. 打印小票
      if (orderId) {
        try {
          const { content_base64 } = await apiPrintReceipt(orderId);
          await bridgePrint(content_base64);
        } catch {
          // 打印失败不阻断结算
        }
      }

      // 4. 现金弹钱箱
      if (method === 'cash') {
        try { await openCashBox(); } catch { /* ignore */ }
      }

      clear();
      navigate('/tables');
    } catch (e) {
      alert(`支付失败: ${e instanceof Error ? e.message : '未知错误'}`);
    } finally {
      setPaying(false);
    }
  };

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左侧 — 订单摘要 */}
      <div style={{ flex: 1, padding: 24, overflowY: 'auto' }}>
        <h2>结算 · 桌号 {tableNo}</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #333', textAlign: 'left' }}>
              <th style={{ padding: 8 }}>菜品</th>
              <th style={{ padding: 8 }}>数量</th>
              <th style={{ padding: 8, textAlign: 'right' }}>小计</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} style={{ borderBottom: '1px solid #1a2a33' }}>
                <td style={{ padding: 8 }}>{item.name}</td>
                <td style={{ padding: 8 }}>×{item.quantity}</td>
                <td style={{ padding: 8, textAlign: 'right' }}>{fen2yuan(item.priceFen * item.quantity)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 16, fontSize: 24, fontWeight: 'bold', color: '#FF6B2C', textAlign: 'right' }}>
          应付: {fen2yuan(finalFen)}
        </div>
      </div>

      {/* 右侧 — 支付方式 */}
      <div style={{ width: 320, background: '#112228', padding: 24, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <h3>选择支付方式</h3>
        {PAYMENT_METHODS.map((m) => (
          <button
            key={m.key}
            onClick={() => handlePay(m.key)}
            disabled={paying}
            style={{
              padding: 16, border: 'none', borderRadius: 8,
              background: paying ? '#444' : m.color, color: '#fff', fontSize: 18,
              cursor: paying ? 'not-allowed' : 'pointer',
            }}
          >
            {paying ? '处理中...' : m.label}
          </button>
        ))}
        <button
          onClick={() => navigate(-1)}
          style={{ padding: 12, border: '1px solid #444', borderRadius: 8, background: 'transparent', color: '#999', cursor: 'pointer', marginTop: 'auto' }}
        >
          返回修改
        </button>
      </div>
    </div>
  );
}
