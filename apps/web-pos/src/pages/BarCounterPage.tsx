/**
 * 吧台盘点 — Bar Counter Inventory Management
 * 终端：Store-POS（安卓 POS / iPad）
 * 功能: 库存状况 / 盘点单 / 领用单 / 调拨单 / 盘点报表
 * 调用: tx-supply :8006  /api/v1/supply/*
 * 规范: TXTouch 触控风格，禁止 Ant Design，大按钮大字体
 */
import React, { useCallback, useEffect, useState } from 'react';
import { txFetch } from '../api';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

interface InventoryItem {
  id: string;
  ingredient_id: string;
  name: string;
  unit: string;
  quantity: number;
  safety_stock: number;
  status: 'ok' | 'low' | 'out';
  last_updated: string;
}

interface StocktakeRecord {
  id: string;
  created_at: string;
  status: 'draft' | 'submitted' | 'confirmed';
  items_count: number;
  variance_fen?: number;
}

interface StocktakeItem {
  ingredient_id: string;
  name: string;
  unit: string;
  book_qty: number;
  actual_qty: number;
  variance: number;
}

interface RequisitionRecord {
  id: string;
  created_at: string;
  requester_name: string;
  items_count: number;
  status: 'pending' | 'approved' | 'rejected';
}

interface TransferRecord {
  id: string;
  created_at: string;
  to_store_name: string;
  items_count: number;
  status: 'pending' | 'approved' | 'shipped' | 'received';
}

interface ReportItem {
  name: string;
  unit: string;
  gain_qty: number;
  loss_qty: number;
  gain_fen: number;
  loss_fen: number;
}

type TabKey = 'inventory' | 'stocktake' | 'requisition' | 'transfer' | 'report';

// ─── Mock 数据（API 不可用时降级） ────────────────────────────────────────────

const MOCK_INVENTORY: InventoryItem[] = [
  { id: '1', ingredient_id: 'i1', name: '可乐 330ml', unit: '罐', quantity: 48, safety_stock: 24, status: 'ok', last_updated: '2026-04-06 08:00' },
  { id: '2', ingredient_id: 'i2', name: '百威啤酒', unit: '箱', quantity: 3, safety_stock: 5, status: 'low', last_updated: '2026-04-06 08:00' },
  { id: '3', ingredient_id: 'i3', name: '气泡水', unit: '瓶', quantity: 0, safety_stock: 12, status: 'out', last_updated: '2026-04-05 20:00' },
  { id: '4', ingredient_id: 'i4', name: '雪碧 500ml', unit: '瓶', quantity: 36, safety_stock: 20, status: 'ok', last_updated: '2026-04-06 08:00' },
  { id: '5', ingredient_id: 'i5', name: '橙汁鲜榨原料', unit: 'kg', quantity: 8.5, safety_stock: 5, status: 'ok', last_updated: '2026-04-06 09:30' },
];

const MOCK_STOCKTAKES: StocktakeRecord[] = [
  { id: 's1', created_at: '2026-04-05 22:30', status: 'confirmed', items_count: 15, variance_fen: -800 },
  { id: 's2', created_at: '2026-04-04 22:15', status: 'confirmed', items_count: 15, variance_fen: 200 },
];

const MOCK_REQUISITIONS: RequisitionRecord[] = [
  { id: 'r1', created_at: '2026-04-06 10:00', requester_name: '张三', items_count: 3, status: 'pending' },
  { id: 'r2', created_at: '2026-04-05 14:30', requester_name: '李四', items_count: 5, status: 'approved' },
];

const MOCK_TRANSFERS: TransferRecord[] = [
  { id: 't1', created_at: '2026-04-06 09:00', to_store_name: '河东店', items_count: 2, status: 'pending' },
];

const MOCK_REPORT: ReportItem[] = [
  { name: '百威啤酒', unit: '箱', gain_qty: 0, loss_qty: 1, gain_fen: 0, loss_fen: 15000 },
  { name: '可乐 330ml', unit: '罐', gain_qty: 2, loss_qty: 0, gain_fen: 600, loss_fen: 0 },
];

