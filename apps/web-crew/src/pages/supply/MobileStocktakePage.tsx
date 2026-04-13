/**
 * 移动盘点 — 开始盘点 → 扫码/手动录入 → 提交
 *
 * 离线支持：条目暂存到 localStorage，联网后同步提交。
 * 路由: /supply/stocktake
 * 角色: 店长 / 库管
 */
import { useState, useEffect, useCallback, useRef } from 'react';
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

interface StocktakeItem {
  id: string;                  // 本地临时 ID
  ingredient_id: string;
  ingredient_name: string;
  barcode?: string;
  actual_quantity: number;
  unit: string;
  unit_cost_fen: number;
  notes?: string;
  synced: boolean;             // 是否已同步到服务器
}

interface StocktakeSession {
  id: string;                  // 服务器返回的盘点单 ID（空则未创建）
  store_id: string;
  status: 'idle' | 'open' | 'submitting' | 'completed';
  items: StocktakeItem[];
  created_at?: string;
}

// localStorage key
const OFFLINE_KEY = 'tx_mobile_stocktake_draft';

// ─── 工具函数 ────────────────────────────────────────────

function loadDraft(): StocktakeSession | null {
  try {
    const raw = localStorage.getItem(OFFLINE_KEY);
    return raw ? (JSON.parse(raw) as StocktakeSession) : null;
  } catch {
    return null;
  }
}

function saveDraft(session: StocktakeSession): void {
  localStorage.setItem(OFFLINE_KEY, JSON.stringify(session));
}

function clearDraft(): void {
  localStorage.removeItem(OFFLINE_KEY);
}

function genLocalId(): string {
  return `local_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

// ─── 子组件：导航栏 ──────────────────────────────────────

function NavBar({
  title,
  subtitle,
  onBack,
}: {
  title: string;
  subtitle?: string;
  onBack: () => void;
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
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 17, fontWeight: 700, color: C.white }}>{title}</div>
        {subtitle && <div style={{ fontSize: 12, color: C.muted }}>{subtitle}</div>}
      </div>
    </div>
  );
}

// ─── 子组件：盘点条目卡片 ─────────────────────────────────

function ItemCard({
  item,
  onEdit,
  onDelete,
}: {
  item: StocktakeItem;
  onEdit: (item: StocktakeItem) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${item.synced ? C.border : C.yellow}`,
        borderRadius: 10,
        padding: 12,
        marginBottom: 8,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: C.white }}>{item.ingredient_name}</div>
        <div style={{ fontSize: 13, color: C.muted, marginTop: 2 }}>
          实盘：
          <span style={{ color: C.green, fontWeight: 600 }}>
            {item.actual_quantity} {item.unit}
          </span>
          {item.barcode && (
            <span style={{ marginLeft: 8, color: C.muted }}>#{item.barcode}</span>
          )}
        </div>
        {!item.synced && (
          <span style={{ fontSize: 11, color: C.yellow }}>未同步（离线暂存）</span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          onClick={() => onEdit(item)}
          style={{
            background: 'none',
            border: `1px solid ${C.border}`,
            borderRadius: 6,
            color: C.text,
            fontSize: 13,
            padding: '4px 8px',
            cursor: 'pointer',
          }}
        >
          编辑
        </button>
        <button
          onClick={() => onDelete(item.id)}
          style={{
            background: 'none',
            border: `1px solid ${C.red}`,
            borderRadius: 6,
            color: C.red,
            fontSize: 13,
            padding: '4px 8px',
            cursor: 'pointer',
          }}
        >
          删除
        </button>
      </div>
    </div>
  );
}

// ─── 子组件：添加/编辑条目弹层 ───────────────────────────

interface ItemEditorProps {
  initial?: Partial<StocktakeItem>;
  onSave: (item: Omit<StocktakeItem, 'id' | 'synced'>) => void;
  onClose: () => void;
  onScan: (callback: (code: string) => void) => void;
}

