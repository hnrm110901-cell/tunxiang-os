/**
 * 缺料上报弹层 — 食材缺货时触发紧急采购
 */
interface Props {
  visible: boolean;
  ingredientName: string;
  currentStock: number;
  unit: string;
  onSubmit: (urgency: string, quantity: number) => void;
  onClose: () => void;
}

export function ShortageReportModal({ visible, ingredientName, currentStock, unit, onSubmit, onClose }: Props) {
  if (!visible) return null;

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ width: 380, background: '#112228', borderRadius: 12, padding: 24, border: '2px solid #faad14' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
          <span style={{ fontSize: 24 }}>📦</span>
          <h3 style={{ margin: 0, color: '#faad14' }}>缺料上报</h3>
        </div>

        <div style={{ fontSize: 13, color: '#ccc', lineHeight: 1.8, marginBottom: 16 }}>
          <div>食材：<b style={{ color: '#FF6B2C' }}>{ingredientName}</b></div>
          <div>当前库存：<b style={{ color: currentStock <= 0 ? '#ff4d4f' : '#faad14' }}>{currentStock} {unit}</b></div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: '#999' }}>补货数量 ({unit})</label>
          <input type="number" defaultValue={10} id="shortage-qty" style={{
            width: '100%', padding: 8, marginTop: 4, borderRadius: 6, border: '1px solid #333',
            background: '#0B1A20', color: '#fff', fontSize: 14,
          }} />
        </div>

        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={onClose} style={{ flex: 1, padding: 10, background: '#333', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>取消</button>
          <button onClick={() => onSubmit('urgent', Number((document.getElementById('shortage-qty') as HTMLInputElement)?.value || 10))}
            style={{ flex: 1, padding: 10, background: '#ff4d4f', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>
            🚨 紧急采购
          </button>
          <button onClick={() => onSubmit('normal', Number((document.getElementById('shortage-qty') as HTMLInputElement)?.value || 10))}
            style={{ flex: 1, padding: 10, background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 8, cursor: 'pointer' }}>
            常规补货
          </button>
        </div>
      </div>
    </div>
  );
}
