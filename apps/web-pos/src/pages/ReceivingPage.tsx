/**
 * 食材收货页面 — 按采购单或快速收货
 * 流程: 选择模式 → 输入/选择采购单 → 逐项验收 → 确认签收
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  fetchPurchaseOrders,
  searchIngredients,
  createReceivingOrder,
  inspectReceivingItem,
  completeReceiving,
  listReceivingOrders,
  type PurchaseOrder,
  type PurchaseOrderItem,
  type IngredientOption,
  type ReceivingOrder,
} from '../api/supplyApi';

const STORE_ID = import.meta.env.VITE_STORE_ID || '';
const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

type Mode = 'select' | 'po-list' | 'inspect' | 'quick' | 'done' | 'log';

/* ── 检验行 ── */
interface InspectRow {
  itemId: string;
  ingredientId: string;
  name: string;
  orderedQty: number;
  unit: string;
  unitPriceFen: number;
  receivedQty: number;
  quality: 'pass' | 'partial' | 'reject';
  batchNo: string;
  expiryDate: string;
}

/* ── 快速收货行 ── */
interface QuickRow {
  ingredientId: string;
  name: string;
  unit: string;
  qty: number;
  supplier: string;
  batchNo: string;
  expiryDate: string;
}

export function ReceivingPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>('select');

  // PO 模式
  const [poList, setPoList] = useState<PurchaseOrder[]>([]);
  const [poLoading, setPoLoading] = useState(false);
  const [poSearch, setPoSearch] = useState('');
  const [selectedPo, setSelectedPo] = useState<PurchaseOrder | null>(null);
  const [inspectRows, setInspectRows] = useState<InspectRow[]>([]);

  // 快速收货
  const [ingredients, setIngredients] = useState<IngredientOption[]>([]);
  const [ingSearch, setIngSearch] = useState('');
  const [quickRows, setQuickRows] = useState<QuickRow[]>([]);
  const [quickSupplier, setQuickSupplier] = useState('');

  // 提交
  const [receiverName, setReceiverName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ReceivingOrder | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 今日记录
  const [todayLogs, setTodayLogs] = useState<ReceivingOrder[]>([]);
  const [logLoading, setLogLoading] = useState(false);

  /* ── 加载采购单 ── */
  const loadPOs = useCallback(async () => {
    setPoLoading(true);
    try {
      const data = await fetchPurchaseOrders(STORE_ID, 'pending', poSearch);
      setPoList(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载采购单失败');
    } finally {
      setPoLoading(false);
    }
  }, [poSearch]);

  /* ── 加载食材列表 ── */
  const loadIngredients = useCallback(async () => {
    try {
      const data = await searchIngredients(STORE_ID, ingSearch);
      setIngredients(data.items);
    } catch { /* ignore */ }
  }, [ingSearch]);

  /* ── 选择采购单 → 填充验收行 ── */
  const selectPO = (po: PurchaseOrder) => {
    setSelectedPo(po);
    setInspectRows(po.items.map((item: PurchaseOrderItem) => ({
      itemId: item.item_id,
      ingredientId: item.ingredient_id,
      name: item.ingredient_name,
      orderedQty: item.ordered_qty,
      unit: item.unit,
      unitPriceFen: item.unit_price_fen,
      receivedQty: item.ordered_qty, // 默认全收
      quality: 'pass' as const,
      batchNo: '',
      expiryDate: '',
    })));
    setMode('inspect');
  };

  /* ── 提交采购单收货 ── */
  const submitPOReceiving = async () => {
    if (!selectedPo || !receiverName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const ro = await createReceivingOrder({
        store_id: STORE_ID,
        supplier_id: selectedPo.supplier_id,
        procurement_order_id: selectedPo.po_id,
        receiver_id: receiverName,
        items: inspectRows.map(r => ({
          ingredient_id: r.ingredientId,
          ingredient_name: r.name,
          expected_quantity: r.orderedQty,
          expected_unit: r.unit,
          unit_price_fen: r.unitPriceFen,
        })),
      });
      // 逐项验收
      for (const row of inspectRows) {
        const matchItem = ro.items.find(i => i.ingredient_id === row.ingredientId);
        if (matchItem) {
          await inspectReceivingItem(ro.order_id, matchItem.item_id, {
            actual_quantity: row.receivedQty,
            accepted_quantity: row.quality === 'reject' ? 0 : row.receivedQty,
            batch_no: row.batchNo || undefined,
            expiry_date: row.expiryDate || undefined,
            rejection_reason: row.quality === 'reject' ? '质量不合格' : undefined,
          });
        }
      }
      const completed = await completeReceiving(ro.order_id, STORE_ID, receiverName);
      setResult(completed);
      setMode('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  /* ── 提交快速收货 ── */
  const submitQuickReceiving = async () => {
    if (quickRows.length === 0 || !receiverName.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const ro = await createReceivingOrder({
        store_id: STORE_ID,
        receiver_id: receiverName,
        items: quickRows.map(r => ({
          ingredient_id: r.ingredientId,
          ingredient_name: r.name,
          expected_quantity: r.qty,
          expected_unit: r.unit,
        })),
      });
      for (const row of quickRows) {
        const matchItem = ro.items.find(i => i.ingredient_id === row.ingredientId);
        if (matchItem) {
          await inspectReceivingItem(ro.order_id, matchItem.item_id, {
            actual_quantity: row.qty,
            accepted_quantity: row.qty,
            batch_no: row.batchNo || undefined,
            expiry_date: row.expiryDate || undefined,
          });
        }
      }
      const completed = await completeReceiving(ro.order_id, STORE_ID, receiverName);
      setResult(completed);
      setMode('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  /* ── 加载今日记录 ── */
  const loadTodayLogs = useCallback(async () => {
    setLogLoading(true);
    try {
      const today = new Date().toISOString().slice(0, 10);
      const data = await listReceivingOrders(STORE_ID, today, today);
      setTodayLogs(data.items);
    } catch { /* ignore */ } finally {
      setLogLoading(false);
    }
  }, []);

  /* ── 更新验收行 ── */
  const updateRow = (idx: number, field: keyof InspectRow, value: string | number) => {
    setInspectRows(prev => prev.map((r, i) => i === idx ? { ...r, [field]: value } : r));
  };

  /* ── 添加快速收货行 ── */
  const addQuickRow = (ing: IngredientOption) => {
    if (quickRows.some(r => r.ingredientId === ing.ingredient_id)) return;
    setQuickRows(prev => [...prev, {
      ingredientId: ing.ingredient_id,
      name: ing.name,
      unit: ing.unit,
      qty: 1,
      supplier: quickSupplier,
      batchNo: '',
      expiryDate: '',
    }]);
  };

  const updateQuickRow = (idx: number, field: keyof QuickRow, value: string | number) => {
    setQuickRows(prev => prev.map((r, i) => i === idx ? { ...r, [field]: value } : r));
  };

  const removeQuickRow = (idx: number) => {
    setQuickRows(prev => prev.filter((_, i) => i !== idx));
  };

  return (
    <div style={{ minHeight: '100vh', background: '#0B1A20', color: '#fff', fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif' }}>
      {/* 顶部栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 20px', borderBottom: '1px solid #1a2a33' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button onClick={() => mode === 'select' ? navigate('/tables') : setMode('select')} style={backBtn}>
            {'<'} {mode === 'select' ? '返回' : '返回选择'}
          </button>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>食材收货</h2>
        </div>
        <button onClick={() => { setMode('log'); loadTodayLogs(); }} style={{ ...backBtn, background: '#1a2a33' }}>
          今日记录
        </button>
      </div>

      <div style={{ padding: 20, maxWidth: 900, margin: '0 auto' }}>
        {error && (
          <div style={{ background: 'rgba(255,77,79,0.15)', border: '1px solid #ff4d4f', borderRadius: 8, padding: 12, marginBottom: 16, color: '#ff4d4f' }}>
            {error}
            <button onClick={() => setError(null)} style={{ marginLeft: 12, background: 'none', border: 'none', color: '#ff4d4f', cursor: 'pointer', textDecoration: 'underline' }}>关闭</button>
          </div>
        )}

        {/* ── 模式选择 ── */}
        {mode === 'select' && (
          <div style={{ display: 'flex', gap: 20, marginTop: 40 }}>
            <ModeCard title="按采购单收货" desc="选择待收采购单，逐项验收数量和质量" icon="📋" onClick={() => { setMode('po-list'); loadPOs(); }} />
            <ModeCard title="快速收货" desc="无采购单，手动录入食材、数量和供应商" icon="⚡" onClick={() => { setMode('quick'); loadIngredients(); }} />
          </div>
        )}

        {/* ── 采购单列表 ── */}
        {mode === 'po-list' && (
          <div>
            <input
              placeholder="搜索采购单号或供应商..."
              value={poSearch}
              onChange={e => setPoSearch(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && loadPOs()}
              style={inputStyle}
            />
            {poLoading && <div style={{ textAlign: 'center', padding: 40, color: '#8A94A4' }}>加载中...</div>}
            {!poLoading && poList.length === 0 && <div style={{ textAlign: 'center', padding: 40, color: '#666' }}>无待收采购单</div>}
            {poList.map(po => (
              <button key={po.po_id} onClick={() => selectPO(po)} style={poCardStyle}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontSize: 18, fontWeight: 700 }}>{po.po_no}</span>
                  <span style={{ color: '#8A94A4' }}>{po.created_at?.slice(0, 10)}</span>
                </div>
                <div style={{ color: '#8A94A4' }}>供应商: {po.supplier_name} | {po.items.length} 种食材</div>
              </button>
            ))}
          </div>
        )}

        {/* ── 验收明细 ── */}
        {mode === 'inspect' && selectedPo && (
          <div>
            <div style={{ ...cardStyle, marginBottom: 16 }}>
              <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>采购单 {selectedPo.po_no}</div>
              <div style={{ color: '#8A94A4' }}>供应商: {selectedPo.supplier_name} | {inspectRows.length} 项</div>
            </div>

            {inspectRows.map((row, idx) => (
              <div key={row.itemId} style={{ ...cardStyle, marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                  <span style={{ fontSize: 17, fontWeight: 600 }}>{row.name}</span>
                  <span style={{ color: '#8A94A4' }}>订购: {row.orderedQty}{row.unit} | {fen2yuan(row.unitPriceFen)}/{row.unit}</span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
                  <div>
                    <label style={labelStyle}>实收数量</label>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <button onClick={() => updateRow(idx, 'receivedQty', Math.max(0, row.receivedQty - 1))} style={qtyBtn}>-</button>
                      <input type="number" value={row.receivedQty} onChange={e => updateRow(idx, 'receivedQty', Number(e.target.value))} style={{ ...inputStyle, width: 70, textAlign: 'center', padding: '8px 4px' }} />
                      <button onClick={() => updateRow(idx, 'receivedQty', row.receivedQty + 1)} style={{ ...qtyBtn, background: '#FF6B2C' }}>+</button>
                    </div>
                  </div>
                  <div>
                    <label style={labelStyle}>质量</label>
                    <select value={row.quality} onChange={e => updateRow(idx, 'quality', e.target.value)} style={{ ...inputStyle, padding: '10px 8px' }}>
                      <option value="pass">合格</option>
                      <option value="partial">部分合格</option>
                      <option value="reject">不合格</option>
                    </select>
                  </div>
                  <div>
                    <label style={labelStyle}>批次号</label>
                    <input placeholder="可选" value={row.batchNo} onChange={e => updateRow(idx, 'batchNo', e.target.value)} style={inputStyle} />
                  </div>
                </div>
              </div>
            ))}

            {/* 签收人 + 提交 */}
            <div style={{ ...cardStyle, marginTop: 20 }}>
              <label style={labelStyle}>收货人姓名 *</label>
              <input value={receiverName} onChange={e => setReceiverName(e.target.value)} placeholder="输入签收人姓名" style={{ ...inputStyle, marginBottom: 16 }} />
              <button onClick={submitPOReceiving} disabled={submitting || !receiverName.trim()} style={{
                ...actionBtn, background: submitting || !receiverName.trim() ? '#333' : '#FF6B2C',
                cursor: submitting || !receiverName.trim() ? 'not-allowed' : 'pointer',
              }}>
                {submitting ? '提交中...' : '确认收货'}
              </button>
            </div>
          </div>
        )}

        {/* ── 快速收货 ── */}
        {mode === 'quick' && (
          <div>
            <div style={{ ...cardStyle, marginBottom: 16 }}>
              <label style={labelStyle}>供应商</label>
              <input value={quickSupplier} onChange={e => setQuickSupplier(e.target.value)} placeholder="输入供应商名称" style={inputStyle} />
            </div>

            <div style={{ ...cardStyle, marginBottom: 16 }}>
              <label style={labelStyle}>添加食材</label>
              <input placeholder="搜索食材名称..." value={ingSearch} onChange={e => { setIngSearch(e.target.value); loadIngredients(); }} style={inputStyle} />
              {ingredients.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
                  {ingredients.slice(0, 12).map(ing => (
                    <button key={ing.ingredient_id} onClick={() => addQuickRow(ing)} style={{
                      padding: '8px 14px', borderRadius: 8, border: '1px solid #1a2a33',
                      background: quickRows.some(r => r.ingredientId === ing.ingredient_id) ? '#FF6B2C22' : '#112228',
                      color: '#fff', cursor: 'pointer', fontSize: 15,
                    }}>
                      {ing.name} ({ing.unit})
                    </button>
                  ))}
                </div>
              )}
            </div>

            {quickRows.map((row, idx) => (
              <div key={row.ingredientId} style={{ ...cardStyle, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 17, fontWeight: 600 }}>{row.name}</div>
                  <div style={{ color: '#8A94A4', fontSize: 14 }}>{row.unit}</div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <button onClick={() => updateQuickRow(idx, 'qty', Math.max(0.5, row.qty - 1))} style={qtyBtn}>-</button>
                  <input type="number" value={row.qty} onChange={e => updateQuickRow(idx, 'qty', Number(e.target.value))} style={{ ...inputStyle, width: 60, textAlign: 'center', padding: '8px 4px' }} />
                  <button onClick={() => updateQuickRow(idx, 'qty', row.qty + 1)} style={{ ...qtyBtn, background: '#FF6B2C' }}>+</button>
                </div>
                <input placeholder="批次" value={row.batchNo} onChange={e => updateQuickRow(idx, 'batchNo', e.target.value)} style={{ ...inputStyle, width: 80, padding: '8px 6px' }} />
                <button onClick={() => removeQuickRow(idx)} style={{ background: 'none', border: 'none', color: '#ff4d4f', fontSize: 20, cursor: 'pointer' }}>✕</button>
              </div>
            ))}

            {quickRows.length > 0 && (
              <div style={{ ...cardStyle, marginTop: 20 }}>
                <div style={{ marginBottom: 12, color: '#8A94A4' }}>{quickRows.length} 种食材，共 {quickRows.reduce((s, r) => s + r.qty, 0)} 单位</div>
                <label style={labelStyle}>收货人姓名 *</label>
                <input value={receiverName} onChange={e => setReceiverName(e.target.value)} placeholder="输入签收人姓名" style={{ ...inputStyle, marginBottom: 16 }} />
                <button onClick={submitQuickReceiving} disabled={submitting || !receiverName.trim()} style={{
                  ...actionBtn, background: submitting || !receiverName.trim() ? '#333' : '#FF6B2C',
                  cursor: submitting || !receiverName.trim() ? 'not-allowed' : 'pointer',
                }}>
                  {submitting ? '提交中...' : '确认收货'}
                </button>
              </div>
            )}
          </div>
        )}

        {/* ── 完成 ── */}
        {mode === 'done' && result && (
          <div style={{ textAlign: 'center', paddingTop: 60 }}>
            <div style={{ fontSize: 64, marginBottom: 16 }}>✓</div>
            <div style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>收货完成</div>
            <div style={{ color: '#8A94A4', marginBottom: 24 }}>
              收货单号: {result.order_id.slice(0, 8)} | {result.items.length} 项 | {fen2yuan(result.total_accepted_value_fen)}
            </div>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
              <button onClick={() => { setMode('select'); setResult(null); setSelectedPo(null); setInspectRows([]); setQuickRows([]); setReceiverName(''); }} style={{ ...actionBtn, background: '#FF6B2C' }}>
                继续收货
              </button>
              <button onClick={() => navigate('/tables')} style={{ ...actionBtn, background: '#1a2a33', border: '1px solid #333' }}>
                返回桌台
              </button>
            </div>
          </div>
        )}

        {/* ── 今日记录 ── */}
        {mode === 'log' && (
          <div>
            <h3 style={{ margin: '0 0 16px', fontSize: 20 }}>今日收货记录</h3>
            {logLoading && <div style={{ textAlign: 'center', padding: 40, color: '#8A94A4' }}>加载中...</div>}
            {!logLoading && todayLogs.length === 0 && <div style={{ textAlign: 'center', padding: 40, color: '#666' }}>今日暂无收货记录</div>}
            {todayLogs.map(log => (
              <div key={log.order_id} style={{ ...cardStyle, marginBottom: 12 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontWeight: 600 }}>{log.order_id.slice(0, 8)}</span>
                  <span style={{ padding: '2px 10px', borderRadius: 10, fontSize: 13, background: log.status === 'completed' ? 'rgba(82,196,26,0.15)' : 'rgba(250,173,20,0.15)', color: log.status === 'completed' ? '#52c41a' : '#faad14' }}>
                    {log.status === 'completed' ? '已完成' : log.status}
                  </span>
                </div>
                <div style={{ color: '#8A94A4', fontSize: 14 }}>
                  {log.items.length} 项 | {fen2yuan(log.total_accepted_value_fen)} | {log.completed_at?.slice(11, 16) || log.created_at?.slice(11, 16)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── 模式选择卡片 ── */
function ModeCard({ title, desc, icon, onClick }: { title: string; desc: string; icon: string; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      flex: 1, padding: 32, borderRadius: 16, background: '#112228', border: '2px solid #1a2a33',
      color: '#fff', cursor: 'pointer', textAlign: 'center', transition: 'border-color 200ms',
    }}
      onPointerEnter={e => { e.currentTarget.style.borderColor = '#FF6B2C'; }}
      onPointerLeave={e => { e.currentTarget.style.borderColor = '#1a2a33'; }}
    >
      <div style={{ fontSize: 48, marginBottom: 12 }}>{icon}</div>
      <div style={{ fontSize: 22, fontWeight: 700, marginBottom: 8 }}>{title}</div>
      <div style={{ fontSize: 16, color: '#8A94A4' }}>{desc}</div>
    </button>
  );
}

/* ── 样式常量 ── */
const cardStyle: React.CSSProperties = { background: '#112228', borderRadius: 12, padding: 20 };
const inputStyle: React.CSSProperties = { width: '100%', padding: '12px 14px', borderRadius: 8, border: '1px solid #1a2a33', background: '#0B1A20', color: '#fff', fontSize: 16, outline: 'none', boxSizing: 'border-box' };
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 14, color: '#8A94A4', marginBottom: 6 };
const qtyBtn: React.CSSProperties = { width: 40, height: 40, borderRadius: 8, border: 'none', background: '#1a2a33', color: '#fff', fontSize: 20, fontWeight: 700, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' };
const actionBtn: React.CSSProperties = { width: '100%', padding: 16, borderRadius: 12, border: 'none', color: '#fff', fontSize: 18, fontWeight: 700, cursor: 'pointer', minHeight: 56 };
const backBtn: React.CSSProperties = { minHeight: 44, padding: '8px 16px', background: '#112228', border: '1px solid #1a2a33', borderRadius: 8, color: '#fff', fontSize: 16, cursor: 'pointer' };
const poCardStyle: React.CSSProperties = { width: '100%', padding: 20, marginBottom: 10, borderRadius: 12, background: '#112228', border: '2px solid #1a2a33', color: '#fff', textAlign: 'left', cursor: 'pointer' };