// ─── CSS-in-JS 样式常量（TXTouch 规范） ──────────────────────────────────────

const CSS = {
  page: {
    minHeight: '100vh',
    background: '#F8F7F5',
    fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    color: '#2C2C2A',
  } as React.CSSProperties,
  header: {
    background: '#1E2A3A',
    padding: '16px 20px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  } as React.CSSProperties,
  headerTitle: {
    fontSize: 20,
    fontWeight: 700,
    color: '#FFFFFF',
    margin: 0,
  } as React.CSSProperties,
  tabBar: {
    display: 'flex',
    background: '#FFFFFF',
    borderBottom: '2px solid #E8E6E1',
    overflowX: 'auto' as const,
  } as React.CSSProperties,
  tabBtn: (active: boolean): React.CSSProperties => ({
    flex: '0 0 auto',
    minHeight: 56,
    padding: '0 20px',
    fontSize: 17,
    fontWeight: active ? 700 : 400,
    color: active ? '#FF6B35' : '#5F5E5A',
    background: 'transparent',
    border: 'none',
    borderBottom: active ? '3px solid #FF6B35' : '3px solid transparent',
    cursor: 'pointer',
    whiteSpace: 'nowrap' as const,
    WebkitTapHighlightColor: 'transparent',
  }),
  content: {
    padding: 16,
  } as React.CSSProperties,
  card: {
    background: '#FFFFFF',
    borderRadius: 12,
    padding: '16px 20px',
    marginBottom: 12,
    boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
  } as React.CSSProperties,
  itemRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 56,
    padding: '12px 0',
    borderBottom: '1px solid #F0EDE6',
  } as React.CSSProperties,
  label: {
    fontSize: 17,
    color: '#2C2C2A',
    fontWeight: 500,
  } as React.CSSProperties,
  sublabel: {
    fontSize: 14,
    color: '#5F5E5A',
    marginTop: 2,
  } as React.CSSProperties,
  primaryBtn: {
    minHeight: 56,
    padding: '0 28px',
    background: '#FF6B35',
    color: '#FFFFFF',
    border: 'none',
    borderRadius: 12,
    fontSize: 17,
    fontWeight: 700,
    cursor: 'pointer',
    WebkitTapHighlightColor: 'transparent',
    transition: 'transform 200ms ease',
  } as React.CSSProperties,
  secondaryBtn: {
    minHeight: 48,
    padding: '0 20px',
    background: '#FFFFFF',
    color: '#FF6B35',
    border: '2px solid #FF6B35',
    borderRadius: 12,
    fontSize: 16,
    fontWeight: 600,
    cursor: 'pointer',
    WebkitTapHighlightColor: 'transparent',
  } as React.CSSProperties,
  dangerBtn: {
    minHeight: 48,
    padding: '0 20px',
    background: '#FFFFFF',
    color: '#A32D2D',
    border: '2px solid #A32D2D',
    borderRadius: 12,
    fontSize: 16,
    fontWeight: 600,
    cursor: 'pointer',
    WebkitTapHighlightColor: 'transparent',
  } as React.CSSProperties,
  statusBadge: (status: string): React.CSSProperties => {
    const map: Record<string, { bg: string; color: string }> = {
      ok:       { bg: '#EBF8F4', color: '#0F6E56' },
      low:      { bg: '#FFF8E1', color: '#BA7517' },
      out:      { bg: '#FDECEA', color: '#A32D2D' },
      pending:  { bg: '#FFF8E1', color: '#BA7517' },
      approved: { bg: '#EBF8F4', color: '#0F6E56' },
      rejected: { bg: '#FDECEA', color: '#A32D2D' },
      draft:    { bg: '#EBF0FB', color: '#185FA5' },
      submitted:{ bg: '#FFF8E1', color: '#BA7517' },
      confirmed:{ bg: '#EBF8F4', color: '#0F6E56' },
      shipped:  { bg: '#EBF0FB', color: '#185FA5' },
      received: { bg: '#EBF8F4', color: '#0F6E56' },
    };
    const s = map[status] ?? { bg: '#F0EDE6', color: '#5F5E5A' };
    return {
      display: 'inline-block',
      padding: '4px 12px',
      background: s.bg,
      color: s.color,
      borderRadius: 20,
      fontSize: 14,
      fontWeight: 600,
    };
  },
  modal: {
    position: 'fixed' as const,
    inset: 0,
    zIndex: 1000,
    display: 'flex',
    alignItems: 'flex-end',
    background: 'rgba(0,0,0,0.4)',
  } as React.CSSProperties,
  modalBody: {
    width: '100%',
    background: '#FFFFFF',
    borderRadius: '16px 16px 0 0',
    padding: 24,
    maxHeight: '80vh',
    overflowY: 'auto' as const,
  } as React.CSSProperties,
  input: {
    width: '100%',
    minHeight: 52,
    padding: '12px 16px',
    fontSize: 17,
    border: '1.5px solid #E8E6E1',
    borderRadius: 10,
    background: '#F8F7F5',
    color: '#2C2C2A',
    boxSizing: 'border-box' as const,
  } as React.CSSProperties,
  sectionTitle: {
    fontSize: 18,
    fontWeight: 700,
    color: '#1E2A3A',
    margin: '16px 0 8px',
  } as React.CSSProperties,
};

