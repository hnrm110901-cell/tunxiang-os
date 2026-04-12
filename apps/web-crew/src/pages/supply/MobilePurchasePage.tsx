/**
 * 移动采购申请 — 扫码/手动采购申请 + 申请列表+状态跟踪
 *
 * 路由: /supply/purchase
 * 角色: 店长 / 采购员
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { txFetch } from '../../api/index';

// ─── 设计 token ──────────────────────────────────────────

const C = {
  bg: '#0B1A20',
  card: '#112228',
  border: '#1a2a33',
  accent: '#FF6B35',
  green: '#22c55e',
  red: '#ef4444',
  yellow: '#f59e0b',
  muted: '#64748b',
  text: '#e2e8f0',
  white: '#ffffff',
};

// ─── 类型定义 ────────────────────────────────────────────

interface PurchaseRequest {
  id: string;
  ingredient_name: string;
  quantity: number;
  unit: string;
  unit_price_fen: number;
  supplier_name?: string;
  status: 'pending' | 'approved' | 'rejected' | 'received';
  created_at: string;
  notes?: string;
}

type ViewMode = 'list' | 'new';

// ─── 工具函数 ────────────────────────────────────────────

function fmtPrice(fen: number): string {
  return `¥${(fen / 100).toFixed(2)}`;
}

function statusLabel(s: PurchaseRequest['status']): { text: string; color: string } {
  const map: Record<PurchaseRequest['status'], { text: string; color: string }> = {
    pending: { text: '待审批', color: C.yellow },
    approved: { text: '已审批', color: C.green },
    rejected: { text: '已拒绝', color: C.red },
    received: { text: '已收货', color: C.muted },
  };
  return map[s] ?? { text: s, color: C.muted };
}

// ─── 子组件：导航栏 ──────────────────────────────────────

function NavBar({
  title,
  onBack,
  right,
}: {
  title: string;
  onBack: () => void;
  right?: React.ReactNode;
}) {
  return (
    <div
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 10,
        background: C.bg,
        borderBottom: `1px solid ${C.border}`,
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        height: 56,
      }}
    >
      <button
        onClick={onBack}
        style={{
          background: 'none',
          border: 'none',
          color: C.text,
          fontSize: 22,
          cursor: 'pointer',
          padding: '8px 8px 8px 0',
          minWidth: 48,
          minHeight: 48,
          display: 'flex',
          alignItems: 'center',
        }}
      >
        ←
      </button>
      <span style={{ flex: 1, fontSize: 17, fontWeight: 700, color: C.white }}>
        {title}
      </span>
      {right}
    </div>
  );
}

// ─── 子组件：状态标签 ────────────────────────────────────

function StatusBadge({ status }: { status: PurchaseRequest['status'] }) {
  const { text, color } = statusLabel(status);
  return (
    <span
      style={{
        fontSize: 12,
        color,
        border: `1px solid ${color}`,
        borderRadius: 4,
        padding: '2px 6px',
      }}
    >
      {text}
    </span>
  );
}

// ─── 子组件：采购申请卡片 ─────────────────────────────────

function RequestCard({ req }: { req: PurchaseRequest }) {
  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        padding: 14,
        marginBottom: 10,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 16, fontWeight: 700, color: C.white, flex: 1 }}>
          {req.ingredient_name}
        </span>
        <StatusBadge status={req.status} />
      </div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 14, color: C.muted }}>
          数量：
          <span style={{ color: C.text }}>
            {req.quantity} {req.unit}
          </span>
        </span>
        <span style={{ fontSize: 14, color: C.muted }}>
          单价：<span style={{ color: C.text }}>{fmtPrice(req.unit_price_fen)}</span>
        </span>
        {req.supplier_name && (
          <span style={{ fontSize: 14, color: C.muted }}>
            供应商：<span style={{ color: C.text }}>{req.supplier_name}</span>
          </span>
        )}
      </div>
      {req.notes && (
        <div style={{ marginTop: 6, fontSize: 13, color: C.muted }}>备注：{req.notes}</div>
      )}
      <div style={{ marginTop: 6, fontSize: 12, color: C.muted }}>
        {new Date(req.created_at).toLocaleString('zh-CN')}
      </div>
    </div>
  );
}

// ─── 子组件：新建采购申请表单 ─────────────────────────────

interface NewPurchaseFormProps {
  onSuccess: () => void;
  onCancel: () => void;
}

function NewPurchaseForm({ onSuccess, onCancel }: NewPurchaseFormProps) {
  const [barcode, setBarcode] = useState('');
  const [ingredientName, setIngredientName] = useState('');
  const [quantity, setQuantity] = useState('');
  const [unit, setUnit] = useState('kg');
  const [unitPriceYuan, setUnitPriceYuan] = useState('');
  const [supplierName, setSupplierName] = useState('');
  const [notes, setNotes] = useState('');
  const [scanning, setScanning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  // 调用 TXBridge 扫码（安卓 POS 环境）
  const handleScan = useCallback(() => {
    if (window.TXBridge) {
      setScanning(true);
      // TXBridge.scan() 结果通过回调写入
      (window as unknown as Record<string, unknown>)['__txScanCallback'] = (result: string) => {
        setBarcode(result);
        setScanning(false);
      };
      window.TXBridge.scan();
    } else {
      // 非安卓环境：提示手动输入
      setError('当前设备不支持扫码，请手动输入条码');
    }
  }, []);

  const handleSubmit = useCallback(async () => {
    if (!ingredientName.trim()) {
      setError('请输入食材名称');
      return;
    }
    const qty = parseFloat(quantity);
    if (!qty || qty <= 0) {
      setError('请输入有效数量');
      return;
    }
    const priceYuan = parseFloat(unitPriceYuan);
    if (isNaN(priceYuan) || priceYuan < 0) {
      setError('请输入有效单价');
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      await txFetch('/api/v1/supply/mobile/purchase-request', {
        method: 'POST',
        body: JSON.stringify({
          store_id: localStorage.getItem('tx_store_id') || '',
          barcode: barcode || undefined,
          ingredient_name: ingredientName.trim(),
          quantity: qty,
          unit,
          unit_price_fen: Math.round(priceYuan * 100),
          supplier_name: supplierName.trim() || undefined,
          requested_by: localStorage.getItem('tx_operator_id') || undefined,
          notes: notes.trim() || undefined,
        }),
      });
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败，请重试');
    } finally {
      setSubmitting(false);
    }
  }, [barcode, ingredientName, quantity, unit, unitPriceYuan, supplierName, notes, onSuccess]);

  const inputStyle: React.CSSProperties = {
    width: '100%',
    background: C.bg,
    border: `1px solid ${C.border}`,
    borderRadius: 8,
    padding: '10px 12px',
    fontSize: 16,
    color: C.white,
    outline: 'none',
    boxSizing: 'border-box',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: 14,
    color: C.muted,
    marginBottom: 6,
    display: 'block',
  };

  return (
    <div style={{ padding: '16px 16px 90px' }}>
      {/* 条码扫描 */}
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>条形码（可选）</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            value={barcode}
            onChange={(e) => setBarcode(e.target.value)}
            placeholder="扫码或手动输入"
          />
          <button
            onClick={handleScan}
            disabled={scanning}
            style={{
              background: C.accent,
              border: 'none',
              borderRadius: 8,
              color: C.white,
              fontSize: 14,
              fontWeight: 600,
              padding: '0 14px',
              cursor: 'pointer',
              minHeight: 44,
              whiteSpace: 'nowrap',
            }}
          >
            {scanning ? '扫描中…' : '扫码'}
          </button>
        </div>
      </div>

      {/* 食材名称 */}
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>
          食材名称 <span style={{ color: C.red }}>*</span>
        </label>
        <input
          style={inputStyle}
          value={ingredientName}
          onChange={(e) => setIngredientName(e.target.value)}
          placeholder="如：五花肉"
        />
      </div>

      {/* 数量 + 单位 */}
      <div style={{ marginBottom: 16, display: 'flex', gap: 8 }}>
        <div style={{ flex: 2 }}>
          <label style={labelStyle}>
            数量 <span style={{ color: C.red }}>*</span>
          </label>
          <input
            style={inputStyle}
            type="number"
            inputMode="decimal"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            placeholder="0.00"
          />
        </div>
        <div style={{ flex: 1 }}>
          <label style={labelStyle}>单位</label>
          <select
            style={{ ...inputStyle, cursor: 'pointer' }}
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
          >
            {['kg', 'g', '斤', '个', '箱', '袋', '瓶', '升', 'L'].map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 单价 */}
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>
          预估单价（元） <span style={{ color: C.red }}>*</span>
        </label>
        <input
          style={inputStyle}
          type="number"
          inputMode="decimal"
          value={unitPriceYuan}
          onChange={(e) => setUnitPriceYuan(e.target.value)}
          placeholder="0.00"
        />
      </div>

      {/* 供应商 */}
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>供应商（可选）</label>
        <input
          style={inputStyle}
          value={supplierName}
          onChange={(e) => setSupplierName(e.target.value)}
          placeholder="供应商名称"
        />
      </div>

      {/* 备注 */}
      <div style={{ marginBottom: 16 }}>
        <label style={labelStyle}>备注</label>
        <textarea
          style={{
            ...inputStyle,
            resize: 'none',
            height: 72,
          }}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="可选备注"
        />
      </div>

      {error && (
        <div
          style={{
            background: '#3b0f0f',
            border: `1px solid ${C.red}`,
            borderRadius: 8,
            padding: '10px 12px',
            color: C.red,
            fontSize: 14,
            marginBottom: 16,
          }}
        >
          {error}
        </div>
      )}

      {/* 底部按钮 */}
      <div
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          display: 'flex',
          gap: 10,
          padding: '12px 16px',
          background: C.bg,
          borderTop: `1px solid ${C.border}`,
        }}
      >
        <button
          onClick={onCancel}
          style={{
            flex: 1,
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: 10,
            color: C.text,
            fontSize: 16,
            fontWeight: 600,
            height: 48,
            cursor: 'pointer',
          }}
        >
          取消
        </button>
        <button
          onClick={handleSubmit}
          disabled={submitting}
          style={{
            flex: 2,
            background: submitting ? C.muted : C.accent,
            border: 'none',
            borderRadius: 10,
            color: C.white,
            fontSize: 16,
            fontWeight: 700,
            height: 48,
            cursor: submitting ? 'not-allowed' : 'pointer',
          }}
        >
          {submitting ? '提交中…' : '提交申请'}
        </button>
      </div>
    </div>
  );
}

