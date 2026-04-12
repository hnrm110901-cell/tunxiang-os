/**
 * 门店管理 — 门店列表 + 桌台配置
 * Tab1: 门店列表（统计卡 + 列表 + 新增/详情/暂停恢复）
 * Tab2: 桌台配置（门店选择 + 区域Tab + 桌台网格拓扑图）
 * API: GET /api/v1/trade/stores, POST /api/v1/trade/stores, PATCH /api/v1/trade/stores/{id}
 *      GET /api/v1/trade/tables?store_id=XXX, POST /api/v1/trade/tables, PATCH /api/v1/trade/tables/{id}
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { txFetchData } from '../../api';

// ─── 类型定义 ────────────────────────────────────────────────────────────────

type StoreType = 'direct' | 'franchise';
type StoreStatus = 'active' | 'suspended';
type TableStatus = 'available' | 'occupied' | 'reserved' | 'cleaning';
type TableArea = '大厅' | '包厢' | '室外' | '吧台';
type TableShape = 'square' | 'round' | 'rectangle';

interface Store {
  id: string;
  name: string;
  type: StoreType;
  city: string;
  address: string;
  status: StoreStatus;
  today_revenue_fen: number;
  table_count: number;
  manager: string;
  phone?: string;
  created_at?: string;
}

interface TableItem {
  id: string;
  number: string;
  area: TableArea;
  capacity: number;
  status: TableStatus;
  shape: TableShape;
  note?: string;
}

// ─── 降级占位数据（仅在 API 不可用时显示，不作为真实数据）────────────────────

const FALLBACK_STORES: Store[] = [];

const FALLBACK_TABLES: TableItem[] = [];

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const TABLE_STATUS_CONFIG: Record<TableStatus, { label: string; color: string; bg: string; border: string }> = {
  available: { label: '空闲', color: '#0F6E56', bg: '#0F6E5618', border: '#0F6E5644' },
  occupied:  { label: '使用中', color: '#FF6B35', bg: '#FF6B3518', border: '#FF6B3544' },
  reserved:  { label: '预约', color: '#185FA5', bg: '#185FA518', border: '#185FA544' },
  cleaning:  { label: '清台中', color: '#888', bg: '#88888818', border: '#88888844' },
};

const STORE_STATUS_CONFIG: Record<StoreStatus, { label: string; color: string; bg: string }> = {
  active:    { label: '正常营业', color: '#0F6E56', bg: '#0F6E5618' },
  suspended: { label: '暂停营业', color: '#A32D2D', bg: '#A32D2D18' },
};

const STORE_TYPE_CONFIG: Record<StoreType, { label: string; color: string; bg: string }> = {
  direct:    { label: '直营', color: '#FF6B35', bg: '#FF6B3518' },
  franchise: { label: '加盟', color: '#185FA5', bg: '#185FA518' },
};

const AREAS: TableArea[] = ['大厅', '包厢', '室外', '吧台'];

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

function formatRevenue(fen: number): string {
  if (fen === 0) return '—';
  const yuan = fen / 100;
  if (yuan >= 10000) return `${(yuan / 10000).toFixed(2)}万`;
  return `¥${yuan.toLocaleString('zh-CN')}`;
}

function formatDate(iso?: string): string {
  if (!iso) return '—';
  return iso.slice(0, 10);
}

// ─── 子组件：统计卡片 ─────────────────────────────────────────────────────────

function StatCard({ title, value, color }: { title: string; value: string | number; color?: string }) {
  return (
    <div style={{
      flex: 1, background: '#1a2a33', borderRadius: 10, padding: '16px 20px',
      border: '1px solid #2a3a44',
    }}>
      <div style={{ color: '#888', fontSize: 12, marginBottom: 8 }}>{title}</div>
      <div style={{ fontSize: 28, fontWeight: 700, color: color || '#fff' }}>{value}</div>
    </div>
  );
}

// ─── 子组件：新增门店 Modal ────────────────────────────────────────────────────

interface AddStoreModalProps {
  onClose: () => void;
  onAdd: (store: Omit<Store, 'id' | 'today_revenue_fen' | 'table_count' | 'created_at'>) => void;
}

function AddStoreModal({ onClose, onAdd }: AddStoreModalProps) {
  const [form, setForm] = useState({
    name: '', city: '', address: '', type: 'direct' as StoreType, manager: '', phone: '',
  });
  const [submitting, setSubmitting] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const validate = () => {
    const e: Record<string, string> = {};
    if (!form.name.trim()) e.name = '请填写门店名称';
    if (!form.city.trim()) e.city = '请填写城市';
    if (!form.address.trim()) e.address = '请填写地址';
    if (!form.manager.trim()) e.manager = '请填写负责人';
    return e;
  };

  const handleSubmit = async () => {
    const e = validate();
    if (Object.keys(e).length > 0) { setErrors(e); return; }
    setSubmitting(true);
    try {
      await txFetchData('/api/v1/trade/stores', {
        method: 'POST',
        body: JSON.stringify({ ...form, status: 'active' as StoreStatus }),
      });
    } catch {
      // 降级：接口不存在时仍然继续
    }
    onAdd({ ...form, status: 'active' });
    setSubmitting(false);
  };

  const field = (key: keyof typeof form, label: string, placeholder: string, type?: string) => (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>{label}</label>
      {key === 'type' ? (
        <div style={{ display: 'flex', gap: 8 }}>
          {(['direct', 'franchise'] as StoreType[]).map((t) => (
            <button key={t}
              onClick={() => setForm(f => ({ ...f, type: t }))}
              style={{
                flex: 1, padding: '8px 0', borderRadius: 6, border: `1px solid ${form.type === t ? '#FF6B35' : '#2a3a44'}`,
                background: form.type === t ? '#FF6B3522' : '#0d1e28', color: form.type === t ? '#FF6B35' : '#888',
                cursor: 'pointer', fontSize: 13, fontWeight: 600,
              }}
            >
              {STORE_TYPE_CONFIG[t].label}
            </button>
          ))}
        </div>
      ) : (
        <input
          type={type || 'text'}
          value={form[key]}
          onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
          placeholder={placeholder}
          style={{
            width: '100%', padding: '8px 12px', borderRadius: 6,
            border: `1px solid ${errors[key] ? '#A32D2D' : '#2a3a44'}`,
            background: '#0d1e28', color: '#fff', fontSize: 14, outline: 'none',
            boxSizing: 'border-box',
          }}
        />
      )}
      {errors[key] && <div style={{ color: '#A32D2D', fontSize: 11, marginTop: 3 }}>{errors[key]}</div>}
    </div>
  );

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={onClose}>
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: 28, width: 440,
        border: '1px solid #2a3a44', boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>新增门店</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>
        {field('name', '门店名称 *', '如：芙蓉路店')}
        {field('city', '城市 *', '如：长沙')}
        {field('address', '详细地址 *', '街道、楼层等')}
        {field('type', '门店类型', '')}
        {field('manager', '负责人 *', '店长姓名')}
        {field('phone', '联系电话', '13900000000', 'tel')}
        <div style={{ display: 'flex', gap: 10, marginTop: 20 }}>
          <button onClick={onClose} style={{
            flex: 1, padding: '10px 0', borderRadius: 8, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 14,
          }}>取消</button>
          <button onClick={handleSubmit} disabled={submitting} style={{
            flex: 2, padding: '10px 0', borderRadius: 8, border: 'none',
            background: submitting ? '#333' : '#FF6B35', color: submitting ? '#888' : '#fff',
            cursor: submitting ? 'not-allowed' : 'pointer', fontSize: 14, fontWeight: 700,
          }}>{submitting ? '提交中...' : '确认新增'}</button>
        </div>
      </div>
    </div>
  );
}

// ─── 子组件：门店详情 Drawer ───────────────────────────────────────────────────

function StoreDetailDrawer({ store, onClose }: { store: Store; onClose: () => void }) {
  const typeCfg = STORE_TYPE_CONFIG[store.type];
  const statusCfg = STORE_STATUS_CONFIG[store.status];

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 900, display: 'flex', justifyContent: 'flex-end',
    }}>
      <div style={{ flex: 1, background: 'rgba(0,0,0,0.4)' }} onClick={onClose} />
      <div style={{
        width: 380, background: '#1a2a33', borderLeft: '1px solid #2a3a44',
        padding: 24, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 16,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: '#fff', marginBottom: 6 }}>{store.name}</div>
            <div style={{ display: 'flex', gap: 6 }}>
              <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, background: typeCfg.bg, color: typeCfg.color }}>{typeCfg.label}</span>
              <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, background: statusCfg.bg, color: statusCfg.color }}>{statusCfg.label}</span>
            </div>
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>

        {[
          { label: '城市', value: store.city },
          { label: '地址', value: store.address },
          { label: '负责人', value: store.manager },
          { label: '联系电话', value: store.phone || '—' },
          { label: '开业日期', value: formatDate(store.created_at) },
        ].map(row => (
          <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid #2a3a44', paddingBottom: 12 }}>
            <span style={{ color: '#888', fontSize: 13 }}>{row.label}</span>
            <span style={{ color: '#fff', fontSize: 13, fontWeight: 500 }}>{row.value}</span>
          </div>
        ))}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div style={{ background: '#0d1e28', borderRadius: 8, padding: 14, textAlign: 'center' }}>
            <div style={{ color: '#888', fontSize: 11, marginBottom: 4 }}>今日营收</div>
            <div style={{ color: '#FF6B35', fontSize: 18, fontWeight: 700 }}>{formatRevenue(store.today_revenue_fen)}</div>
          </div>
          <div style={{ background: '#0d1e28', borderRadius: 8, padding: 14, textAlign: 'center' }}>
            <div style={{ color: '#888', fontSize: 11, marginBottom: 4 }}>桌台数</div>
            <div style={{ color: '#fff', fontSize: 18, fontWeight: 700 }}>{store.table_count}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── 子组件：暂停/恢复确认弹窗 ────────────────────────────────────────────────

function ConfirmModal({ store, onConfirm, onClose }: { store: Store; onConfirm: () => void; onClose: () => void }) {
  const isActive = store.status === 'active';
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: 28, width: 360,
        border: `1px solid ${isActive ? '#A32D2D44' : '#0F6E5644'}`,
      }}>
        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 12, color: isActive ? '#A32D2D' : '#0F6E56' }}>
          {isActive ? '确认暂停营业' : '确认恢复营业'}
        </div>
        <div style={{ color: '#aaa', fontSize: 14, marginBottom: 24, lineHeight: 1.6 }}>
          {isActive
            ? `暂停【${store.name}】营业后，该门店将无法收款和接单。确认操作？`
            : `恢复【${store.name}】营业后，门店可正常收款和接单。确认操作？`}
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onClose} style={{
            flex: 1, padding: '10px 0', borderRadius: 8, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 14,
          }}>取消</button>
          <button onClick={onConfirm} style={{
            flex: 1, padding: '10px 0', borderRadius: 8, border: 'none',
            background: isActive ? '#A32D2D' : '#0F6E56', color: '#fff',
            cursor: 'pointer', fontSize: 14, fontWeight: 700,
          }}>{isActive ? '确认暂停' : '确认恢复'}</button>
        </div>
      </div>
    </div>
  );
}

// ─── 子组件：桌台编辑 Drawer ──────────────────────────────────────────────────

function TableEditDrawer({ table, onClose, onSave }: {
  table: TableItem; onClose: () => void;
  onSave: (updated: TableItem) => void;
}) {
  const [form, setForm] = useState({ ...table });

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 900, display: 'flex', justifyContent: 'flex-end',
    }}>
      <div style={{ flex: 1, background: 'rgba(0,0,0,0.4)' }} onClick={onClose} />
      <div style={{
        width: 320, background: '#1a2a33', borderLeft: '1px solid #2a3a44',
        padding: 24, overflow: 'auto',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>桌台 {table.number}</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>

        {/* 容量 */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>容量（人）</label>
          <input type="number" min={1} max={20} value={form.capacity}
            onChange={e => setForm(f => ({ ...f, capacity: Number(e.target.value) }))}
            style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid #2a3a44', background: '#0d1e28', color: '#fff', fontSize: 14, outline: 'none', boxSizing: 'border-box' }}
          />
        </div>

        {/* 区域 */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>区域</label>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {AREAS.map(a => (
              <button key={a} onClick={() => setForm(f => ({ ...f, area: a }))}
                style={{
                  padding: '5px 14px', borderRadius: 6, border: `1px solid ${form.area === a ? '#FF6B35' : '#2a3a44'}`,
                  background: form.area === a ? '#FF6B3522' : 'transparent', color: form.area === a ? '#FF6B35' : '#888',
                  cursor: 'pointer', fontSize: 12, fontWeight: 600,
                }}>{a}</button>
            ))}
          </div>
        </div>

        {/* 形状 */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>形状</label>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['square', 'round', 'rectangle'] as TableShape[]).map(s => {
              const labels: Record<TableShape, string> = { square: '方桌', round: '圆桌', rectangle: '长桌' };
              return (
                <button key={s} onClick={() => setForm(f => ({ ...f, shape: s }))}
                  style={{
                    flex: 1, padding: '6px 0', borderRadius: 6, border: `1px solid ${form.shape === s ? '#FF6B35' : '#2a3a44'}`,
                    background: form.shape === s ? '#FF6B3522' : 'transparent', color: form.shape === s ? '#FF6B35' : '#888',
                    cursor: 'pointer', fontSize: 12,
                  }}>{labels[s]}</button>
              );
            })}
          </div>
        </div>

        {/* 备注 */}
        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>备注</label>
          <textarea value={form.note || ''}
            onChange={e => setForm(f => ({ ...f, note: e.target.value }))}
            placeholder="选填备注"
            rows={3}
            style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid #2a3a44', background: '#0d1e28', color: '#fff', fontSize: 13, outline: 'none', resize: 'vertical', boxSizing: 'border-box' }}
          />
        </div>

        <button onClick={() => onSave(form)} style={{
          width: '100%', padding: '10px 0', borderRadius: 8, border: 'none',
          background: '#FF6B35', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 700,
        }}>保存修改</button>
      </div>
    </div>
  );
}

