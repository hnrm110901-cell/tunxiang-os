/**
 * 打印机路由配置页面
 *
 * 功能：
 *  - 查看/添加/编辑/停用 门店打印机
 *  - 配置 菜品类别 → 打印机 路由规则
 *  - 测试打印
 *
 * URL: /printer-settings
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

// ─── 常量 ─────────────────────────────────────────────────────────────────────

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

const API_BASE = (window as any).__API_BASE__ || '';
const TENANT_ID = (window as any).__TENANT_ID__ || '';
const STORE_ID = (window as any).__STORE_ID__ || 'demo-store-id';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

type PrinterType = 'receipt' | 'kitchen' | 'label';
type ConnType = 'usb' | 'network' | 'bluetooth';

interface Printer {
  id: string;
  name: string;
  type: PrinterType;
  connection_type: ConnType;
  address: string | null;
  is_active: boolean;
  paper_width: 58 | 80;
}

interface PrinterRoute {
  id: string;
  printer_id: string;
  printer_name?: string;
  printer_type?: string;
  category_id: string | null;
  category_name: string | null;
  dish_tag: string | null;
  priority: number;
  is_default: boolean;
}

interface MenuCategory {
  id: string;
  name: string;
}

// ─── 翻译辅助 ─────────────────────────────────────────────────────────────────

const PRINTER_TYPE_LABEL: Record<PrinterType, string> = {
  receipt: '收银机',
  kitchen: '厨房打印机',
  label: '标签打印机',
};

const CONN_TYPE_LABEL: Record<ConnType, string> = {
  usb: 'USB',
  network: '网络',
  bluetooth: '蓝牙',
};

// ─── API 工具 ─────────────────────────────────────────────────────────────────

async function apiFetch(path: string, options: RequestInit = {}): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Tenant-ID': TENANT_ID,
      ...(options.headers || {}),
    },
  });
  const json = await res.json();
  if (!res.ok || !json.ok) {
    throw new Error(json.error?.message || json.detail || '请求失败');
  }
  return json.data;
}

// ─── 子组件：打印机卡片 ────────────────────────────────────────────────────────

interface PrinterCardProps {
  printer: Printer;
  onEdit: (p: Printer) => void;
  onTest: (id: string) => void;
  testingId: string | null;
}

function PrinterCard({ printer, onEdit, onTest, testingId }: PrinterCardProps) {
  const isTesting = testingId === printer.id;

  return (
    <div style={{
      background: C.card,
      borderRadius: 12,
      padding: 16,
      marginBottom: 12,
      border: `1px solid ${C.border}`,
      borderLeft: `4px solid ${printer.is_active ? C.accent : C.muted}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: C.white }}>{printer.name}</span>
            <span style={{
              fontSize: 12, fontWeight: 600, padding: '2px 8px', borderRadius: 20,
              background: printer.is_active ? `${C.accent}22` : `${C.muted}22`,
              color: printer.is_active ? C.accent : C.muted,
              border: `1px solid ${printer.is_active ? C.accent : C.muted}`,
            }}>
              {PRINTER_TYPE_LABEL[printer.type]}
            </span>
          </div>
          <div style={{ fontSize: 14, color: C.muted, marginTop: 4 }}>
            {CONN_TYPE_LABEL[printer.connection_type]}
            {printer.address ? ` · ${printer.address}` : ''}
            {` · 纸宽 ${printer.paper_width}mm`}
          </div>
        </div>
        {/* 状态指示灯 */}
        <div style={{
          width: 10, height: 10, borderRadius: '50%', flexShrink: 0, marginTop: 6,
          background: printer.is_active ? C.green : C.muted,
          boxShadow: printer.is_active ? `0 0 6px ${C.green}` : 'none',
        }} />
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
        <button
          onClick={() => onTest(printer.id)}
          disabled={isTesting || !printer.is_active}
          style={{
            flex: 1, minHeight: 44, borderRadius: 8,
            border: `1px solid ${C.border}`,
            background: 'transparent',
            color: isTesting ? C.muted : C.text,
            fontSize: 14, fontWeight: 600, cursor: isTesting ? 'default' : 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
          }}
        >
          {isTesting ? (
            <>
              <span style={{ fontSize: 16 }}>⏳</span>
              发送中...
            </>
          ) : (
            <>
              <span style={{ fontSize: 16 }}>🖨</span>
              测试打印
            </>
          )}
        </button>
        <button
          onClick={() => onEdit(printer)}
          style={{
            flex: 1, minHeight: 44, borderRadius: 8,
            border: `1px solid ${C.accent}`,
            background: 'transparent',
            color: C.accent,
            fontSize: 14, fontWeight: 600, cursor: 'pointer',
          }}
        >
          编辑
        </button>
      </div>
    </div>
  );
}