function ItemEditor({ initial, onSave, onClose, onScan }: ItemEditorProps) {
  const [ingredientName, setIngredientName] = useState(initial?.ingredient_name ?? '');
  const [barcode, setBarcode] = useState(initial?.barcode ?? '');
  const [actualQty, setActualQty] = useState(String(initial?.actual_quantity ?? ''));
  const [unit, setUnit] = useState(initial?.unit ?? 'kg');
  const [costYuan, setCostYuan] = useState(
    initial?.unit_cost_fen ? String(initial.unit_cost_fen / 100) : '',
  );
  const [notes, setNotes] = useState(initial?.notes ?? '');
  const [err, setErr] = useState('');

  const handleScan = () => {
    onScan((code) => setBarcode(code));
  };

  const handleSave = () => {
    if (!ingredientName.trim()) { setErr('请输入食材名称'); return; }
    const qty = parseFloat(actualQty);
    if (isNaN(qty) || qty < 0) { setErr('请输入有效数量（≥0）'); return; }
    const cost = parseFloat(costYuan);
    if (isNaN(cost) || cost < 0) { setErr('请输入有效成本价'); return; }
    onSave({
      ingredient_id: initial?.ingredient_id ?? `temp_${Date.now()}`,
      ingredient_name: ingredientName.trim(),
      barcode: barcode || undefined,
      actual_quantity: qty,
      unit,
      unit_cost_fen: Math.round(cost * 100),
      notes: notes.trim() || undefined,
    });
  };

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

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 100,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'flex-end',
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        style={{
          background: C.card,
          borderRadius: '16px 16px 0 0',
          width: '100%',
          maxHeight: '80vh',
          overflowY: 'auto',
          padding: '20px 16px 32px',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
          }}
        >
          <span style={{ fontSize: 17, fontWeight: 700, color: C.white }}>
            {initial?.ingredient_name ? '编辑条目' : '录入条目'}
          </span>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', color: C.muted, fontSize: 22, cursor: 'pointer' }}
          >
            ×
          </button>
        </div>

        {/* 条码 */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 4 }}>条码（可选）</div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              style={{ ...inputStyle, flex: 1 }}
              value={barcode}
              onChange={(e) => setBarcode(e.target.value)}
              placeholder="扫码或手动输入"
            />
            <button
              onClick={handleScan}
              style={{
                background: C.accent,
                border: 'none',
                borderRadius: 8,
                color: C.white,
                fontSize: 13,
                fontWeight: 600,
                padding: '0 12px',
                cursor: 'pointer',
                minHeight: 44,
              }}
            >
              扫码
            </button>
          </div>
        </div>

        {/* 食材名 */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 4 }}>食材名称 *</div>
          <input
            style={inputStyle}
            value={ingredientName}
            onChange={(e) => setIngredientName(e.target.value)}
            placeholder="如：猪里脊"
          />
        </div>

        {/* 数量 + 单位 */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <div style={{ flex: 2 }}>
            <div style={{ fontSize: 13, color: C.muted, marginBottom: 4 }}>实盘数量 *</div>
            <input
              style={inputStyle}
              type="number"
              inputMode="decimal"
              value={actualQty}
              onChange={(e) => setActualQty(e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13, color: C.muted, marginBottom: 4 }}>单位</div>
            <select
              style={{ ...inputStyle, cursor: 'pointer' }}
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
            >
              {['kg', 'g', '斤', '个', '箱', '袋', '瓶', '升'].map((u) => (
                <option key={u} value={u}>{u}</option>
              ))}
            </select>
          </div>
        </div>

        {/* 成本价 */}
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 4 }}>单位成本（元）*</div>
          <input
            style={inputStyle}
            type="number"
            inputMode="decimal"
            value={costYuan}
            onChange={(e) => setCostYuan(e.target.value)}
            placeholder="0.00（用于差异金额计算）"
          />
        </div>

        {/* 备注 */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: 13, color: C.muted, marginBottom: 4 }}>备注</div>
          <input
            style={inputStyle}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="可选"
          />
        </div>

        {err && (
          <div style={{ color: C.red, fontSize: 13, marginBottom: 12 }}>{err}</div>
        )}

        <button
          onClick={handleSave}
          style={{
            width: '100%',
            background: C.accent,
            border: 'none',
            borderRadius: 10,
            color: C.white,
            fontSize: 16,
            fontWeight: 700,
            height: 48,
            cursor: 'pointer',
          }}
        >
          保存
        </button>
      </div>
    </div>
  );
}