// ─── 子组件：新增桌台 Modal ───────────────────────────────────────────────────

function AddTableModal({ onClose, onAdd }: { onClose: () => void; onAdd: (t: Omit<TableItem, 'id' | 'status'>) => void }) {
  const [form, setForm] = useState({ number: '', area: '大厅' as TableArea, capacity: 4, shape: 'square' as TableShape });
  const [err, setErr] = useState('');

  const handleSubmit = () => {
    if (!form.number.trim()) { setErr('请填写桌台号'); return; }
    onAdd(form);
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }} onClick={onClose}>
      <div style={{
        background: '#1a2a33', borderRadius: 12, padding: 28, width: 380,
        border: '1px solid #2a3a44',
      }} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>新增桌台</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: '#888', cursor: 'pointer', fontSize: 20 }}>×</button>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>桌台号 *</label>
          <input value={form.number} onChange={e => setForm(f => ({ ...f, number: e.target.value }))}
            placeholder="如：A09" style={{
              width: '100%', padding: '8px 12px', borderRadius: 6,
              border: `1px solid ${err ? '#A32D2D' : '#2a3a44'}`, background: '#0d1e28', color: '#fff', fontSize: 14, outline: 'none', boxSizing: 'border-box',
            }} />
          {err && <div style={{ color: '#A32D2D', fontSize: 11, marginTop: 3 }}>{err}</div>}
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>区域</label>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {AREAS.map(a => (
              <button key={a} onClick={() => setForm(f => ({ ...f, area: a }))}
                style={{
                  padding: '5px 14px', borderRadius: 6, border: `1px solid ${form.area === a ? '#FF6B35' : '#2a3a44'}`,
                  background: form.area === a ? '#FF6B3522' : 'transparent', color: form.area === a ? '#FF6B35' : '#888',
                  cursor: 'pointer', fontSize: 12, fontWeight: 600,
                }}>{a}</button>
            ))}
          </div>
        </div>

        <div style={{ marginBottom: 14 }}>
          <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>容量（人）</label>
          <input type="number" min={1} max={20} value={form.capacity}
            onChange={e => setForm(f => ({ ...f, capacity: Number(e.target.value) }))}
            style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid #2a3a44', background: '#0d1e28', color: '#fff', fontSize: 14, outline: 'none', boxSizing: 'border-box' }}
          />
        </div>

        <div style={{ marginBottom: 20 }}>
          <label style={{ display: 'block', color: '#aaa', fontSize: 12, marginBottom: 5 }}>形状</label>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['square', 'round', 'rectangle'] as TableShape[]).map(s => {
              const labels: Record<TableShape, string> = { square: '方桌', round: '圆桌', rectangle: '长桌' };
              return (
                <button key={s} onClick={() => setForm(f => ({ ...f, shape: s }))}
                  style={{
                    flex: 1, padding: '7px 0', borderRadius: 6, border: `1px solid ${form.shape === s ? '#FF6B35' : '#2a3a44'}`,
                    background: form.shape === s ? '#FF6B3522' : 'transparent', color: form.shape === s ? '#FF6B35' : '#888',
                    cursor: 'pointer', fontSize: 12,
                  }}>{labels[s]}</button>
              );
            })}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onClose} style={{
            flex: 1, padding: '10px 0', borderRadius: 8, border: '1px solid #2a3a44',
            background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 14,
          }}>取消</button>
          <button onClick={handleSubmit} style={{
            flex: 2, padding: '10px 0', borderRadius: 8, border: 'none',
            background: '#FF6B35', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 700,
          }}>确认新增</button>
        </div>
      </div>
    </div>
  );
}

