/**
 * 结算页面 — 支付方式选择 + 打印
 */
import { useNavigate } from 'react-router-dom';
import { useOrderStore } from '../store/orderStore';
import { printReceipt, openCashBox } from '../bridge/TXBridge';

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
  const { items, totalFen, discountFen, tableNo, clear } = useOrderStore();
  const finalFen = totalFen - discountFen;

  const handlePay = async (method: string) => {
    // TODO: 调用 PaymentService API
    alert(`支付方式: ${method}\n金额: ${fen2yuan(finalFen)}\n支付成功！`);

    // 打印小票
    try {
      await printReceipt(`[收银小票]\n桌号: ${tableNo}\n金额: ${fen2yuan(finalFen)}`);
    } catch (e) {
      console.error('打印失败', e);
    }

    // 现金支付弹钱箱
    if (method === 'cash') {
      try { await openCashBox(); } catch (e) { /* ignore */ }
    }

    clear();
    navigate('/tables');
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
            style={{
              padding: 16, border: 'none', borderRadius: 8,
              background: m.color, color: '#fff', fontSize: 18,
              cursor: 'pointer',
            }}
          >
            {m.label}
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