const STATUS_LABEL: Record<string, string> = {
  ok: '充足', low: '偏低', out: '沽清',
  pending: '待审批', approved: '已通过', rejected: '已拒绝',
  draft: '草稿', submitted: '已提交', confirmed: '已确认',
  shipped: '已发货', received: '已收货',
};

// ─── 打印辅助 ─────────────────────────────────────────────────────────────────

const handlePrint = (data: unknown) => {
  if ((window as Window & { TXBridge?: { print: (s: string) => void } }).TXBridge?.print) {
    (window as Window & { TXBridge: { print: (s: string) => void } }).TXBridge.print(JSON.stringify(data));
  } else {
    window.print();
  }
};

// ─── CSV 导出辅助 ─────────────────────────────────────────────────────────────

const exportCSV = (rows: InventoryItem[]) => {
  const header = '品项名,单位,当前库存,安全库存,状态,最后更新时间';
  const body = rows.map(r =>
    `${r.name},${r.unit},${r.quantity},${r.safety_stock},${STATUS_LABEL[r.status] ?? r.status},${r.last_updated}`
  ).join('\n');
  const blob = new Blob([`\uFEFF${header}\n${body}`], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `吧台库存_${new Date().toLocaleDateString('zh')}.csv`;
  a.click();
  URL.revokeObjectURL(url);
};

// ─── 库存状况 Tab ─────────────────────────────────────────────────────────────

function InventoryTab({ storeId }: { storeId: string }) {
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await txFetch<{ ok: boolean; data: { items: InventoryItem[] } }>(
        `/api/v1/supply/inventory/store/${storeId}?size=100`
      );
      if (res.ok && res.data?.items) {
        setItems(res.data.items);
        return;
      }
    } catch {
      // API 不可达，降级到 mock
    }
    setItems(MOCK_INVENTORY);
    setLoading(false);
  }, [storeId]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={CSS.sectionTitle}>库存清单</span>
        <div style={{ display: 'flex', gap: 8 }}>
          <button style={CSS.secondaryBtn} onClick={() => exportCSV(items)}>导出 CSV</button>
          <button style={CSS.secondaryBtn} onClick={load}>刷新</button>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 32, color: '#B4B2A9', fontSize: 17 }}>加载中…</div>
      )}

      {!loading && items.map((item) => (
        <div key={item.id} style={CSS.itemRow}>
          <div>
            <div style={CSS.label}>{item.name}</div>
            <div style={CSS.sublabel}>安全库存：{item.safety_stock} {item.unit} · 更新：{item.last_updated}</div>
          </div>
          <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
            <span style={{ fontSize: 22, fontWeight: 700, color: item.status === 'out' ? '#A32D2D' : item.status === 'low' ? '#BA7517' : '#2C2C2A' }}>
              {item.quantity} <span style={{ fontSize: 14, color: '#5F5E5A' }}>{item.unit}</span>
            </span>
            <span style={CSS.statusBadge(item.status)}>{STATUS_LABEL[item.status]}</span>
          </div>
        </div>
      ))}

      {!loading && items.length === 0 && (
        <div style={{ textAlign: 'center', padding: 48, color: '#B4B2A9', fontSize: 17 }}>暂无库存数据</div>
      )}
    </div>
  );
}

