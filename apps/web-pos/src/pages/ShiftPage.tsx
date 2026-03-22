/**
 * 交接班页面 — 营业额汇总 + 现金盘点
 */
import { useNavigate } from 'react-router-dom';

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

export function ShiftPage() {
  const navigate = useNavigate();

  // TODO: 从 tx-trade API 加载当班数据
  const shiftData = {
    totalOrders: 42,
    totalRevenueFen: 856000,
    cashFen: 125000,
    wechatFen: 480000,
    alipayFen: 210000,
    unionpayFen: 41000,
    refundFen: 8800,
    avgPerGuestFen: 6800,
    totalGuests: 126,
  };

  return (
    <div style={{ padding: 24, background: '#0B1A20', minHeight: '100vh', color: '#fff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 24 }}>
        <h2 style={{ margin: 0 }}>交接班</h2>
        <button
          onClick={() => navigate('/tables')}
          style={{ padding: '8px 16px', background: '#333', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }}
        >
          返回
        </button>
      </div>

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 24 }}>
        {[
          { label: '总单数', value: `${shiftData.totalOrders} 单` },
          { label: '总营收', value: fen2yuan(shiftData.totalRevenueFen) },
          { label: '客流', value: `${shiftData.totalGuests} 人` },
          { label: '客单价', value: fen2yuan(shiftData.avgPerGuestFen) },
        ].map((kpi) => (
          <div key={kpi.label} style={{ padding: 16, background: '#112228', borderRadius: 8, textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: '#999' }}>{kpi.label}</div>
            <div style={{ fontSize: 24, fontWeight: 'bold', color: '#FF6B2C', marginTop: 4 }}>{kpi.value}</div>
          </div>
        ))}
      </div>

      {/* 支付方式明细 */}
      <h3>支付方式明细</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 24 }}>
        <tbody>
          {[
            { label: '微信支付', fen: shiftData.wechatFen, color: '#07C160' },
            { label: '支付宝', fen: shiftData.alipayFen, color: '#1677FF' },
            { label: '现金', fen: shiftData.cashFen, color: '#faad14' },
            { label: '银联', fen: shiftData.unionpayFen, color: '#e6002d' },
            { label: '退款', fen: -shiftData.refundFen, color: '#ff4d4f' },
          ].map((row) => (
            <tr key={row.label} style={{ borderBottom: '1px solid #1a2a33' }}>
              <td style={{ padding: 12 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: row.color, display: 'inline-block', marginRight: 8 }} />
                {row.label}
              </td>
              <td style={{ padding: 12, textAlign: 'right', fontWeight: 'bold' }}>
                {row.fen < 0 ? `-${fen2yuan(-row.fen)}` : fen2yuan(row.fen)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* 现金盘点 */}
      <h3>现金盘点</h3>
      <div style={{ background: '#112228', padding: 16, borderRadius: 8, marginBottom: 24 }}>
        <div style={{ marginBottom: 12 }}>
          应有现金: <strong>{fen2yuan(shiftData.cashFen)}</strong>
        </div>
        <div>
          <label>实际现金: </label>
          <input
            type="number"
            placeholder="输入实际金额（元）"
            style={{ padding: 8, background: '#1a2a33', border: '1px solid #333', borderRadius: 4, color: '#fff', width: 200 }}
          />
        </div>
      </div>

      {/* 确认交接 */}
      <button
        onClick={() => {
          alert('交接班完成！');
          navigate('/tables');
        }}
        style={{
          padding: '12px 48px', background: '#FF6B2C', color: '#fff',
          border: 'none', borderRadius: 8, fontSize: 18, cursor: 'pointer',
        }}
      >
        确认交接班
      </button>
    </div>
  );
}