// ─── 子组件：路由规则行 ────────────────────────────────────────────────────────

interface RouteRowProps {
  route: PrinterRoute;
  onDelete: (id: string) => void;
}

function RouteRow({ route, onDelete }: RouteRowProps) {
  const label = route.is_default
    ? '所有菜品（默认兜底）'
    : route.category_name
    ? route.category_name
    : route.dish_tag
    ? `标签：${route.dish_tag}`
    : '全部';

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      background: C.card, borderRadius: 10, padding: '10px 14px',
      border: `1px solid ${C.border}`, marginBottom: 8,
      minHeight: 56,
    }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: C.white, marginBottom: 2 }}>
          {label}
        </div>
        <div style={{ fontSize: 12, color: C.muted }}>
          优先级 {route.priority}
        </div>
      </div>
      <span style={{ fontSize: 20, color: C.muted }}>→</span>
      <div style={{ flex: 1, minWidth: 0, textAlign: 'right' }}>
        <div style={{ fontSize: 15, fontWeight: 600, color: C.accent }}>
          {route.printer_name || route.printer_id.slice(0, 8)}
        </div>
        <div style={{ fontSize: 12, color: C.muted }}>
          {route.printer_type ? PRINTER_TYPE_LABEL[route.printer_type as PrinterType] : ''}
        </div>
      </div>
      <button
        onClick={() => onDelete(route.id)}
        style={{
          minWidth: 44, minHeight: 48, borderRadius: 8,
          border: 'none', background: `${C.red}18`,
          color: C.red, fontSize: 18, cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
        }}
      >
        ✕
      </button>
    </div>
  );
}

// ─── 子组件：底部Sheet ─────────────────────────────────────────────────────────

interface SheetProps {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}

function BottomSheet({ title, onClose, children }: SheetProps) {
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 100,
      background: 'rgba(0,0,0,0.6)',
      display: 'flex', flexDirection: 'column', justifyContent: 'flex-end',
    }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        background: C.card, borderRadius: '16px 16px 0 0',
        padding: '0 16px 32px',
        maxHeight: '90vh', overflowY: 'auto',
      }}>
        {/* 拖拽把手 */}
        <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0 8px' }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: C.border }} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: C.white }}>{title}</span>
          <button
            onClick={onClose}
            style={{
              minWidth: 44, minHeight: 44, border: 'none', background: 'transparent',
              color: C.muted, fontSize: 22, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ─── 子组件：按钮组选择器 ────────────────────────────────────────────────────

interface SegmentProps<T extends string | number> {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}

function SegmentControl<T extends string | number>({ label, value, options, onChange }: SegmentProps<T>) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>{label}</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {options.map(opt => (
          <button
            key={String(opt.value)}
            onClick={() => onChange(opt.value)}
            style={{
              flex: 1, minHeight: 44, borderRadius: 8, fontSize: 14, fontWeight: 600,
              border: `1px solid ${value === opt.value ? C.accent : C.border}`,
              background: value === opt.value ? `${C.accent}22` : 'transparent',
              color: value === opt.value ? C.accent : C.text,
              cursor: 'pointer',
            }}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

// ─── 子组件：表单输入 ─────────────────────────────────────────────────────────

interface FieldProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}

function FormField({ label, value, onChange, placeholder, type = 'text' }: FieldProps) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>{label}</div>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: '100%', minHeight: 48, borderRadius: 8, fontSize: 16,
          border: `1px solid ${C.border}`, background: '#0d1f27',
          color: C.text, padding: '0 14px', boxSizing: 'border-box',
          outline: 'none',
        }}
      />
    </div>
  );
}