// ─── 子组件：桌台格子 ────────────────────────────────────────────────────────

function TableCell({ table, selected, onSelect, onClick }: {
  table: TableItem; selected: boolean;
  onSelect: (id: string, checked: boolean) => void;
  onClick: (t: TableItem) => void;
}) {
  const cfg = TABLE_STATUS_CONFIG[table.status];
  const isRect = table.shape === 'rectangle';
  const isRound = table.shape === 'round';

  return (
    <div
      onClick={() => onClick(table)}
      style={{
        width: isRect ? 168 : 80, height: 80, borderRadius: isRound ? '50%' : 8,
        background: cfg.bg, border: `2px solid ${selected ? '#FF6B35' : cfg.border}`,
        cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', gap: 3, transition: 'all 0.15s', position: 'relative',
        boxShadow: selected ? '0 0 0 2px #FF6B3555' : 'none',
      }}
      onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = '#FF6B35'; }}
      onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = selected ? '#FF6B35' : cfg.border; }}
    >
      {/* 选择框 */}
      <div
        onClick={e => { e.stopPropagation(); onSelect(table.id, !selected); }}
        style={{
          position: 'absolute', top: 4, right: 4, width: 14, height: 14, borderRadius: 3,
          border: `1.5px solid ${selected ? '#FF6B35' : '#444'}`, background: selected ? '#FF6B35' : 'transparent',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        {selected && <span style={{ color: '#fff', fontSize: 9, fontWeight: 700 }}>✓</span>}
      </div>

      <div style={{ fontWeight: 700, fontSize: 13, color: cfg.color }}>{table.number}</div>
      <div style={{ fontSize: 11, color: cfg.color, opacity: 0.8 }}>{table.capacity}人</div>
      <div style={{
        fontSize: 10, color: cfg.color, padding: '1px 6px', borderRadius: 8,
        background: `${cfg.color}22`,
      }}>{cfg.label}</div>
    </div>
  );
}

