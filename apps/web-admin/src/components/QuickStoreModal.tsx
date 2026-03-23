/**
 * 快速开店弹窗 — 品智借鉴 P0-1
 * 3步向导：选门店 → 选配置 → 完成
 */
import { useState } from 'react';

interface Props {
  visible: boolean;
  onClose: () => void;
}

type Step = 1 | 2 | 3;

const CLONE_ITEMS = [
  { key: 'dishes', label: '菜品档案', desc: '菜品+分类+配料+套餐', default: true },
  { key: 'payments', label: '支付方式', desc: '支付方式+优惠券+互斥规则', default: true },
  { key: 'tables', label: '桌台设置', desc: '营业区+桌台+包厢', default: true },
  { key: 'marketing', label: '营销方案', desc: '特价/满减/买赠等方案', default: true },
  { key: 'kds', label: 'KDS/打印', desc: '出品部门+打印机+KDS映射', default: true },
  { key: 'roles', label: '角色权限', desc: '角色定义+权限配置', default: false },
  { key: 'daily_ops', label: '日清日结', desc: 'E1-E8检查项模板', default: true },
];

const MOCK_STORES = [
  { id: 's1', name: '尝在一起·芙蓉路店', brand: '尝在一起', status: '营业中' },
  { id: 's2', name: '尝在一起·岳麓店', brand: '尝在一起', status: '营业中' },
  { id: 's3', name: '尝在一起·星沙店', brand: '尝在一起', status: '待开业' },
];

export function QuickStoreModal({ visible, onClose }: Props) {
  const [step, setStep] = useState<Step>(1);
  const [sourceStore, setSourceStore] = useState('');
  const [targetStore, setTargetStore] = useState('');
  const [selectedItems, setSelectedItems] = useState(CLONE_ITEMS.filter(i => i.default).map(i => i.key));
  const [cloning, setCloning] = useState(false);

  if (!visible) return null;

  const toggleItem = (key: string) => {
    setSelectedItems(prev => prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]);
  };

  const handleClone = async () => {
    setCloning(true);
    // TODO: call POST /api/v1/ops/stores/clone
    await new Promise(r => setTimeout(r, 2000));
    setCloning(false);
    setStep(3);
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
      <div style={{ width: 520, background: '#112228', borderRadius: 12, padding: 24 }}>
        {/* 步骤指示器 */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 32, marginBottom: 24 }}>
          {[1, 2, 3].map(s => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: step >= s ? '#FF6B2C' : '#333', color: '#fff', fontSize: 13, fontWeight: 'bold',
              }}>{s}</span>
              <span style={{ fontSize: 12, color: step >= s ? '#fff' : '#666' }}>
                {s === 1 ? '选择门店' : s === 2 ? '选择配置' : '开店完成'}
              </span>
            </div>
          ))}
        </div>

        {/* Step 1: 选门店 */}
        {step === 1 && (
          <div>
            <div style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, color: '#999' }}>新门店（目标）</label>
              <select value={targetStore} onChange={e => setTargetStore(e.target.value)}
                style={{ width: '100%', padding: 10, marginTop: 4, background: '#0B1A20', border: '1px solid #333', borderRadius: 6, color: '#fff', fontSize: 14 }}>
                <option value="">请选择新门店</option>
                {MOCK_STORES.filter(s => s.status === '待开业').map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ fontSize: 12, color: '#999' }}>老门店（模板）</label>
              <select value={sourceStore} onChange={e => setSourceStore(e.target.value)}
                style={{ width: '100%', padding: 10, marginTop: 4, background: '#0B1A20', border: '1px solid #333', borderRadius: 6, color: '#fff', fontSize: 14 }}>
                <option value="">请选择老门店</option>
                {MOCK_STORES.filter(s => s.status === '营业中').map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
          </div>
        )}

        {/* Step 2: 选配置 */}
        {step === 2 && (
          <div>
            <div style={{ fontSize: 13, color: '#999', marginBottom: 12 }}>选择要从老门店复制的配置项：</div>
            {CLONE_ITEMS.map(item => (
              <label key={item.key} onClick={() => toggleItem(item.key)} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', marginBottom: 6,
                background: selectedItems.includes(item.key) ? 'rgba(255,107,44,0.08)' : '#0B1A20',
                border: `1px solid ${selectedItems.includes(item.key) ? '#FF6B2C' : '#333'}`,
                borderRadius: 8, cursor: 'pointer',
              }}>
                <input type="checkbox" checked={selectedItems.includes(item.key)} readOnly style={{ accentColor: '#FF6B2C' }} />
                <div>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{item.label}</div>
                  <div style={{ fontSize: 11, color: '#666' }}>{item.desc}</div>
                </div>
              </label>
            ))}
          </div>
        )}

        {/* Step 3: 完成 */}
        {step === 3 && (
          <div style={{ textAlign: 'center', padding: '20px 0' }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
            <div style={{ fontSize: 18, fontWeight: 'bold', marginBottom: 8 }}>开店完成！</div>
            <div style={{ fontSize: 13, color: '#999', marginBottom: 8 }}>
              已复制 {selectedItems.length} 项配置到新门店
            </div>
            <div style={{ fontSize: 12, color: '#faad14', background: 'rgba(250,173,20,0.08)', padding: 10, borderRadius: 6, textAlign: 'left' }}>
              提醒：请及时完善打印机/KDS关联的终端编号信息，并在门店信息中进行"上线"操作。
            </div>
          </div>
        )}

        {/* 底部按钮 */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
          <button onClick={onClose} style={{ padding: '8px 20px', background: '#333', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
            {step === 3 ? '关闭' : '取消'}
          </button>
          {step === 1 && (
            <button onClick={() => sourceStore && targetStore && setStep(2)} disabled={!sourceStore || !targetStore}
              style={{ padding: '8px 20px', background: sourceStore && targetStore ? '#FF6B2C' : '#444', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
              下一步
            </button>
          )}
          {step === 2 && (
            <>
              <button onClick={() => setStep(1)} style={{ padding: '8px 20px', background: '#333', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>上一步</button>
              <button onClick={handleClone} disabled={cloning || selectedItems.length === 0}
                style={{ padding: '8px 20px', background: '#FF6B2C', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer' }}>
                {cloning ? '复制中...' : '开始复制'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