// ─── 添加打印机 Sheet ──────────────────────────────────────────────────────────

interface AddPrinterSheetProps {
  editPrinter: Printer | null;
  onClose: () => void;
  onSaved: () => void;
}

function AddPrinterSheet({ editPrinter, onClose, onSaved }: AddPrinterSheetProps) {
  const [name, setName] = useState(editPrinter?.name || '');
  const [type, setType] = useState<PrinterType>(editPrinter?.type || 'receipt');
  const [connType, setConnType] = useState<ConnType>(editPrinter?.connection_type || 'network');
  const [address, setAddress] = useState(editPrinter?.address || '');
  const [paperWidth, setPaperWidth] = useState<58 | 80>(editPrinter?.paper_width || 80);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const isEdit = !!editPrinter;

  async function handleSave() {
    if (!name.trim()) { setError('请填写打印机名称'); return; }
    setSaving(true);
    setError('');
    try {
      const body = {
        store_id: STORE_ID,
        name: name.trim(),
        type,
        connection_type: connType,
        address: address.trim() || null,
        paper_width: paperWidth,
      };
      if (isEdit) {
        await apiFetch(`/api/v1/printers/${editPrinter.id}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        });
      } else {
        await apiFetch('/api/v1/printers', {
          method: 'POST',
          body: JSON.stringify(body),
        });
      }
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <BottomSheet title={isEdit ? '编辑打印机' : '添加打印机'} onClose={onClose}>
      <FormField
        label="打印机名称"
        value={name}
        onChange={setName}
        placeholder="如：前台收银机、后厨热菜"
      />
      <SegmentControl
        label="类型"
        value={type}
        options={[
          { value: 'receipt', label: '收银机' },
          { value: 'kitchen', label: '厨房打印机' },
          { value: 'label', label: '标签打印机' },
        ]}
        onChange={(v) => setType(v as PrinterType)}
      />
      <SegmentControl
        label="连接方式"
        value={connType}
        options={[
          { value: 'network', label: '网络' },
          { value: 'usb', label: 'USB' },
          { value: 'bluetooth', label: '蓝牙' },
        ]}
        onChange={(v) => setConnType(v as ConnType)}
      />
      <FormField
        label={connType === 'usb' ? '设备ID' : connType === 'network' ? 'IP 地址' : '设备地址'}
        value={address}
        onChange={setAddress}
        placeholder={connType === 'network' ? '192.168.1.100' : connType === 'usb' ? '/dev/usb/lp0' : 'XX:XX:XX:XX:XX:XX'}
      />
      <SegmentControl
        label="纸宽"
        value={paperWidth}
        options={[
          { value: 58, label: '58mm' },
          { value: 80, label: '80mm' },
        ]}
        onChange={(v) => setPaperWidth(v as 58 | 80)}
      />
      {error && (
        <div style={{ color: C.red, fontSize: 14, marginBottom: 12, textAlign: 'center' }}>
          {error}
        </div>
      )}
      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          width: '100%', minHeight: 52, borderRadius: 10, fontSize: 16, fontWeight: 700,
          border: 'none', background: saving ? C.muted : C.accent,
          color: C.white, cursor: saving ? 'default' : 'pointer',
        }}
      >
        {saving ? '保存中...' : '确认保存'}
      </button>
    </BottomSheet>
  );
}

// ─── 添加路由规则 Sheet ────────────────────────────────────────────────────────

interface AddRouteSheetProps {
  printers: Printer[];
  categories: MenuCategory[];
  onClose: () => void;
  onSaved: () => void;
}

function AddRouteSheet({ printers, categories, onClose, onSaved }: AddRouteSheetProps) {
  const [categoryId, setCategoryId] = useState<string>('');
  const [dishTag, setDishTag] = useState('');
  const [printerId, setPrinterId] = useState(printers[0]?.id || '');
  const [isDefault, setIsDefault] = useState(false);
  const [priority, setPriority] = useState('0');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const selectedCat = categories.find(c => c.id === categoryId);

  async function handleSave() {
    if (!printerId) { setError('请选择目标打印机'); return; }
    setSaving(true);
    setError('');
    try {
      await apiFetch('/api/v1/printers/routes', {
        method: 'POST',
        body: JSON.stringify({
          store_id: STORE_ID,
          printer_id: printerId,
          category_id: categoryId || null,
          category_name: selectedCat?.name || null,
          dish_tag: dishTag.trim() || null,
          priority: parseInt(priority) || 0,
          is_default: isDefault,
        }),
      });
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '保存失败');
    } finally {
      setSaving(false);
    }
  }

  return (
    <BottomSheet title="添加路由规则" onClose={onClose}>
      {/* 菜品类别选择 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>菜品类别</div>
        <select
          value={categoryId}
          onChange={e => { setCategoryId(e.target.value); if (e.target.value) setIsDefault(false); }}
          style={{
            width: '100%', minHeight: 48, borderRadius: 8, fontSize: 16,
            border: `1px solid ${C.border}`, background: '#0d1f27',
            color: categoryId ? C.text : C.muted, padding: '0 14px', boxSizing: 'border-box',
            outline: 'none', appearance: 'none',
          }}
        >
          <option value="">不限类别（全部）</option>
          {categories.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {/* 菜品标签 */}
      <FormField
        label="菜品标签（可选）"
        value={dishTag}
        onChange={setDishTag}
        placeholder="如：酒水、主食、甜品"
      />

      {/* 目标打印机 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 14, color: C.muted, marginBottom: 8 }}>目标打印机</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {printers.filter(p => p.is_active).map(p => (
            <button
              key={p.id}
              onClick={() => setPrinterId(p.id)}
              style={{
                minHeight: 52, borderRadius: 8, fontSize: 15, fontWeight: 600,
                border: `1px solid ${printerId === p.id ? C.accent : C.border}`,
                background: printerId === p.id ? `${C.accent}22` : 'transparent',
                color: printerId === p.id ? C.accent : C.text,
                cursor: 'pointer', textAlign: 'left', padding: '0 16px',
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              }}
            >
              <span>{p.name}</span>
              <span style={{ fontSize: 13, color: C.muted, fontWeight: 400 }}>
                {PRINTER_TYPE_LABEL[p.type]}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* 优先级 */}
      <FormField
        label="优先级（数字越大越优先）"
        value={priority}
        onChange={setPriority}
        type="number"
        placeholder="0"
      />

      {/* 默认兜底开关 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        minHeight: 52, background: C.bg, borderRadius: 10, padding: '0 16px',
        border: `1px solid ${C.border}`, marginBottom: 16, cursor: 'pointer',
      }}
        onClick={() => setIsDefault(!isDefault)}
      >
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, color: C.text }}>设为默认兜底规则</div>
          <div style={{ fontSize: 12, color: C.muted }}>未匹配其他规则时使用</div>
        </div>
        <div style={{
          width: 48, height: 28, borderRadius: 14,
          background: isDefault ? C.accent : C.border,
          position: 'relative', transition: 'background 0.2s',
          flexShrink: 0,
        }}>
          <div style={{
            width: 22, height: 22, borderRadius: '50%', background: C.white,
            position: 'absolute', top: 3,
            left: isDefault ? 23 : 3,
            transition: 'left 0.2s',
          }} />
        </div>
      </div>

      {error && (
        <div style={{ color: C.red, fontSize: 14, marginBottom: 12, textAlign: 'center' }}>
          {error}
        </div>
      )}
      <button
        onClick={handleSave}
        disabled={saving}
        style={{
          width: '100%', minHeight: 52, borderRadius: 10, fontSize: 16, fontWeight: 700,
          border: 'none', background: saving ? C.muted : C.accent,
          color: C.white, cursor: saving ? 'default' : 'pointer',
        }}
      >
        {saving ? '保存中...' : '确认添加'}
      </button>
    </BottomSheet>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export function PrinterSettingsPage() {
  const navigate = useNavigate();

  const [printers, setPrinters] = useState<Printer[]>([]);
  const [routes, setRoutes] = useState<PrinterRoute[]>([]);
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [showAddPrinter, setShowAddPrinter] = useState(false);
  const [editPrinter, setEditPrinter] = useState<Printer | null>(null);
  const [showAddRoute, setShowAddRoute] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [toast, setToast] = useState('');

  function showToast(msg: string) {
    setToast(msg);
    setTimeout(() => setToast(''), 3000);
  }

  const loadData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [ps, rs] = await Promise.all([
        apiFetch(`/api/v1/printers?store_id=${STORE_ID}`),
        apiFetch(`/api/v1/printers/routes?store_id=${STORE_ID}`),
      ]);
      setPrinters(ps as Printer[]);
      setRoutes(rs as PrinterRoute[]);

      // 加载菜品类别（如果 API 不存在则忽略错误）
      try {
        const cats = await apiFetch(`/api/v1/menu/categories?store_id=${STORE_ID}`);
        setCategories(Array.isArray(cats) ? cats : (cats?.items || []));
      } catch {
        // 菜品类别 API 不可用时不影响主功能
        setCategories([]);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '加载失败，请重试');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleTest(id: string) {
    setTestingId(id);
    try {
      await apiFetch(`/api/v1/printers/${id}/test`, { method: 'POST', body: '{}' });
      showToast('测试打印已发送');
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : '测试失败');
    } finally {
      setTimeout(() => setTestingId(null), 2000);
    }
  }

  async function handleDeleteRoute(routeId: string) {
    try {
      await apiFetch(`/api/v1/printers/routes/${routeId}`, { method: 'DELETE' });
      showToast('规则已删除');
      setRoutes(prev => prev.filter(r => r.id !== routeId));
    } catch (e: unknown) {
      showToast(e instanceof Error ? e.message : '删除失败');
    }
  }

  const activePrinters = printers.filter(p => p.is_active);

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.white, paddingBottom: 120 }}>

      {/* 顶部导航 */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 40,
        background: C.card, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', padding: '0 16px', height: 56,
      }}>
        <button
          onClick={() => navigate(-1)}
          style={{
            minWidth: 44, minHeight: 44, border: 'none', background: 'transparent',
            color: C.text, fontSize: 22, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center', marginLeft: -8,
          }}
        >
          ‹
        </button>
        <span style={{ fontSize: 18, fontWeight: 700, flex: 1 }}>打印机配置</span>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 40, color: C.muted, fontSize: 16 }}>
          加载中...
        </div>
      ) : error ? (
        <div style={{ textAlign: 'center', padding: 40 }}>
          <div style={{ color: C.red, fontSize: 16, marginBottom: 16 }}>{error}</div>
          <button
            onClick={loadData}
            style={{
              minHeight: 48, padding: '0 24px', borderRadius: 10,
              border: `1px solid ${C.accent}`, background: 'transparent',
              color: C.accent, fontSize: 15, fontWeight: 600, cursor: 'pointer',
            }}
          >
            重试
          </button>
        </div>
      ) : (
        <div style={{ padding: '16px 16px 0' }}>

          {/* ── Section 1: 打印机列表 ── */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 12,
          }}>
            <h2 style={{ fontSize: 17, fontWeight: 700, color: C.white, margin: 0 }}>
              已配置打印机
              <span style={{
                fontSize: 13, fontWeight: 400, color: C.muted, marginLeft: 8,
              }}>
                {activePrinters.length} 台活跃
              </span>
            </h2>
          </div>

          {printers.length === 0 ? (
            <div style={{
              background: C.card, borderRadius: 12, padding: 32,
              border: `1px dashed ${C.border}`, textAlign: 'center', marginBottom: 20,
            }}>
              <div style={{ fontSize: 36, marginBottom: 12 }}>🖨</div>
              <div style={{ fontSize: 16, color: C.muted }}>还未配置任何打印机</div>
              <div style={{ fontSize: 14, color: C.muted, marginTop: 4 }}>点击下方按钮添加第一台</div>
            </div>
          ) : (
            printers.map(p => (
              <PrinterCard
                key={p.id}
                printer={p}
                onEdit={setEditPrinter}
                onTest={handleTest}
                testingId={testingId}
              />
            ))
          )}

          {/* ── Section 2: 路由规则 ── */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginTop: 8, marginBottom: 12,
          }}>
            <h2 style={{ fontSize: 17, fontWeight: 700, color: C.white, margin: 0 }}>
              路由规则
            </h2>
            <button
              onClick={() => setShowAddRoute(true)}
              disabled={activePrinters.length === 0}
              style={{
                minHeight: 36, padding: '0 14px', borderRadius: 8,
                border: `1px solid ${activePrinters.length === 0 ? C.border : C.accent}`,
                background: 'transparent',
                color: activePrinters.length === 0 ? C.muted : C.accent,
                fontSize: 14, fontWeight: 600, cursor: activePrinters.length === 0 ? 'default' : 'pointer',
              }}
            >
              + 添加规则
            </button>
          </div>

          {routes.length === 0 ? (
            <div style={{
              background: C.card, borderRadius: 12, padding: 24,
              border: `1px dashed ${C.border}`, textAlign: 'center', marginBottom: 20,
            }}>
              <div style={{ fontSize: 14, color: C.muted }}>
                {activePrinters.length === 0
                  ? '请先添加打印机，再配置路由规则'
                  : '还没有路由规则，点击"添加规则"配置'}
              </div>
            </div>
          ) : (
            routes.map(r => (
              <RouteRow key={r.id} route={r} onDelete={handleDeleteRoute} />
            ))
          )}

          {/* 规则说明 */}
          {routes.length > 0 && (
            <div style={{
              background: `${C.accent}10`, borderRadius: 10, padding: '10px 14px',
              border: `1px solid ${C.accent}30`, marginTop: 4,
            }}>
              <div style={{ fontSize: 13, color: C.muted, lineHeight: 1.6 }}>
                <strong style={{ color: C.accent }}>匹配优先级：</strong>
                菜品类别精确匹配 → 菜品标签匹配 → 默认兜底规则
              </div>
            </div>
          )}
        </div>
      )}

      {/* 固定底部"添加打印机"按钮 */}
      {!loading && !error && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          padding: '12px 16px 24px', background: C.bg,
          borderTop: `1px solid ${C.border}`,
        }}>
          <button
            onClick={() => { setEditPrinter(null); setShowAddPrinter(true); }}
            style={{
              width: '100%', minHeight: 52, borderRadius: 12,
              border: 'none', background: C.accent,
              color: C.white, fontSize: 16, fontWeight: 700, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            }}
          >
            <span style={{ fontSize: 20 }}>+</span>
            添加打印机
          </button>
        </div>
      )}

      {/* Sheet: 添加/编辑打印机 */}
      {(showAddPrinter || editPrinter !== null) && (
        <AddPrinterSheet
          editPrinter={editPrinter}
          onClose={() => { setShowAddPrinter(false); setEditPrinter(null); }}
          onSaved={() => {
            setShowAddPrinter(false);
            setEditPrinter(null);
            showToast(editPrinter ? '打印机已更新' : '打印机已添加');
            loadData();
          }}
        />
      )}

      {/* Sheet: 添加路由规则 */}
      {showAddRoute && (
        <AddRouteSheet
          printers={printers}
          categories={categories}
          onClose={() => setShowAddRoute(false)}
          onSaved={() => {
            setShowAddRoute(false);
            showToast('路由规则已添加');
            loadData();
          }}
        />
      )}

      {/* Toast 提示 */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: 100, left: '50%', transform: 'translateX(-50%)',
          background: '#1e3a47', border: `1px solid ${C.border}`,
          borderRadius: 24, padding: '10px 20px',
          color: C.text, fontSize: 14, fontWeight: 600, zIndex: 200,
          whiteSpace: 'nowrap', boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
        }}>
          {toast}
        </div>
      )}
    </div>
  );
}