// ─── Tab1：门店列表 ───────────────────────────────────────────────────────────

function StoreListTab() {
  const [stores, setStores] = useState<Store[]>(FALLBACK_STORES);
  const [loadingStores, setLoadingStores] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [detailStore, setDetailStore] = useState<Store | null>(null);
  const [confirmStore, setConfirmStore] = useState<Store | null>(null);
  const [searchText, setSearchText] = useState('');
  const [filterStatus, setFilterStatus] = useState<StoreStatus | 'all'>('all');
  const [filterType, setFilterType] = useState<StoreType | 'all'>('all');

  // 加载门店列表
  useEffect(() => {
    setLoadingStores(true);
    txFetchData<{ items: Store[] }>('/api/v1/trade/stores?page=1&size=200')
      .then(res => { setStores(res.items ?? []); })
      .catch(() => { setStores(FALLBACK_STORES); })
      .finally(() => { setLoadingStores(false); });
  }, []);

  // 统计
  const total = stores.length;
  const active = stores.filter(s => s.status === 'active').length;
  const suspended = stores.filter(s => s.status === 'suspended').length;
  // 模拟本月新增（created_at在近30天内）
  const now = new Date();
  const thisMonth = stores.filter(s => {
    if (!s.created_at) return false;
    const d = new Date(s.created_at);
    return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth();
  }).length;

  const filtered = stores.filter(s => {
    const matchText = !searchText || s.name.includes(searchText) || s.city.includes(searchText) || s.manager.includes(searchText);
    const matchStatus = filterStatus === 'all' || s.status === filterStatus;
    const matchType = filterType === 'all' || s.type === filterType;
    return matchText && matchStatus && matchType;
  });

  const handleAdd = async (data: Omit<Store, 'id' | 'today_revenue_fen' | 'table_count' | 'created_at'>) => {
    const payload = { ...data, today_revenue_fen: 0, table_count: 0 };
    try {
      const created = await txFetchData<Store>('/api/v1/trade/stores', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setStores(s => [...s, created]);
    } catch {
      // API 失败时本地乐观更新
      const newStore: Store = {
        ...payload, id: `s${Date.now()}`,
        created_at: new Date().toISOString().slice(0, 10),
      };
      setStores(s => [...s, newStore]);
    }
    setShowAdd(false);
  };

  const handleToggleStatus = useCallback(async (store: Store) => {
    const newStatus: StoreStatus = store.status === 'active' ? 'suspended' : 'active';
    try {
      await txFetchData(`/api/v1/trade/stores/${store.id}`, {
        method: 'PATCH', body: JSON.stringify({ status: newStatus }),
      });
    } catch {
      // 降级
    }
    setStores(ss => ss.map(s => s.id === store.id ? { ...s, status: newStatus } : s));
    setConfirmStore(null);
  }, []);

  return (
    <div>
      {/* 统计卡片 */}
      <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
        <StatCard title="总门店数" value={total} />
        <StatCard title="正常营业" value={active} color="#0F6E56" />
        <StatCard title="暂停营业" value={suspended} color="#A32D2D" />
        <StatCard title="本月新增" value={thisMonth} color="#FF6B35" />
      </div>

      {/* 筛选栏 */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <input
          value={searchText} onChange={e => setSearchText(e.target.value)}
          placeholder="搜索门店名/城市/负责人..."
          style={{
            padding: '7px 12px', borderRadius: 8, border: '1px solid #2a3a44',
            background: '#1a2a33', color: '#fff', fontSize: 13, outline: 'none', width: 220,
          }}
        />
        {/* 状态筛选 */}
        <div style={{ display: 'flex', gap: 4 }}>
          {(['all', 'active', 'suspended'] as const).map(v => (
            <button key={v} onClick={() => setFilterStatus(v)} style={{
              padding: '5px 12px', borderRadius: 6, border: `1px solid ${filterStatus === v ? '#FF6B35' : '#2a3a44'}`,
              background: filterStatus === v ? '#FF6B3522' : 'transparent', color: filterStatus === v ? '#FF6B35' : '#888',
              cursor: 'pointer', fontSize: 12,
            }}>
              {v === 'all' ? '全部' : v === 'active' ? '营业中' : '暂停'}
            </button>
          ))}
        </div>
        {/* 类型筛选 */}
        <div style={{ display: 'flex', gap: 4 }}>
          {(['all', 'direct', 'franchise'] as const).map(v => (
            <button key={v} onClick={() => setFilterType(v)} style={{
              padding: '5px 12px', borderRadius: 6, border: `1px solid ${filterType === v ? '#185FA5' : '#2a3a44'}`,
              background: filterType === v ? '#185FA522' : 'transparent', color: filterType === v ? '#185FA5' : '#888',
              cursor: 'pointer', fontSize: 12,
            }}>
              {v === 'all' ? '全部' : v === 'direct' ? '直营' : '加盟'}
            </button>
          ))}
        </div>
        <div style={{ flex: 1 }} />
        <button onClick={() => setShowAdd(true)} style={{
          padding: '7px 20px', borderRadius: 8, border: 'none',
          background: '#FF6B35', color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 700,
        }}>+ 新增门店</button>
      </div>

      {/* 表格 */}
      <div style={{ background: '#1a2a33', borderRadius: 10, border: '1px solid #2a3a44', overflow: 'hidden' }}>
        {/* 表头 */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1.6fr 80px 80px 120px 120px 80px 140px 140px',
          padding: '11px 16px', background: '#0d1e28', borderBottom: '1px solid #2a3a44',
          fontSize: 11, fontWeight: 700, color: '#666', textTransform: 'uppercase', letterSpacing: '0.05em',
        }}>
          <div>门店名称</div>
          <div>类型</div>
          <div>城市</div>
          <div>状态</div>
          <div>今日营收</div>
          <div>桌台数</div>
          <div>开业日期</div>
          <div>操作</div>
        </div>

        {/* 数据行 */}
        {loadingStores ? (
          <div style={{ padding: '40px 0', textAlign: 'center', color: '#888', fontSize: 13 }}>加载中...</div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: '40px 0', textAlign: 'center', color: '#888', fontSize: 13 }}>暂无门店数据</div>
        ) : (
          filtered.map((store, idx) => {
            const typeCfg = STORE_TYPE_CONFIG[store.type];
            const statusCfg = STORE_STATUS_CONFIG[store.status];
            return (
              <div key={store.id} style={{
                display: 'grid',
                gridTemplateColumns: '1.6fr 80px 80px 120px 120px 80px 140px 140px',
                padding: '13px 16px', alignItems: 'center',
                borderBottom: idx < filtered.length - 1 ? '1px solid #2a3a44' : 'none',
                transition: 'background 0.12s',
              }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = '#0d1e2866'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}
              >
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14, color: '#fff', marginBottom: 2 }}>{store.name}</div>
                  <div style={{ fontSize: 11, color: '#888' }}>{store.manager} · {store.address}</div>
                </div>
                <div>
                  <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, background: typeCfg.bg, color: typeCfg.color }}>{typeCfg.label}</span>
                </div>
                <div style={{ color: '#ccc', fontSize: 13 }}>{store.city}</div>
                <div>
                  <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, background: statusCfg.bg, color: statusCfg.color }}>{statusCfg.label}</span>
                </div>
                <div style={{ color: store.status === 'active' ? '#FF6B35' : '#888', fontWeight: 600, fontSize: 14 }}>
                  {formatRevenue(store.today_revenue_fen)}
                </div>
                <div style={{ color: '#ccc', fontSize: 13 }}>{store.table_count}</div>
                <div style={{ color: '#888', fontSize: 12 }}>{formatDate(store.created_at)}</div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button onClick={() => setDetailStore(store)} style={{
                    padding: '4px 10px', borderRadius: 6, border: '1px solid #2a3a44',
                    background: 'transparent', color: '#aaa', cursor: 'pointer', fontSize: 11,
                  }}>详情</button>
                  <button onClick={() => setConfirmStore(store)} style={{
                    padding: '4px 10px', borderRadius: 6, border: `1px solid ${store.status === 'active' ? '#A32D2D44' : '#0F6E5644'}`,
                    background: 'transparent', color: store.status === 'active' ? '#A32D2D' : '#0F6E56', cursor: 'pointer', fontSize: 11,
                  }}>
                    {store.status === 'active' ? '暂停' : '恢复'}
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* 页脚统计 */}
      <div style={{ marginTop: 12, color: '#888', fontSize: 12, textAlign: 'right' }}>
        共 {filtered.length} 家门店
      </div>

      {/* 弹窗 */}
      {showAdd && <AddStoreModal onClose={() => setShowAdd(false)} onAdd={handleAdd} />}
      {detailStore && <StoreDetailDrawer store={detailStore} onClose={() => setDetailStore(null)} />}
      {confirmStore && (
        <ConfirmModal
          store={confirmStore}
          onConfirm={() => handleToggleStatus(confirmStore)}
          onClose={() => setConfirmStore(null)}
        />
      )}
    </div>
  );
}