// ─── 盘点单 Tab ───────────────────────────────────────────────────────────────

function StocktakeTab({ storeId }: { storeId: string }) {
  const [records, setRecords] = useState<StocktakeRecord[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [newItems, setNewItems] = useState<StocktakeItem[]>([
    { ingredient_id: 'i1', name: '可乐 330ml', unit: '罐', book_qty: 48, actual_qty: 0, variance: 0 },
    { ingredient_id: 'i2', name: '百威啤酒', unit: '箱', book_qty: 3, actual_qty: 0, variance: 0 },
  ]);
  const [submitting, setSubmitting] = useState(false);

  const loadRecords = useCallback(async () => {
    try {
      const res = await txFetch<{ ok: boolean; data: { items: StocktakeRecord[] } }>(
        `/api/v1/supply/stocktakes?store_id=${storeId}`
      );
      if (res.ok && res.data?.items) { setRecords(res.data.items); return; }
    } catch { /* fall through */ }
    setRecords(MOCK_STOCKTAKES);
  }, [storeId]);

  useEffect(() => { void loadRecords(); }, [loadRecords]);

  const handleActualChange = (idx: number, val: string) => {
    const actual = parseFloat(val) || 0;
    setNewItems(prev => prev.map((item, i) =>
      i === idx ? { ...item, actual_qty: actual, variance: actual - item.book_qty } : item
    ));
  };

  const handleSubmitStocktake = async () => {
    setSubmitting(true);
    try {
      for (const item of newItems) {
        if (item.variance !== 0) {
          await txFetch(`/api/v1/supply/inventory/${item.ingredient_id}/adjust`, {
            method: 'POST',
            body: JSON.stringify({
              ingredient_id: item.ingredient_id,
              quantity: item.variance,
              reason: '盘点调整',
              store_id: storeId,
            }),
          });
        }
      }
    } catch { /* API 不可达，本地记录即可 */ }
    setRecords(prev => [{
      id: `local_${Date.now()}`,
      created_at: new Date().toLocaleString('zh'),
      status: 'confirmed',
      items_count: newItems.length,
    }, ...prev]);
    handlePrint({ type: '盘点单', items: newItems, created_at: new Date().toISOString() });
    setShowNew(false);
    setSubmitting(false);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={CSS.sectionTitle}>盘点记录</span>
        <button style={CSS.primaryBtn} onClick={() => setShowNew(true)}>+ 新建盘点</button>
      </div>

      {records.map(r => (
        <div key={r.id} style={CSS.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={CSS.label}>{r.created_at}</div>
              <div style={CSS.sublabel}>{r.items_count} 个品项
                {r.variance_fen !== undefined && (
                  <span style={{ marginLeft: 8, color: r.variance_fen < 0 ? '#A32D2D' : '#0F6E56' }}>
                    损益：{r.variance_fen < 0 ? '' : '+'}{(r.variance_fen / 100).toFixed(2)} 元
                  </span>
                )}
              </div>
            </div>
            <span style={CSS.statusBadge(r.status)}>{STATUS_LABEL[r.status]}</span>
          </div>
        </div>
      ))}

      {records.length === 0 && (
        <div style={{ textAlign: 'center', padding: 48, color: '#B4B2A9', fontSize: 17 }}>暂无盘点记录</div>
      )}

      {showNew && (
        <div style={CSS.modal} onClick={(e) => e.target === e.currentTarget && setShowNew(false)}>
          <div style={CSS.modalBody}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>新建盘点单</h2>
              <button style={{ ...CSS.secondaryBtn, minHeight: 40 }} onClick={() => setShowNew(false)}>取消</button>
            </div>

            {newItems.map((item, idx) => (
              <div key={item.ingredient_id} style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 17, fontWeight: 600, marginBottom: 8 }}>
                  {item.name}（账面：{item.book_qty} {item.unit}）
                </div>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <div style={{ flex: 1 }}>
                    <input
                      type="number"
                      placeholder="实际数量"
                      style={CSS.input}
                      onChange={(e) => handleActualChange(idx, e.target.value)}
                    />
                  </div>
                  <div style={{ minWidth: 80, textAlign: 'right', fontSize: 16, fontWeight: 600,
                    color: item.variance > 0 ? '#0F6E56' : item.variance < 0 ? '#A32D2D' : '#B4B2A9' }}>
                    {item.variance > 0 ? '+' : ''}{item.variance} {item.unit}
                  </div>
                </div>
              </div>
            ))}

            <button
              style={{ ...CSS.primaryBtn, width: '100%', marginTop: 8 }}
              disabled={submitting}
              onClick={handleSubmitStocktake}
            >
              {submitting ? '提交中…' : '提交盘点'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 领用单 Tab ───────────────────────────────────────────────────────────────

function RequisitionTab({ storeId }: { storeId: string }) {
  const [records, setRecords] = useState<RequisitionRecord[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    ingredient_name: '', quantity: '', unit: '', requester_name: '', purpose: '', remark: '',
  });
  const [submitting, setSubmitting] = useState(false);

  const loadRecords = useCallback(async () => {
    try {
      const res = await txFetch<{ ok: boolean; data: { items: RequisitionRecord[] } }>(
        `/api/v1/supply/requisitions?store_id=${storeId}`
      );
      if (res.ok && res.data?.items) { setRecords(res.data.items); return; }
    } catch { /* fall through */ }
    setRecords(MOCK_REQUISITIONS);
  }, [storeId]);

  useEffect(() => { void loadRecords(); }, [loadRecords]);

  const handleSubmit = async () => {
    if (!form.ingredient_name || !form.quantity) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/supply/requisitions', {
        method: 'POST',
        body: JSON.stringify({
          store_id: storeId,
          items: [{
            ingredient_id: `manual_${Date.now()}`,
            name: form.ingredient_name,
            quantity: parseFloat(form.quantity),
            unit: form.unit,
          }],
          requester_id: form.requester_name,
        }),
      });
    } catch { /* 降级处理 */ }
    setRecords(prev => [{
      id: `local_${Date.now()}`,
      created_at: new Date().toLocaleString('zh'),
      requester_name: form.requester_name || '未填',
      items_count: 1,
      status: 'pending',
    }, ...prev]);
    setShowNew(false);
    setForm({ ingredient_name: '', quantity: '', unit: '', requester_name: '', purpose: '', remark: '' });
    setSubmitting(false);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={CSS.sectionTitle}>领用记录</span>
        <button style={CSS.primaryBtn} onClick={() => setShowNew(true)}>+ 新建领用</button>
      </div>

      {records.map(r => (
        <div key={r.id} style={CSS.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={CSS.label}>{r.created_at}</div>
              <div style={CSS.sublabel}>领用人：{r.requester_name} · {r.items_count} 个品项</div>
            </div>
            <span style={CSS.statusBadge(r.status)}>{STATUS_LABEL[r.status]}</span>
          </div>
        </div>
      ))}

      {records.length === 0 && (
        <div style={{ textAlign: 'center', padding: 48, color: '#B4B2A9', fontSize: 17 }}>暂无领用记录</div>
      )}

      {showNew && (
        <div style={CSS.modal} onClick={(e) => e.target === e.currentTarget && setShowNew(false)}>
          <div style={CSS.modalBody}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>新建领用单</h2>
              <button style={{ ...CSS.secondaryBtn, minHeight: 40 }} onClick={() => setShowNew(false)}>取消</button>
            </div>

            {[
              { label: '品项名称 *', key: 'ingredient_name', placeholder: '如：可乐 330ml' },
              { label: '数量 *', key: 'quantity', placeholder: '数字', type: 'number' },
              { label: '单位', key: 'unit', placeholder: '如：箱、瓶' },
              { label: '领用人', key: 'requester_name', placeholder: '员工姓名' },
              { label: '用途', key: 'purpose', placeholder: '如：补吧台库存' },
              { label: '备注', key: 'remark', placeholder: '可选' },
            ].map(({ label, key, placeholder, type }) => (
              <div key={key} style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 6 }}>{label}</div>
                <input
                  type={type ?? 'text'}
                  placeholder={placeholder}
                  value={form[key as keyof typeof form]}
                  onChange={(e) => setForm(prev => ({ ...prev, [key]: e.target.value }))}
                  style={CSS.input}
                />
              </div>
            ))}

            <button
              style={{ ...CSS.primaryBtn, width: '100%', marginTop: 4 }}
              disabled={submitting || !form.ingredient_name || !form.quantity}
              onClick={handleSubmit}
            >
              {submitting ? '提交中…' : '提交领用单'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 调拨单 Tab ───────────────────────────────────────────────────────────────

function TransferTab({ storeId }: { storeId: string }) {
  const [records, setRecords] = useState<TransferRecord[]>([]);
  const [showNew, setShowNew] = useState(false);
  const [form, setForm] = useState({
    ingredient_name: '', quantity: '', unit: '', to_store_id: '', to_store_name: '', remark: '',
  });
  const [submitting, setSubmitting] = useState(false);

  const loadRecords = useCallback(async () => {
    try {
      const res = await txFetch<{ ok: boolean; data: { items: TransferRecord[] } }>(
        `/api/v1/transfers?from_store_id=${storeId}`
      );
      if (res.ok && res.data?.items) { setRecords(res.data.items); return; }
    } catch { /* fall through */ }
    setRecords(MOCK_TRANSFERS);
  }, [storeId]);

  useEffect(() => { void loadRecords(); }, [loadRecords]);

  const handleSubmit = async () => {
    if (!form.ingredient_name || !form.quantity) return;
    setSubmitting(true);
    try {
      await txFetch('/api/v1/transfers', {
        method: 'POST',
        body: JSON.stringify({
          from_store_id: storeId,
          to_store_id: form.to_store_id || 'unknown',
          items: [{
            ingredient_id: `manual_${Date.now()}`,
            ingredient_name: form.ingredient_name,
            requested_quantity: parseFloat(form.quantity),
            unit: form.unit,
          }],
          notes: form.remark,
        }),
      });
    } catch { /* 降级 */ }
    setRecords(prev => [{
      id: `local_${Date.now()}`,
      created_at: new Date().toLocaleString('zh'),
      to_store_name: form.to_store_name || '目标门店',
      items_count: 1,
      status: 'pending',
    }, ...prev]);
    setShowNew(false);
    setForm({ ingredient_name: '', quantity: '', unit: '', to_store_id: '', to_store_name: '', remark: '' });
    setSubmitting(false);
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={CSS.sectionTitle}>调拨记录</span>
        <button style={CSS.primaryBtn} onClick={() => setShowNew(true)}>+ 新建调拨</button>
      </div>

      {records.map(r => (
        <div key={r.id} style={CSS.card}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={CSS.label}>{r.created_at}</div>
              <div style={CSS.sublabel}>调往：{r.to_store_name} · {r.items_count} 个品项</div>
            </div>
            <span style={CSS.statusBadge(r.status)}>{STATUS_LABEL[r.status]}</span>
          </div>
        </div>
      ))}

      {records.length === 0 && (
        <div style={{ textAlign: 'center', padding: 48, color: '#B4B2A9', fontSize: 17 }}>暂无调拨记录</div>
      )}

      {showNew && (
        <div style={CSS.modal} onClick={(e) => e.target === e.currentTarget && setShowNew(false)}>
          <div style={CSS.modalBody}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
              <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>新建调拨单</h2>
              <button style={{ ...CSS.secondaryBtn, minHeight: 40 }} onClick={() => setShowNew(false)}>取消</button>
            </div>

            {[
              { label: '品项名称 *', key: 'ingredient_name', placeholder: '如：百威啤酒' },
              { label: '数量 *', key: 'quantity', placeholder: '数字', type: 'number' },
              { label: '单位', key: 'unit', placeholder: '如：箱、瓶' },
              { label: '目标门店名称', key: 'to_store_name', placeholder: '如：河东店' },
              { label: '目标门店 ID（可选）', key: 'to_store_id', placeholder: 'UUID' },
              { label: '备注', key: 'remark', placeholder: '调拨原因' },
            ].map(({ label, key, placeholder, type }) => (
              <div key={key} style={{ marginBottom: 14 }}>
                <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 6 }}>{label}</div>
                <input
                  type={type ?? 'text'}
                  placeholder={placeholder}
                  value={form[key as keyof typeof form]}
                  onChange={(e) => setForm(prev => ({ ...prev, [key]: e.target.value }))}
                  style={CSS.input}
                />
              </div>
            ))}

            <button
              style={{ ...CSS.primaryBtn, width: '100%', marginTop: 4 }}
              disabled={submitting || !form.ingredient_name || !form.quantity}
              onClick={handleSubmit}
            >
              {submitting ? '提交中…' : '提交调拨单'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── 盘点报表 Tab ─────────────────────────────────────────────────────────────

function ReportTab({ storeId }: { storeId: string }) {
  const [items, setItems] = useState<ReportItem[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const end = new Date().toISOString().slice(0, 10);
      const start = new Date(Date.now() - 30 * 86400 * 1000).toISOString().slice(0, 10);
      const res = await txFetch<{ ok: boolean; data: { items: ReportItem[] } }>(
        `/api/v1/supply/inventory/report?store_id=${storeId}&start_date=${start}&end_date=${end}`
      );
      if (res.ok && res.data?.items) {
        setItems(res.data.items);
        setLoading(false);
        return;
      }
    } catch { /* 降级 */ }
    setItems(MOCK_REPORT);
    setLoading(false);
  }, [storeId]);

  useEffect(() => { void load(); }, [load]);

  const totalLoss = items.reduce((s, r) => s + r.loss_fen, 0);
  const totalGain = items.reduce((s, r) => s + r.gain_fen, 0);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={CSS.sectionTitle}>近 30 天盘点损益</span>
        <button style={CSS.secondaryBtn} onClick={load}>刷新</button>
      </div>

      {/* 汇总卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        <div style={{ ...CSS.card, borderLeft: '4px solid #0F6E56', marginBottom: 0 }}>
          <div style={{ fontSize: 14, color: '#5F5E5A', marginBottom: 4 }}>盘盈金额</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: '#0F6E56' }}>
            +¥{(totalGain / 100).toFixed(2)}
          </div>
        </div>
        <div style={{ ...CSS.card, borderLeft: '4px solid #A32D2D', marginBottom: 0 }}>
          <div style={{ fontSize: 14, color: '#5F5E5A', marginBottom: 4 }}>盘亏金额</div>
          <div style={{ fontSize: 24, fontWeight: 700, color: '#A32D2D' }}>
            -¥{(totalLoss / 100).toFixed(2)}
          </div>
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 32, color: '#B4B2A9', fontSize: 17 }}>加载中…</div>
      )}

      {!loading && items.length > 0 && (
        <div style={CSS.card}>
          {/* 表头 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 80px 80px 80px 80px', gap: 8,
            padding: '8px 0', borderBottom: '2px solid #E8E6E1', fontSize: 14, color: '#5F5E5A', fontWeight: 600 }}>
            <span>品项</span>
            <span style={{ textAlign: 'right' }}>盈数量</span>
            <span style={{ textAlign: 'right' }}>亏数量</span>
            <span style={{ textAlign: 'right' }}>盈金额</span>
            <span style={{ textAlign: 'right' }}>亏金额</span>
          </div>
          {items.map((item, idx) => (
            <div key={idx} style={{ display: 'grid', gridTemplateColumns: '1fr 80px 80px 80px 80px',
              gap: 8, padding: '12px 0', borderBottom: '1px solid #F0EDE6', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 500 }}>{item.name}</div>
                <div style={{ fontSize: 13, color: '#B4B2A9' }}>{item.unit}</div>
              </div>
              <span style={{ textAlign: 'right', fontSize: 16, color: '#0F6E56', fontWeight: item.gain_qty > 0 ? 600 : 400 }}>
                {item.gain_qty > 0 ? `+${item.gain_qty}` : '-'}
              </span>
              <span style={{ textAlign: 'right', fontSize: 16, color: '#A32D2D', fontWeight: item.loss_qty > 0 ? 600 : 400 }}>
                {item.loss_qty > 0 ? `-${item.loss_qty}` : '-'}
              </span>
              <span style={{ textAlign: 'right', fontSize: 15, color: '#0F6E56' }}>
                {item.gain_fen > 0 ? `+¥${(item.gain_fen / 100).toFixed(0)}` : '-'}
              </span>
              <span style={{ textAlign: 'right', fontSize: 15, color: '#A32D2D' }}>
                {item.loss_fen > 0 ? `-¥${(item.loss_fen / 100).toFixed(0)}` : '-'}
              </span>
            </div>
          ))}
        </div>
      )}

      {!loading && items.length === 0 && (
        <div style={{ textAlign: 'center', padding: 48, color: '#B4B2A9', fontSize: 17 }}>暂无盘点数据</div>
      )}
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

const STORE_ID: string =
  (window as unknown as Record<string, unknown>).__STORE_ID__ as string || 'default-store';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'inventory',   label: '库存状况' },
  { key: 'stocktake',  label: '盘点单' },
  { key: 'requisition', label: '领用单' },
  { key: 'transfer',   label: '调拨单' },
  { key: 'report',     label: '盘点报表' },
];

export function BarCounterPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('inventory');

  return (
    <div style={CSS.page}>
      {/* 顶部导航 */}
      <div style={CSS.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            style={{ background: 'transparent', border: 'none', color: '#FFFFFF', fontSize: 22,
              cursor: 'pointer', padding: '0 4px', minHeight: 44, minWidth: 44 }}
            onClick={() => window.history.back()}
          >
            ←
          </button>
          <h1 style={CSS.headerTitle}>吧台盘点</h1>
        </div>
        <span style={{ fontSize: 13, color: '#8899A6' }}>
          {new Date().toLocaleDateString('zh', { month: 'long', day: 'numeric', weekday: 'short' })}
        </span>
      </div>

      {/* Tab 栏 */}
      <div style={CSS.tabBar}>
        {TABS.map(tab => (
          <button
            key={tab.key}
            style={CSS.tabBtn(activeTab === tab.key)}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div style={CSS.content}>
        {activeTab === 'inventory'   && <InventoryTab   storeId={STORE_ID} />}
        {activeTab === 'stocktake'  && <StocktakeTab   storeId={STORE_ID} />}
        {activeTab === 'requisition' && <RequisitionTab storeId={STORE_ID} />}
        {activeTab === 'transfer'   && <TransferTab    storeId={STORE_ID} />}
        {activeTab === 'report'     && <ReportTab      storeId={STORE_ID} />}
      </div>
    </div>
  );
}
