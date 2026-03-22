/**
 * 异常中心 — 投诉/退菜/设备故障/缺料 集中处理
 */

const MOCK_EXCEPTIONS = [
  { id: '1', type: 'complaint', title: '客诉: A03桌菜品太咸', severity: 'high', time: '14:25', status: 'pending', table: 'A03' },
  { id: '2', type: 'return_dish', title: '退菜: 口味虾（不新鲜）', severity: 'high', time: '14:10', status: 'processing', table: 'B01' },
  { id: '3', type: 'equipment', title: '2号打印机卡纸', severity: 'medium', time: '13:50', status: 'resolved' },
  { id: '4', type: 'shortage', title: '鲈鱼库存不足(仅剩2kg)', severity: 'high', time: '13:30', status: 'pending' },
  { id: '5', type: 'discount', title: '异常折扣: A05桌 折扣率65%', severity: 'critical', time: '14:30', status: 'pending', table: 'A05' },
];

const typeIcon: Record<string, string> = { complaint: '😤', return_dish: '↩️', equipment: '🔧', shortage: '📦', discount: '💰' };
const severityColor: Record<string, string> = { critical: '#ff4d4f', high: '#faad14', medium: '#1890ff', low: '#52c41a' };
const statusLabel: Record<string, string> = { pending: '待处理', processing: '处理中', resolved: '已解决' };

export function ExceptionPage() {
  const pending = MOCK_EXCEPTIONS.filter(e => e.status === 'pending');
  const processing = MOCK_EXCEPTIONS.filter(e => e.status === 'processing');
  const resolved = MOCK_EXCEPTIONS.filter(e => e.status === 'resolved');

  return (
    <div style={{ padding: 16, background: '#0B1A20', minHeight: '100vh', color: '#fff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={{ margin: 0 }}>异常中心</h3>
        <div style={{ display: 'flex', gap: 12, fontSize: 13 }}>
          <span style={{ color: '#ff4d4f' }}>待处理 {pending.length}</span>
          <span style={{ color: '#faad14' }}>处理中 {processing.length}</span>
          <span style={{ color: '#52c41a' }}>已解决 {resolved.length}</span>
        </div>
      </div>

      {MOCK_EXCEPTIONS.map(e => (
        <div key={e.id} style={{
          padding: 14, marginBottom: 8, borderRadius: 8, background: '#112228',
          borderLeft: `4px solid ${severityColor[e.severity]}`,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 24 }}>{typeIcon[e.type]}</span>
            <div>
              <div style={{ fontWeight: 'bold' }}>{e.title}</div>
              <div style={{ fontSize: 12, color: '#666' }}>{e.time} {e.table ? `· ${e.table}` : ''}</div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              padding: '3px 10px', borderRadius: 10, fontSize: 11,
              background: e.status === 'pending' ? '#ff4d4f22' : e.status === 'processing' ? '#faad1422' : '#52c41a22',
              color: e.status === 'pending' ? '#ff4d4f' : e.status === 'processing' ? '#faad14' : '#52c41a',
            }}>
              {statusLabel[e.status]}
            </span>
            {e.status === 'pending' && (
              <button style={{ padding: '4px 12px', background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12 }}>
                处理
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
