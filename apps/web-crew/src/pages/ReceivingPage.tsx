/**
 * 移动收货 — 3步向导：基本信息 → 货品录入 → 确认提交
 */
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  red: '#ef4444',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
};

interface ReceivingItem {
  ingredient_name: string;
  unit: string;
  ordered_qty: number | null;
  received_qty: number | null;
  unit_price: number | null;
  discrepancy_note: string;
}


function NavBar({ title, step, onBack }: { title: string; step: string; onBack: () => void }) {
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 10,
      background: C.bg, borderBottom: `1px solid ${C.border}`,
      display: 'flex', alignItems: 'center', padding: '0 16px',
      height: 56,
    }}>
      <button onClick={onBack} style={{
        background: 'none', border: 'none', color: C.text, fontSize: 22,
        cursor: 'pointer', padding: '8px 8px 8px 0', minWidth: 48, minHeight: 48,
        display: 'flex', alignItems: 'center',
      }}>←</button>
      <span style={{ flex: 1, fontSize: 17, fontWeight: 700, color: C.white }}>{title}</span>
      <span style={{ fontSize: 14, color: C.muted }}>{step}</span>
    </div>
  );
}

function Step1({
  supplierName, setSupplierName,
  notes, setNotes,
  onNext,
}: {
  supplierName: string; setSupplierName: (v: string) => void;
  notes: string; setNotes: (v: string) => void;
  onNext: () => void;
}) {
  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>供应商名称</div>
        <input
          type="text"
          placeholder="输入供应商名称..."
          value={supplierName}
          onChange={e => setSupplierName(e.target.value)}
          style={{
            width: '100%', boxSizing: 'border-box',
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 10, padding: '14px 16px',
            fontSize: 16, color: C.white, outline: 'none',
            minHeight: 52,
          }}
        />
      </div>
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: 16, color: C.muted, marginBottom: 8 }}>备注</div>
        <textarea
          placeholder="可选备注..."
          value={notes}
          onChange={e => setNotes(e.target.value)}
          rows={3}
          style={{
            width: '100%', boxSizing: 'border-box', resize: 'none',
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 10, padding: '14px 16px',
            fontSize: 16, color: C.white, outline: 'none',
          }}
        />
      </div>
      <button
        onClick={onNext}
        disabled={!supplierName.trim()}
        style={{
          width: '100%', height: 52,
          background: supplierName.trim() ? C.accent : C.border,
          border: 'none', borderRadius: 12,
          fontSize: 17, fontWeight: 700, color: C.white,
          cursor: supplierName.trim() ? 'pointer' : 'not-allowed',
        }}
      >
        下一步 →
      </button>
    </div>
  );
}

function ItemRow({
  item, onChange,
}: {
  item: ReceivingItem;
  onChange: (updated: ReceivingItem) => void;
}) {
  const hasDiscrepancy = item.ordered_qty !== null && item.received_qty !== null
    && item.received_qty !== item.ordered_qty;
  const diff = item.ordered_qty !== null && item.received_qty !== null
    ? item.received_qty - item.ordered_qty : 0;

  return (
    <div style={{
      background: C.card, borderRadius: 12, padding: 14, marginBottom: 12,
      border: `1px solid ${hasDiscrepancy ? C.red : C.border}`,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 17, fontWeight: 600, color: C.white }}>{item.ingredient_name}</span>
        <span style={{ fontSize: 14, color: C.muted }}>{item.unit}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 4 }}>采购单</div>
          <div style={{ fontSize: 16, color: C.muted }}>
            {item.ordered_qty !== null ? `${item.ordered_qty}${item.unit}` : '—'}
          </div>
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 4 }}>实收</div>
          <input
            type="number"
            inputMode="decimal"
            placeholder="0"
            value={item.received_qty ?? ''}
            onChange={e => onChange({ ...item, received_qty: e.target.value ? Number(e.target.value) : null })}
            style={{
              width: '100%', boxSizing: 'border-box',
              background: '#0B1A20', border: `1px solid ${hasDiscrepancy ? C.red : C.border}`,
              borderRadius: 8, padding: '10px 12px',
              fontSize: 18, fontWeight: 700, color: C.white, outline: 'none',
              minHeight: 48, textAlign: 'center',
            }}
          />
        </div>
      </div>
      {hasDiscrepancy && (
        <div style={{
          marginTop: 10, padding: '8px 12px',
          background: `${C.red}18`, borderRadius: 8,
          fontSize: 14, color: C.red,
        }}>
          差异 {diff > 0 ? '+' : ''}{diff}{item.unit}
          <input
            type="text"
            placeholder="差异备注（可选）"
            value={item.discrepancy_note}
            onChange={e => onChange({ ...item, discrepancy_note: e.target.value })}
            style={{
              display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 6,
              background: '#0B1A20', border: `1px solid ${C.red}60`,
              borderRadius: 6, padding: '6px 10px',
              fontSize: 14, color: C.text, outline: 'none',
            }}
          />
        </div>
      )}
      {!hasDiscrepancy && item.received_qty !== null && (
        <div style={{ marginTop: 8, fontSize: 13, color: C.green }}>✓ 数量一致</div>
      )}
    </div>
  );
}

