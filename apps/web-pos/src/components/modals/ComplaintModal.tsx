/**
 * 客诉登记弹层 — 记录投诉 + 触发处理流程
 */
interface Props {
  visible: boolean;
  tableNo: string;
  onSubmit: (data: { type: string; description: string; severity: string }) => void;
  onClose: () => void;
}

const COMPLAINT_TYPES = [
  { key: 'food_quality', label: '菜品质量', icon: '🍽️' },
  { key: 'service', label: '服务态度', icon: '😤' },
  { key: 'wait_time', label: '等待太久', icon: '⏰' },
  { key: 'hygiene', label: '卫生问题', icon: '🧹' },
  { key: 'billing', label: '账单问题', icon: '💰' },
  { key: 'other', label: '其他', icon: '📝' },
];

export function ComplaintModal({ visible, tableNo, onSubmit, onClose }: Props) {
  if (!visible) return null;

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ width: 420, background: '#112228', borderRadius: 12, padding: 24, border: '2px solid #ff4d4f' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>😤</span>
          <h3 style={{ margin: 0, color: '#ff4d4f' }}>客诉登记 · {tableNo}</h3>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
          {COMPLAINT_TYPES.map(t => (
            <label key={t.key} style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', padding: 10, borderRadius: 8,
              background: '#0B1A20', border: '1px solid #333', cursor: 'pointer', fontSize: 12,
            }}>
              <input type="radio" name="complaint-type" value={t.key} style={{ display: 'none' }} />
              <span style={{ fontSize: 20 }}>{t.icon}</span>
              {t.label}
            </label>
          ))}
        </div>

        <textarea placeholder="详细描述..." style={{
          width: '100%', height: 80, padding: 8, borderRadius: 6, border: '1px solid #333',
          background: '#0B1A20', color: '#fff', fontSize: 13, resize: 'none', marginBottom: 12,
        }} id="complaint-desc" />

        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onClose} style={{ flex: 1, padding: 10, background: '#333', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>取消</button>
          <button onClick={() => onSubmit({
            type: (document.querySelector('input[name="complaint-type"]:checked') as HTMLInputElement)?.value || 'other',
            description: (document.getElementById('complaint-desc') as HTMLTextAreaElement)?.value || '',
            severity: 'high',
          })} style={{ flex: 1, padding: 10, background: '#ff4d4f', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>
            提交客诉
          </button>
        </div>
      </div>
    </div>
  );
}