// ─── Tab2：桌台配置 ───────────────────────────────────────────────────────────

function TableConfigTab() {
  const [stores, setStores] = useState<Store[]>(FALLBACK_STORES);
  const [loadingStores, setLoadingStores] = useState(true);
  const [selectedStoreId, setSelectedStoreId] = useState<string>('');
  const [tables, setTables] = useState<TableItem[]>(FALLBACK_TABLES);
  const [loading, setLoading] = useState(false);
  const [activeArea, setActiveArea] = useState<TableArea>('大厅');
  const [editTable, setEditTable] = useState<TableItem | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const initRef = useRef(false);

  // 加载门店列表（Tab2 独立加载，不依赖 Tab1）
  useEffect(() => {
    setLoadingStores(true);
    txFetchData<{ items: Store[] }>('/api/v1/trade/stores?page=1&size=200')
      .then(res => {
        const list = res.items ?? [];
        setStores(list);
        if (list.length > 0 && !initRef.current) {
          setSelectedStoreId(list[0].id);
          initRef.current = true;
        }
      })
      .catch(() => { setStores([]); })
      .finally(() => { setLoadingStores(false); });
  }, []);

  // 切换门店时加载桌台
  const loadTables = useCallback(async (storeId: string) => {
    if (!storeId) return;
    setLoading(true);
    setSelectedIds(new Set());
    try {
      const res = await txFetchData<{ items: TableItem[] }>(`/api/v1/trade/tables?store_id=${storeId}`);
      setTables(res.items ?? FALLBACK_TABLES);
    } catch {
      setTables(FALLBACK_TABLES);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadTables(selectedStoreId); }, [selectedStoreId, loadTables]);

  const areaItems = tables.filter(t => t.area === activeArea);

  // 区域统计
  const areaStats = AREAS.reduce((acc, area) => {
    const items = tables.filter(t => t.area === area);
    acc[area] = {
      total: items.length,
      available: items.filter(t => t.status === 'available').length,
      occupied: items.filter(t => t.status === 'occupied').length,
    };
    return acc;
  }, {} as Record<TableArea, { total: number; available: number; occupied: number }>);

  const handleSaveTable = useCallback(async (updated: TableItem) => {
    try {
      await txFetchData(`/api/v1/trade/tables/${updated.id}`, {
        method: 'PATCH', body: JSON.stringify(updated),
      });
    } catch { /* 降级 */ }
    setTables(ts => ts.map(t => t.id === updated.id ? updated : t));
    setEditTable(null);
  }, []);

  const handleAddTable = useCallback(async (data: Omit<TableItem, 'id' | 'status'>) => {
    const newTable: TableItem = { ...data, id: `t${Date.now()}`, status: 'available' };
    try {
      await txFetchData('/api/v1/trade/tables', {
        method: 'POST', body: JSON.stringify({ ...newTable, store_id: selectedStoreId }),
      });
    } catch { /* 降级 */ }
    setTables(ts => [...ts, newTable]);
    setShowAdd(false);
    setActiveArea(newTable.area);
  }, [selectedStoreId]);

  const handleSelectTable = useCallback((id: string, checked: boolean) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }, []);

  const handleBatchDelete = () => {
    setTables(ts => ts.filter(t => !selectedIds.has(t.id)));
    setSelectedIds(new Set());
    setShowDeleteConfirm(false);
  };

  const selectedStore = stores.find(s => s.id === selectedStoreId)!;

  return (
    <div style={{ display: 'flex', gap: 20, minHeight: 600 }}>
      {/* 左侧：门店选择 */}
      <div style={{ width: 220, flexShrink: 0 }}>
        <div style={{ marginBottom: 10, color: '#aaa', fontSize: 12 }}>选择门店</div>
        {stores.map(store => (
          <div key={store.id}
            onClick={() => setSelectedStoreId(store.id)}
            style={{
              padding: '11px 14px', borderRadius: 8, cursor: 'pointer', marginBottom: 4,
              background: selectedStoreId === store.id ? '#FF6B3518' : '#1a2a33',
              border: `1px solid ${selectedStoreId === store.id ? '#FF6B35' : '#2a3a44'}`,
              transition: 'all 0.12s',
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 13, color: selectedStoreId === store.id ? '#FF6B35' : '#fff', marginBottom: 2 }}>
              {store.name}
            </div>
            <div style={{ fontSize: 11, color: '#888' }}>{store.city} · {store.table_count}桌</div>
          </div>
        ))}

        {/* 区域统计 */}
        <div style={{ marginTop: 16, background: '#1a2a33', borderRadius: 8, padding: 12, border: '1px solid #2a3a44' }}>
          <div style={{ color: '#888', fontSize: 11, marginBottom: 8, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>区域概览</div>
          {AREAS.map(area => {
            const stat = areaStats[area] || { total: 0, available: 0, occupied: 0 };
            return (
              <div key={area} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 12 }}>
                <span style={{ color: '#aaa' }}>{area}</span>
                <span style={{ color: '#fff' }}>
                  <span style={{ color: '#0F6E56' }}>{stat.available}</span>
                  <span style={{ color: '#666' }}>/{stat.total}</span>
                </span>
              </div>
            );
          })}
        </div>
      </div>

      {/* 右侧：桌台配置区 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* 右侧标题栏 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div>
            <span style={{ fontSize: 16, fontWeight: 700, color: '#fff' }}>{selectedStore?.name}</span>
            <span style={{ color: '#888', fontSize: 13, marginLeft: 10 }}>共 {tables.length} 张桌台</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {selectedIds.size > 0 && (
              <button onClick={() => setShowDeleteConfirm(true)} style={{
                padding: '6px 14px', borderRadius: 8, border: '1px solid #A32D2D44',
                background: '#A32D2D22', color: '#A32D2D', cursor: 'pointer', fontSize: 12, fontWeight: 600,
              }}>
                删除选中 ({selectedIds.size})
              </button>
            )}
            <button onClick={() => setShowAdd(true)} style={{
              padding: '6px 16px', borderRadius: 8, border: 'none',
              background: '#FF6B35', color: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 700,
            }}>+ 新增桌台</button>
          </div>
        </div>

        {/* 图例 */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
          {(Object.entries(TABLE_STATUS_CONFIG) as [TableStatus, typeof TABLE_STATUS_CONFIG[TableStatus]][]).map(([key, cfg]) => (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#888' }}>
              <div style={{ width: 12, height: 12, borderRadius: 2, background: cfg.bg, border: `1.5px solid ${cfg.border}` }} />
              <span>{cfg.label}</span>
            </div>
          ))}
        </div>

        {/* 区域 Tab */}
        <div style={{ display: 'flex', gap: 2, marginBottom: 16, background: '#0d1e28', borderRadius: 8, padding: 4, width: 'fit-content' }}>
          {AREAS.map(area => {
            const stat = areaStats[area] || { total: 0, available: 0, occupied: 0 };
            return (
              <button key={area} onClick={() => setActiveArea(area)} style={{
                padding: '6px 18px', borderRadius: 6, border: 'none',
                background: activeArea === area ? '#1a2a33' : 'transparent',
                color: activeArea === area ? '#FF6B35' : '#888',
                cursor: 'pointer', fontSize: 13, fontWeight: activeArea === area ? 700 : 400,
                transition: 'all 0.12s',
              }}>
                {area}
                <span style={{ fontSize: 11, marginLeft: 4, opacity: 0.7 }}>({stat.total})</span>
              </button>
            );
          })}
        </div>

        {/* 桌台网格 */}
        {loading ? (
          <div style={{ textAlign: 'center', padding: 60, color: '#888', fontSize: 14 }}>加载中...</div>
        ) : areaItems.length === 0 ? (
          <div style={{
            textAlign: 'center', padding: 60, color: '#888', fontSize: 14,
            background: '#1a2a33', borderRadius: 10, border: '1px dashed #2a3a44',
          }}>
            {activeArea} 区暂无桌台，点击右上角"新增桌台"添加
          </div>
        ) : (
          <div style={{
            background: '#1a2a33', borderRadius: 10, padding: 20,
            border: '1px solid #2a3a44', minHeight: 200,
          }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
              {areaItems.map(table => (
                <TableCell
                  key={table.id}
                  table={table}
                  selected={selectedIds.has(table.id)}
                  onSelect={handleSelectTable}
                  onClick={setEditTable}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Drawers & Modals */}
      {editTable && <TableEditDrawer table={editTable} onClose={() => setEditTable(null)} onSave={handleSaveTable} />}
      {showAdd && <AddTableModal onClose={() => setShowAdd(false)} onAdd={handleAddTable} />}
      {showDeleteConfirm && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <div style={{ background: '#1a2a33', borderRadius: 12, padding: 28, width: 340, border: '1px solid #A32D2D44' }}>
            <div style={{ fontSize: 17, fontWeight: 700, color: '#A32D2D', marginBottom: 12 }}>确认批量删除</div>
            <div style={{ color: '#aaa', fontSize: 14, marginBottom: 24 }}>
              即将删除 {selectedIds.size} 张桌台，此操作不可撤销。
            </div>
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setShowDeleteConfirm(false)} style={{
                flex: 1, padding: '10px 0', borderRadius: 8, border: '1px solid #2a3a44',
                background: 'transparent', color: '#888', cursor: 'pointer', fontSize: 14,
              }}>取消</button>
              <button onClick={handleBatchDelete} style={{
                flex: 1, padding: '10px 0', borderRadius: 8, border: 'none',
                background: '#A32D2D', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 700,
              }}>确认删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function StoreManagePage() {
  const [activeTab, setActiveTab] = useState<'list' | 'tables'>('list');

  return (
    <div style={{ padding: 24, minHeight: '100vh', background: '#0d1e28', color: '#fff' }}>
      {/* 页头 */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: '#fff' }}>门店管理</h2>
        <p style={{ color: '#888', margin: '6px 0 0', fontSize: 13 }}>管理连锁门店基本信息与桌台配置</p>
      </div>

      {/* Tab 切换 */}
      <div style={{ display: 'flex', gap: 2, marginBottom: 20, background: '#1a2a33', borderRadius: 8, padding: 4, width: 'fit-content', border: '1px solid #2a3a44' }}>
        {([['list', '门店列表'], ['tables', '桌台配置']] as const).map(([key, label]) => (
          <button key={key} onClick={() => setActiveTab(key)} style={{
            padding: '7px 28px', borderRadius: 6, border: 'none',
            background: activeTab === key ? '#FF6B35' : 'transparent',
            color: activeTab === key ? '#fff' : '#888',
            cursor: 'pointer', fontSize: 14, fontWeight: activeTab === key ? 700 : 400,
            transition: 'all 0.15s',
          }}>{label}</button>
        ))}
      </div>

      {/* Tab 内容 */}
      {activeTab === 'list' ? <StoreListTab /> : <TableConfigTab />}
    </div>
  );
}
