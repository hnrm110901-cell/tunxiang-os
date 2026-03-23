/**
 * KDS 档口配置 — 档口列表 + 新增/编辑
 * 大字号设计，厨房友好
 */
import { useState } from 'react';

/* ---------- Types ---------- */
interface Stall {
  id: string;
  name: string;
  dishCount: number;
  printer: string;
  status: 'online' | 'offline';
}

/* ---------- Mock Data ---------- */
const initialStalls: Stall[] = [
  { id: '1', name: '热菜档口', dishCount: 28, printer: '热菜出品机 (192.168.1.102)', status: 'online' },
  { id: '2', name: '凉菜档口', dishCount: 12, printer: '凉菜出品机 (192.168.1.103)', status: 'online' },
  { id: '3', name: '主食档口', dishCount: 8, printer: '主食出品机 (192.168.1.104)', status: 'online' },
  { id: '4', name: '蒸菜档口', dishCount: 15, printer: '蒸菜出品机 (192.168.1.105)', status: 'offline' },
];

/* ---------- Component ---------- */
export function KDSConfigPage() {
  const [stalls, setStalls] = useState(initialStalls);
  const [editing, setEditing] = useState<Stall | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [formPrinter, setFormPrinter] = useState('');

  const openAdd = () => {
    setEditing(null);
    setFormName('');
    setFormPrinter('');
    setShowForm(true);
  };

  const openEdit = (stall: Stall) => {
    setEditing(stall);
    setFormName(stall.name);
    setFormPrinter(stall.printer);
    setShowForm(true);
  };

  const handleSave = () => {
    if (!formName.trim()) return;
    if (editing) {
      setStalls(prev => prev.map(s =>
        s.id === editing.id ? { ...s, name: formName, printer: formPrinter } : s
      ));
    } else {
      setStalls(prev => [...prev, {
        id: Date.now().toString(),
        name: formName,
        dishCount: 0,
        printer: formPrinter || '未配置',
        status: 'offline',
      }]);
    }
    setShowForm(false);
  };

  const handleDelete = (id: string) => {
    setStalls(prev => prev.filter(s => s.id !== id));
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', boxSizing: 'border-box', padding: '12px 14px',
    background: '#1A3A48', color: '#fff', border: '1px solid #2A4A58',
    borderRadius: 6, fontSize: 18,
  };

  return (
    <div style={{
      background: '#0B1A20', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: 'Noto Sans SC, sans-serif', padding: 16,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#fff' }}>档口配置</h1>
        <button onClick={openAdd} style={{
          padding: '10px 24px', background: '#52c41a', color: '#fff',
          border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 18, fontWeight: 'bold',
        }}>
          + 新增档口
        </button>
      </div>

      {/* Stall List */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 14 }}>
        {stalls.map(stall => (
          <div key={stall.id} style={{
            background: '#112B36', borderRadius: 12, padding: 20,
            borderLeft: `5px solid ${stall.status === 'online' ? '#52c41a' : '#ff4d4f'}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontSize: 24, fontWeight: 'bold', color: '#fff' }}>{stall.name}</span>
              <span style={{
                fontSize: 14, padding: '4px 10px', borderRadius: 4,
                background: stall.status === 'online' ? '#52c41a22' : '#ff4d4f22',
                color: stall.status === 'online' ? '#52c41a' : '#ff4d4f',
              }}>
                {stall.status === 'online' ? '在线' : '离线'}
              </span>
            </div>

            <div style={{ fontSize: 16, color: '#8899A6', marginBottom: 8 }}>
              关联菜品: <span style={{ color: '#E0C97F', fontWeight: 'bold' }}>{stall.dishCount}</span> 道
            </div>

            <div style={{ fontSize: 14, color: '#666', marginBottom: 14 }}>
              打印机: {stall.printer}
            </div>

            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => openEdit(stall)} style={{
                flex: 1, padding: '8px 0', background: '#1A3A48', color: '#1890ff',
                border: '1px solid #1890ff', borderRadius: 6, cursor: 'pointer', fontSize: 16,
              }}>
                编辑
              </button>
              <button onClick={() => handleDelete(stall.id)} style={{
                flex: 1, padding: '8px 0', background: '#1A3A48', color: '#ff4d4f',
                border: '1px solid #ff4d4f', borderRadius: 6, cursor: 'pointer', fontSize: 16,
              }}>
                删除
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Edit/Add Modal */}
      {showForm && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{ background: '#112B36', borderRadius: 12, padding: 28, width: 420 }}>
            <h2 style={{ margin: '0 0 20px', fontSize: 24, color: '#fff' }}>
              {editing ? '编辑档口' : '新增档口'}
            </h2>

            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 16, color: '#8899A6', marginBottom: 6 }}>档口名称</label>
              <input
                value={formName}
                onChange={e => setFormName(e.target.value)}
                placeholder="如：热菜档口"
                style={inputStyle}
              />
            </div>

            <div style={{ marginBottom: 24 }}>
              <label style={{ display: 'block', fontSize: 16, color: '#8899A6', marginBottom: 6 }}>关联打印机</label>
              <input
                value={formPrinter}
                onChange={e => setFormPrinter(e.target.value)}
                placeholder="如：热菜出品机 (192.168.1.102)"
                style={inputStyle}
              />
            </div>

            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={handleSave} style={{
                flex: 1, padding: '12px 0', background: '#1890ff', color: '#fff',
                border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 18, fontWeight: 'bold',
              }}>
                保存
              </button>
              <button onClick={() => setShowForm(false)} style={{
                flex: 1, padding: '12px 0', background: '#1A3A48', color: '#aaa',
                border: 'none', borderRadius: 8, cursor: 'pointer', fontSize: 18,
              }}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
