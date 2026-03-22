/**
 * 预订排队台账 — 双栏布局
 * 左：预订列表（按时段分组） 右：详情/新建
 */
import { useState } from 'react';

const MOCK_RESERVATIONS = [
  { id: '1', name: '张总', phone: '138****0001', guests: 6, time: '11:30', table: 'B01', status: 'confirmed' },
  { id: '2', name: '李经理', phone: '139****0002', guests: 4, time: '12:00', table: '', status: 'pending' },
  { id: '3', name: '王女士', phone: '137****0003', guests: 8, time: '17:30', table: 'B02', status: 'confirmed' },
  { id: '4', name: '赵先生', phone: '136****0004', guests: 2, time: '18:00', table: '', status: 'pending' },
  { id: '5', name: '刘总 (宴请)', phone: '135****0005', guests: 20, time: '18:30', table: 'B03', status: 'confirmed' },
];

const statusMap: Record<string, { label: string; color: string }> = {
  pending: { label: '待确认', color: '#faad14' },
  confirmed: { label: '已确认', color: '#52c41a' },
  seated: { label: '已就座', color: '#1890ff' },
  cancelled: { label: '已取消', color: '#ff4d4f' },
  no_show: { label: '爽约', color: '#999' },
};

export function ReservationPage() {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#0B1A20', color: '#fff' }}>
      {/* 左：预订列表 */}
      <div style={{ flex: 1, padding: 16, overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
          <h3 style={{ margin: 0 }}>预订台账</h3>
          <button style={{ padding: '6px 16px', background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
            + 新增预订
          </button>
        </div>

        {/* 午市 */}
        <div style={{ fontSize: 11, color: '#999', padding: '8px 0 4px', borderBottom: '1px solid #1a2a33' }}>午市 (11:00-14:00)</div>
        {MOCK_RESERVATIONS.filter(r => parseInt(r.time) < 15).map(r => (
          <ReservationRow key={r.id} r={r} selected={selected === r.id} onSelect={() => setSelected(r.id)} />
        ))}

        {/* 晚市 */}
        <div style={{ fontSize: 11, color: '#999', padding: '12px 0 4px', borderBottom: '1px solid #1a2a33' }}>晚市 (17:00-21:00)</div>
        {MOCK_RESERVATIONS.filter(r => parseInt(r.time) >= 15).map(r => (
          <ReservationRow key={r.id} r={r} selected={selected === r.id} onSelect={() => setSelected(r.id)} />
        ))}
      </div>

      {/* 右：详情 */}
      <div style={{ width: 320, background: '#112228', padding: 16, borderLeft: '1px solid #1a2a33' }}>
        {selected ? (
          <div>
            <h4 style={{ margin: '0 0 12px' }}>预订详情</h4>
            {(() => {
              const r = MOCK_RESERVATIONS.find(x => x.id === selected);
              if (!r) return null;
              const s = statusMap[r.status];
              return (
                <div>
                  <div style={{ fontSize: 20, fontWeight: 'bold', marginBottom: 8 }}>{r.name}</div>
                  <div style={{ color: '#999', marginBottom: 4 }}>{r.phone}</div>
                  <div style={{ marginBottom: 4 }}>{r.guests} 人 · {r.time} · {r.table || '待分桌'}</div>
                  <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, background: s.color + '22', color: s.color }}>{s.label}</span>
                  <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
                    <button style={{ flex: 1, padding: 8, background: '#52c41a', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>确认</button>
                    <button style={{ flex: 1, padding: 8, background: '#333', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>取消</button>
                  </div>
                </div>
              );
            })()}
          </div>
        ) : (
          <div style={{ color: '#666', textAlign: 'center', marginTop: 40 }}>选择预订查看详情</div>
        )}
      </div>
    </div>
  );
}

function ReservationRow({ r, selected, onSelect }: { r: any; selected: boolean; onSelect: () => void }) {
  const s = statusMap[r.status];
  return (
    <div onClick={onSelect} style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '10px 8px', cursor: 'pointer', borderRadius: 6,
      background: selected ? '#1a2a33' : 'transparent',
      borderBottom: '1px solid #112228',
    }}>
      <div>
        <div style={{ fontWeight: 'bold' }}>{r.name} <span style={{ fontWeight: 'normal', color: '#999' }}>({r.guests}人)</span></div>
        <div style={{ fontSize: 12, color: '#666' }}>{r.time} · {r.table || '待分桌'}</div>
      </div>
      <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 10, background: s.color + '22', color: s.color }}>{s.label}</span>
    </div>
  );
}