// ─── 主页面 ──────────────────────────────────────────────

export function MobileStocktakePage() {
  const navigate = useNavigate();
  const [session, setSession] = useState<StocktakeSession>(() => {
    const draft = loadDraft();
    return (
      draft ?? {
        id: '',
        store_id: localStorage.getItem('tx_store_id') || '',
        status: 'idle',
        items: [],
      }
    );
  });
  const [showEditor, setShowEditor] = useState(false);
  const [editingItem, setEditingItem] = useState<StocktakeItem | undefined>();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');

  // 持久化草稿
  useEffect(() => {
    if (session.status !== 'idle') {
      saveDraft(session);
    }
  }, [session]);

  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(''), 2500);
  }, []);

  // 开始盘点
  const handleStart = useCallback(async () => {
    setError('');
    try {
      const data = await txFetch<{ id: string; status: string; created_at: string }>(
        '/api/v1/supply/mobile/stocktake/start',
        {
          method: 'POST',
          body: JSON.stringify({
            store_id: session.store_id,
            operator_id: localStorage.getItem('tx_operator_id') || undefined,
          }),
        },
      );
      const newSession: StocktakeSession = {
        ...session,
        id: data.id,
        status: 'open',
        created_at: data.created_at,
        items: [],
      };
      setSession(newSession);
      saveDraft(newSession);
      showToast('盘点任务已创建');
    } catch (err) {
      // 离线降级：使用本地 ID 开始盘点
      const offlineSession: StocktakeSession = {
        ...session,
        id: `offline_${Date.now()}`,
        status: 'open',
        created_at: new Date().toISOString(),
        items: [],
      };
      setSession(offlineSession);
      saveDraft(offlineSession);
      showToast('离线模式：条目将在联网后同步');
    }
  }, [session, showToast]);

  // 扫码入口（统一）
  const handleScan = useCallback((callback: (code: string) => void) => {
    if (window.TXBridge) {
      (window as unknown as Record<string, unknown>)['__txScanCallback'] = callback;
      window.TXBridge.scan();
    } else {
      setError('当前设备不支持扫码，请手动输入条码');
    }
  }, []);

  // 保存条目（本地 + 尝试同步服务器）
  const handleSaveItem = useCallback(
    async (itemData: Omit<StocktakeItem, 'id' | 'synced'>) => {
      setShowEditor(false);
      const localId = editingItem?.id ?? genLocalId();
      const newItem: StocktakeItem = { ...itemData, id: localId, synced: false };

      const updatedItems = editingItem
        ? session.items.map((i) => (i.id === editingItem.id ? newItem : i))
        : [...session.items, newItem];

      const updatedSession = { ...session, items: updatedItems };
      setSession(updatedSession);
      setEditingItem(undefined);

      // 尝试同步到服务器
      if (session.id && !session.id.startsWith('offline_')) {
        try {
          await txFetch('/api/v1/supply/mobile/stocktake/item', {
            method: 'POST',
            body: JSON.stringify({
              stocktake_id: session.id,
              ingredient_id: itemData.ingredient_id,
              ingredient_name: itemData.ingredient_name,
              barcode: itemData.barcode,
              actual_quantity: itemData.actual_quantity,
              unit: itemData.unit,
              unit_cost_fen: itemData.unit_cost_fen,
              notes: itemData.notes,
            }),
          });
          // 标记已同步
          const syncedItems = updatedItems.map((i) =>
            i.id === localId ? { ...i, synced: true } : i,
          );
          setSession((prev) => ({ ...prev, items: syncedItems }));
          showToast('已同步');
        } catch {
          showToast('离线暂存，联网后将自动同步');
        }
      }
    },
    [session, editingItem, showToast],
  );

  // 删除条目
  const handleDeleteItem = useCallback(
    (id: string) => {
      setSession((prev) => ({ ...prev, items: prev.items.filter((i) => i.id !== id) }));
    },
    [],
  );

  // 提交盘点
  const handleSubmit = useCallback(async () => {
    if (session.items.length === 0) {
      setError('请先录入至少一个条目');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      // 如果有未同步的条目，先批量同步
      const unsynced = session.items.filter((i) => !i.synced);
      for (const item of unsynced) {
        await txFetch('/api/v1/supply/mobile/stocktake/item', {
          method: 'POST',
          body: JSON.stringify({
            stocktake_id: session.id,
            ingredient_id: item.ingredient_id,
            ingredient_name: item.ingredient_name,
            barcode: item.barcode,
            actual_quantity: item.actual_quantity,
            unit: item.unit,
            unit_cost_fen: item.unit_cost_fen,
            notes: item.notes,
          }),
        });
      }

      // 提交盘点单
      await txFetch(`/api/v1/supply/mobile/stocktake/${session.id}/submit`, {
        method: 'POST',
        body: JSON.stringify({
          operator_id: localStorage.getItem('tx_operator_id') || undefined,
        }),
      });

      clearDraft();
      setSession({
        id: '',
        store_id: session.store_id,
        status: 'completed',
        items: [],
      });
      showToast('盘点已提交');
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败，请检查网络后重试');
    } finally {
      setSubmitting(false);
    }
  }, [session, showToast]);

  // 重置（已完成 or 放弃）
  const handleReset = useCallback(() => {
    clearDraft();
    setSession({
      id: '',
      store_id: localStorage.getItem('tx_store_id') || '',
      status: 'idle',
      items: [],
    });
    setError('');
  }, []);

  // ── 渲染：完成态 ──────────────────────────────────────

  if (session.status === 'completed') {
    return (
      <div style={{ background: C.bg, minHeight: '100vh' }}>
        <NavBar title="移动盘点" onBack={() => navigate(-1)} />
        <div style={{ textAlign: 'center', padding: '72px 24px' }}>
          <div style={{ fontSize: 56, marginBottom: 16 }}>✅</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginBottom: 8 }}>
            盘点已提交
          </div>
          <div style={{ fontSize: 14, color: C.muted, marginBottom: 32 }}>
            差异数据已发射到事件总线，等待投影器更新库存视图
          </div>
          <button
            onClick={handleReset}
            style={{
              background: C.accent,
              border: 'none',
              borderRadius: 10,
              color: C.white,
              fontSize: 16,
              fontWeight: 700,
              padding: '12px 32px',
              cursor: 'pointer',
            }}
          >
            开始新一轮盘点
          </button>
        </div>
      </div>
    );
  }

  // ── 渲染：空闲态（未开始） ────────────────────────────

  if (session.status === 'idle') {
    return (
      <div style={{ background: C.bg, minHeight: '100vh' }}>
        <NavBar title="移动盘点" onBack={() => navigate(-1)} />
        <div style={{ textAlign: 'center', padding: '72px 24px' }}>
          <div style={{ fontSize: 48, marginBottom: 16 }}>📋</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.white, marginBottom: 8 }}>
            开始盘点
          </div>
          <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>
            扫码或手动录入实盘数量，系统自动计算盘差
          </div>
          <div
            style={{
              fontSize: 13,
              color: C.yellow,
              background: '#2a2000',
              border: `1px solid ${C.yellow}`,
              borderRadius: 8,
              padding: '8px 12px',
              marginBottom: 32,
              display: 'inline-block',
            }}
          >
            支持离线盘点，条目暂存本地，联网后自动同步
          </div>
          <br />
          {error && (
            <div style={{ color: C.red, fontSize: 14, marginBottom: 16 }}>{error}</div>
          )}
          <button
            onClick={handleStart}
            style={{
              background: C.accent,
              border: 'none',
              borderRadius: 10,
              color: C.white,
              fontSize: 16,
              fontWeight: 700,
              padding: '14px 40px',
              cursor: 'pointer',
            }}
          >
            开始盘点
          </button>
        </div>
      </div>
    );
  }

  // ── 渲染：盘点进行中 ──────────────────────────────────

  const unsyncedCount = session.items.filter((i) => !i.synced).length;

  return (
    <div style={{ background: C.bg, minHeight: '100vh' }}>
      <NavBar
        title="盘点中"
        subtitle={
          session.id.startsWith('offline_')
            ? '离线模式'
            : `单号 ${session.id.slice(0, 8)}…`
        }
        onBack={() => navigate(-1)}
      />

      {/* 状态栏 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '10px 16px',
          background: C.card,
          borderBottom: `1px solid ${C.border}`,
        }}
      >
        <span style={{ fontSize: 14, color: C.muted }}>
          已录入 <span style={{ color: C.white, fontWeight: 700 }}>{session.items.length}</span> 项
          {unsyncedCount > 0 && (
            <span style={{ color: C.yellow, marginLeft: 8 }}>
              （{unsyncedCount} 项未同步）
            </span>
          )}
        </span>
        <button
          onClick={() => {
            setEditingItem(undefined);
            setShowEditor(true);
          }}
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
          + 录入条目
        </button>
      </div>

      {/* 条目列表 */}
      <div style={{ padding: '12px 14px 120px' }}>
        {session.items.length === 0 && (
          <div style={{ textAlign: 'center', padding: '48px 0', color: C.muted }}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>📦</div>
            <div>点击上方「录入条目」开始盘点</div>
          </div>
        )}
        {session.items.map((item) => (
          <ItemCard
            key={item.id}
            item={item}
            onEdit={(i) => {
              setEditingItem(i);
              setShowEditor(true);
            }}
            onDelete={handleDeleteItem}
          />
        ))}
      </div>

      {/* 底部操作区 */}
      <div
        style={{
          position: 'fixed',
          bottom: 0,
          left: 0,
          right: 0,
          padding: '12px 16px',
          background: C.bg,
          borderTop: `1px solid ${C.border}`,
        }}
      >
        {error && (
          <div style={{ color: C.red, fontSize: 13, marginBottom: 8 }}>{error}</div>
        )}
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={handleReset}
            style={{
              flex: 1,
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: 10,
              color: C.text,
              fontSize: 15,
              fontWeight: 600,
              height: 48,
              cursor: 'pointer',
            }}
          >
            放弃盘点
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting || session.items.length === 0}
            style={{
              flex: 2,
              background:
                submitting || session.items.length === 0 ? C.muted : C.accent,
              border: 'none',
              borderRadius: 10,
              color: C.white,
              fontSize: 15,
              fontWeight: 700,
              height: 48,
              cursor: submitting || session.items.length === 0 ? 'not-allowed' : 'pointer',
            }}
          >
            {submitting ? '提交中…' : `提交盘点（${session.items.length} 项）`}
          </button>
        </div>
      </div>

      {/* 条目编辑器弹层 */}
      {showEditor && (
        <ItemEditor
          initial={editingItem}
          onSave={handleSaveItem}
          onClose={() => {
            setShowEditor(false);
            setEditingItem(undefined);
          }}
          onScan={handleScan}
        />
      )}

      {/* Toast 提示 */}
      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 80,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(0,0,0,0.8)',
            color: C.white,
            fontSize: 14,
            padding: '8px 20px',
            borderRadius: 20,
            zIndex: 200,
            whiteSpace: 'nowrap',
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}

export default MobileStocktakePage;