function Step2({
  items, setItems,
  photoCount,
  onAddItem,
  onPhoto,
  onNext,
}: {
  items: ReceivingItem[];
  setItems: (items: ReceivingItem[]) => void;
  photoCount: number;
  onAddItem: () => void;
  onPhoto: () => void;
  onNext: () => void;
}) {
  const updateItem = (idx: number, updated: ReceivingItem) => {
    const next = [...items];
    next[idx] = updated;
    setItems(next);
  };

  return (
    <div style={{ padding: 16 }}>
      {items.map((item, idx) => (
        <ItemRow key={idx} item={item} onChange={u => updateItem(idx, u)} />
      ))}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <button
          onClick={onAddItem}
          style={{
            flex: 1, height: 48,
            background: C.card, border: `1px dashed ${C.accent}`,
            borderRadius: 10, fontSize: 16, color: C.accent,
            cursor: 'pointer',
          }}
        >
          + 添加货品
        </button>
        <button
          onClick={onPhoto}
          style={{
            flex: 1, height: 48,
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 10, fontSize: 16, color: C.text,
            cursor: 'pointer',
          }}
        >
          {photoCount > 0 ? `📷 ${photoCount}张` : '📷 拍照留证'}
        </button>
      </div>
      <button
        onClick={onNext}
        style={{
          width: '100%', height: 52,
          background: C.accent, border: 'none', borderRadius: 12,
          fontSize: 17, fontWeight: 700, color: C.white, cursor: 'pointer',
        }}
      >
        下一步 →
      </button>
    </div>
  );
}

function Step3({
  supplierName, items, photoCount, notes,
  onSubmit, submitting,
}: {
  supplierName: string;
  items: ReceivingItem[];
  photoCount: number;
  notes: string;
  onSubmit: () => void;
  submitting: boolean;
}) {
  const discrepancyItems = items.filter(
    i => i.ordered_qty !== null && i.received_qty !== null && i.received_qty !== i.ordered_qty
  );

  return (
    <div style={{ padding: 16 }}>
      <div style={{
        background: C.card, borderRadius: 12, padding: 16, marginBottom: 16,
        border: `1px solid ${C.border}`,
      }}>
        <div style={{ fontSize: 14, color: C.muted, marginBottom: 4 }}>供应商</div>
        <div style={{ fontSize: 17, fontWeight: 600, color: C.white, marginBottom: 14 }}>{supplierName}</div>
        <div style={{ display: 'flex', gap: 16 }}>
          <div>
            <div style={{ fontSize: 14, color: C.muted }}>货品</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: C.white }}>{items.length} 项</div>
          </div>
          <div>
            <div style={{ fontSize: 14, color: C.muted }}>差异</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: discrepancyItems.length > 0 ? C.red : C.green }}>
              {discrepancyItems.length} 项
            </div>
          </div>
          {photoCount > 0 && (
            <div>
              <div style={{ fontSize: 14, color: C.muted }}>照片</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: C.white }}>📷 {photoCount}张</div>
            </div>
          )}
        </div>
      </div>

      {discrepancyItems.length > 0 && (
        <div style={{
          background: `${C.red}12`, border: `1px solid ${C.red}40`,
          borderRadius: 12, padding: 14, marginBottom: 16,
        }}>
          <div style={{ fontSize: 14, color: C.red, fontWeight: 600, marginBottom: 8 }}>差异明细</div>
          {discrepancyItems.map((item, idx) => {
            const diff = (item.received_qty ?? 0) - (item.ordered_qty ?? 0);
            return (
              <div key={idx} style={{ fontSize: 14, color: C.text, marginBottom: 4 }}>
                · {item.ingredient_name} {diff > 0 ? '+' : ''}{diff}{item.unit}
                {item.discrepancy_note && <span style={{ color: C.muted }}> — {item.discrepancy_note}</span>}
              </div>
            );
          })}
        </div>
      )}

      {notes && (
        <div style={{
          background: C.card, borderRadius: 10, padding: 12, marginBottom: 16,
          border: `1px solid ${C.border}`,
          fontSize: 14, color: C.muted,
        }}>
          备注：{notes}
        </div>
      )}

      <button
        onClick={onSubmit}
        disabled={submitting}
        style={{
          width: '100%', height: 56,
          background: submitting ? C.border : C.accent,
          border: 'none', borderRadius: 12,
          fontSize: 18, fontWeight: 700, color: C.white,
          cursor: submitting ? 'not-allowed' : 'pointer',
        }}
      >
        {submitting ? '提交中...' : '确认收货并入库'}
      </button>
    </div>
  );
}