// ─── 主页面 ──────────────────────────────────────────────

export function MobilePurchasePage() {
  const navigate = useNavigate();
  const [view, setView] = useState<ViewMode>('list');
  const [requests, setRequests] = useState<PurchaseRequest[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [error, setError] = useState('');

  const loadRequests = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      const storeId = localStorage.getItem('tx_store_id');
      if (storeId) params.set('store_id', storeId);
      if (statusFilter) params.set('status', statusFilter);
      const data = await txFetch<{ items: PurchaseRequest[]; total: number }>(
        `/api/v1/supply/mobile/purchase-requests?${params}`,
      );
      setRequests(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    if (view === 'list') loadRequests();
  }, [view, loadRequests]);

  if (view === 'new') {
    return (
      <div style={{ background: C.bg, minHeight: '100vh' }}>
        <NavBar
          title="新建采购申请"
          onBack={() => setView('list')}
        />
        <NewPurchaseForm
          onSuccess={() => {
            setView('list');
          }}
          onCancel={() => setView('list')}
        />
      </div>
    );
  }

  // 列表视图
  const filterTabs: Array<{ label: string; value: string }> = [
    { label: '全部', value: '' },
    { label: '待审批', value: 'pending' },
    { label: '已审批', value: 'approved' },
    { label: '已收货', value: 'received' },
  ];

  return (
    <div style={{ background: C.bg, minHeight: '100vh' }}>
      <NavBar
        title="移动采购申请"
        onBack={() => navigate(-1)}
        right={
          <button
            onClick={() => setView('new')}
            style={{
              background: C.accent,
              border: 'none',
              borderRadius: 8,
              color: C.white,
              fontSize: 14,
              fontWeight: 600,
              padding: '6px 14px',
              cursor: 'pointer',
            }}
          >
            + 新建
          </button>
        }
      />

      {/* 状态筛选 */}
      <div
        style={{
          display: 'flex',
          gap: 0,
          borderBottom: `1px solid ${C.border}`,
          overflowX: 'auto',
        }}
      >
        {filterTabs.map((tab) => (
          <button
            key={tab.value}
            onClick={() => setStatusFilter(tab.value)}
            style={{
              flex: 1,
              minWidth: 70,
              background: 'none',
              border: 'none',
              borderBottom: statusFilter === tab.value ? `2px solid ${C.accent}` : '2px solid transparent',
              color: statusFilter === tab.value ? C.accent : C.muted,
              fontSize: 14,
              fontWeight: statusFilter === tab.value ? 700 : 400,
              padding: '12px 4px',
              cursor: 'pointer',
              transition: 'color 0.15s',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 列表内容 */}
      <div style={{ padding: '12px 14px 80px' }}>
        {loading && (
          <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 15 }}>
            加载中…
          </div>
        )}
        {error && !loading && (
          <div
            style={{
              background: '#3b0f0f',
              border: `1px solid ${C.red}`,
              borderRadius: 8,
              padding: '12px 14px',
              color: C.red,
              fontSize: 14,
              marginBottom: 12,
            }}
          >
            {error}
            <button
              onClick={loadRequests}
              style={{
                marginLeft: 12,
                background: 'none',
                border: 'none',
                color: C.accent,
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              重试
            </button>
          </div>
        )}
        {!loading && !error && requests.length === 0 && (
          <div style={{ textAlign: 'center', padding: '48px 0', color: C.muted }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>📦</div>
            <div style={{ fontSize: 15 }}>暂无采购申请</div>
          </div>
        )}
        {requests.map((req) => (
          <RequestCard key={req.id} req={req} />
        ))}
        {total > requests.length && (
          <div style={{ textAlign: 'center', fontSize: 13, color: C.muted, padding: '12px 0' }}>
            共 {total} 条，已显示 {requests.length} 条
          </div>
        )}
      </div>
    </div>
  );
}

export default MobilePurchasePage;