export function ReceivingPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [supplierName, setSupplierName] = useState('');
  const [notes, setNotes] = useState('');
  const [items, setItems] = useState<ReceivingItem[]>([]);
  const [photoCount, setPhotoCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    const storeId = (window as any).__STORE_ID__ || '';
    fetch(`/api/v1/supply/receiving/orders?store_id=${encodeURIComponent(storeId)}&status=pending`, {
      headers: { 'X-Tenant-ID': localStorage.getItem('tenant_id') ?? '' },
    })
      .then(res => {
        if (!res.ok) throw new Error(`获取收货单失败: ${res.status}`);
        return res.json();
      })
      .then(json => {
        const raw: Array<{
          ingredient_name: string;
          unit: string;
          ordered_qty: number | null;
          received_qty?: number | null;
          unit_price: number | null;
        }> = json?.data?.items ?? json?.items ?? [];
        setItems(raw.map(i => ({
          ingredient_name: i.ingredient_name,
          unit: i.unit,
          ordered_qty: i.ordered_qty,
          received_qty: i.received_qty ?? null,
          unit_price: i.unit_price,
          discrepancy_note: '',
        })));
      })
      .catch(err => {
        setLoadError(err instanceof Error ? err.message : '收货单加载失败');
      });
  }, []);

  const handleBack = () => {
    if (step === 1) navigate(-1);
    else setStep(s => s - 1);
  };

  const handlePhoto = () => {
    setPhotoCount(c => c + 1);
    alert('开发模式：已模拟拍照');
  };

  const handleAddItem = () => {
    const name = prompt('货品名称：');
    if (!name?.trim()) return;
    const unit = prompt('单位（如 kg / 个 / 箱）：') || 'kg';
    setItems(prev => [...prev, {
      ingredient_name: name.trim(),
      unit,
      ordered_qty: null,
      received_qty: null,
      unit_price: null,
      discrepancy_note: '',
    }]);
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      const storeId = (window as any).__STORE_ID__ || '';
      const res = await fetch('/api/v1/supply/receiving/orders', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Tenant-ID': localStorage.getItem('tenant_id') ?? '',
        },
        body: JSON.stringify({
          store_id: storeId,
          supplier_name: supplierName,
          notes,
          items,
        }),
      });
      if (!res.ok) throw new Error(`提交失败: ${res.status}`);
      alert('收货成功！库存已更新。');
      navigate(-1);
    } catch (err) {
      alert(err instanceof Error ? err.message : '提交收货单失败，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  const titles = ['移动收货', '货品录入', '确认收货'];
  const stepLabels = ['步骤 1/3', '步骤 2/3', '步骤 3/3'];

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.white }}>
      <NavBar title={titles[step - 1]} step={stepLabels[step - 1]} onBack={handleBack} />
      {loadError && (
        <div style={{
          margin: '12px 16px 0', padding: '10px 14px',
          background: 'rgba(186,117,23,0.12)', border: '1px solid #BA7517',
          borderRadius: 10, fontSize: 14, color: '#BA7517',
        }}>
          {loadError}
        </div>
      )}
      {step === 1 && (
        <Step1
          supplierName={supplierName} setSupplierName={setSupplierName}
          notes={notes} setNotes={setNotes}
          onNext={() => setStep(2)}
        />
      )}
      {step === 2 && (
        <Step2
          items={items} setItems={setItems}
          photoCount={photoCount}
          onAddItem={handleAddItem}
          onPhoto={handlePhoto}
          onNext={() => setStep(3)}
        />
      )}
      {step === 3 && (
        <Step3
          supplierName={supplierName}
          items={items}
          photoCount={photoCount}
          notes={notes}
          onSubmit={handleSubmit}
          submitting={submitting}
        />
      )}
    </div>
  );
}
