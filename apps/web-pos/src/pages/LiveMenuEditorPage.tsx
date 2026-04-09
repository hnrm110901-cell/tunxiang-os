/**
 * LiveMenuEditorPage — 菜单实时编辑页
 *
 * 店长/运营人员不停机修改菜品价格、上下架、限量，
 * 保存后 ≤5s 同步到所有终端。
 *
 * C2 库存联动：每个菜品行显示库存状态（可出份数/低库存/售完）。
 * 因缺货下架的菜品显示"等待食材"状态，食材到货后变为"恢复上架"。
 */
import { useState, useCallback, useRef, useEffect, useMemo } from 'react';

// ─── 类型 ───

interface Dish {
  id: string;
  name: string;
  price: number;        // 分
  category: string;
  is_available: boolean;
  daily_limit: number | null;
  sold_today: number;
}

/** 库存预警条目（来自 /api/v1/inventory/soldout-watch） */
interface InventoryWatchItem {
  dish_id: string;
  dish_name: string;
  ingredient_name: string;
  ingredient_id?: string;
  estimated_servings: number;
  is_auto_soldout: boolean;
  is_low_stock: boolean;
}

type SyncStatus = 'idle' | 'syncing' | 'success' | 'error';

interface EditState {
  price: string;        // 元（字符串，方便输入）
  is_available: boolean;
  daily_limit: string;  // 数字字符串，'0' 代表不限
}

// ─── 常量 ───

const API_BASE: string = (window as unknown as Record<string, unknown>).__STORE_API_BASE__ as string || '';
const STORE_ID: string = (window as unknown as Record<string, unknown>).__STORE_ID__ as string || '';
const TENANT_ID: string = (window as unknown as Record<string, unknown>).__TENANT_ID__ as string || '';

const CATEGORIES = ['全部', '热菜', '凉菜', '主食', '饮品'];

const MOCK_DISHES: Dish[] = [
  { id: 'd1', name: '宫保鸡丁',  price: 3800,  category: '热菜', is_available: true,  daily_limit: null, sold_today: 23 },
  { id: 'd2', name: '鱼香肉丝',  price: 3200,  category: '热菜', is_available: false, daily_limit: null, sold_today: 0  },
  { id: 'd3', name: '佛跳墙',    price: 18800, category: '热菜', is_available: true,  daily_limit: 5,    sold_today: 2  },
  { id: 'd4', name: '凉拌黄瓜',  price: 1800,  category: '凉菜', is_available: true,  daily_limit: null, sold_today: 41 },
  { id: 'd5', name: '小笼包',    price: 2200,  category: '主食', is_available: true,  daily_limit: 30,   sold_today: 18 },
];

// ─── 工具 ───

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2).replace(/\.?0+$/, '');
}

function yuanToFen(yuan: string): number {
  const n = parseFloat(yuan);
  return isNaN(n) ? 0 : Math.round(n * 100);
}

// ─── 子组件：同步状态指示器 ───

interface SyncIndicatorProps {
  status: SyncStatus;
  syncedCount: number;
}

function SyncIndicator({ status, syncedCount }: SyncIndicatorProps) {
  const map: Record<SyncStatus, { color: string; label: string; spin?: boolean }> = {
    idle:    { color: '#9CA3AF', label: '已同步' },
    syncing: { color: '#FF6B35', label: '同步中...', spin: true },
    success: { color: '#22C55E', label: `已同步到 ${syncedCount} 个终端` },
    error:   { color: '#EF4444', label: '同步失败，请重试' },
  };
  const { color, label, spin } = map[status];

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span
        style={{
          display: 'inline-block',
          width: 10,
          height: 10,
          borderRadius: '50%',
          background: color,
          animation: spin ? 'spin 1s linear infinite' : 'none',
          flexShrink: 0,
        }}
      />
      <span style={{ fontSize: 13, color }}>{label}</span>
    </div>
  );
}

// ─── 子组件：菜品行内编辑面板 ───

interface DishEditPanelProps {
  dish: Dish;
  onSave: (id: string, edit: EditState) => Promise<void>;
  onClose: () => void;
  saving: boolean;
}

function DishEditPanel({ dish, onSave, onClose, saving }: DishEditPanelProps) {
  const [edit, setEdit] = useState<EditState>({
    price: fenToYuan(dish.price),
    is_available: dish.is_available,
    daily_limit: dish.daily_limit === null ? '0' : String(dish.daily_limit),
  });

  const update = (partial: Partial<EditState>) => setEdit(prev => ({ ...prev, ...partial }));

  const btnBase: React.CSSProperties = {
    height: 48,
    minWidth: 80,
    borderRadius: 8,
    border: 'none',
    cursor: 'pointer',
    fontSize: 15,
    fontWeight: 600,
  };

  const toggleBase: React.CSSProperties = {
    height: 48,
    flex: 1,
    borderRadius: 8,
    border: '1px solid #374151',
    cursor: 'pointer',
    fontSize: 15,
    fontWeight: 600,
    transition: 'background 0.15s, color 0.15s',
  };

  return (
    <div
      style={{
        background: '#1F2937',
        border: '1px solid #374151',
        borderRadius: 12,
        padding: '16px 20px',
        marginTop: 8,
      }}
    >
      {/* 标题行 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <span style={{ color: '#F9FAFB', fontWeight: 700, fontSize: 16 }}>{dish.name}</span>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: '#9CA3AF', cursor: 'pointer', fontSize: 20, padding: '4px 8px', minWidth: 48, minHeight: 48 }}
          aria-label="关闭"
        >
          ✕
        </button>
      </div>

      {/* 价格 */}
      <div style={{ marginBottom: 14 }}>
        <label style={{ color: '#9CA3AF', fontSize: 14, display: 'block', marginBottom: 6 }}>价格（元）</label>
        <input
          type="number"
          min="0"
          step="0.01"
          value={edit.price}
          onChange={e => update({ price: e.target.value })}
          style={{
            background: '#111827',
            border: '1px solid #374151',
            borderRadius: 8,
            color: '#F9FAFB',
            fontSize: 18,
            padding: '10px 14px',
            width: '100%',
            boxSizing: 'border-box',
            height: 48,
          }}
        />
      </div>

      {/* 上下架 */}
      <div style={{ marginBottom: 14 }}>
        <label style={{ color: '#9CA3AF', fontSize: 14, display: 'block', marginBottom: 6 }}>状态</label>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => update({ is_available: true })}
            style={{
              ...toggleBase,
              background: edit.is_available ? '#FF6B35' : '#111827',
              color: edit.is_available ? '#fff' : '#9CA3AF',
              borderColor: edit.is_available ? '#FF6B35' : '#374151',
            }}
          >
            ● 上架
          </button>
          <button
            onClick={() => update({ is_available: false })}
            style={{
              ...toggleBase,
              background: !edit.is_available ? '#374151' : '#111827',
              color: !edit.is_available ? '#F9FAFB' : '#9CA3AF',
              borderColor: !edit.is_available ? '#6B7280' : '#374151',
            }}
          >
            ○ 下架
          </button>
        </div>
      </div>

      {/* 每日限量 */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ color: '#9CA3AF', fontSize: 14, display: 'block', marginBottom: 6 }}>
          每日限量（0 = 不限）
        </label>
        <input
          type="number"
          min="0"
          value={edit.daily_limit}
          onChange={e => update({ daily_limit: e.target.value })}
          placeholder="0（不限）"
          style={{
            background: '#111827',
            border: '1px solid #374151',
            borderRadius: 8,
            color: '#F9FAFB',
            fontSize: 16,
            padding: '10px 14px',
            width: '100%',
            boxSizing: 'border-box',
            height: 48,
          }}
        />
      </div>

      {/* 保存按钮 */}
      <button
        onClick={() => onSave(dish.id, edit)}
        disabled={saving}
        style={{
          ...btnBase,
          width: '100%',
          background: saving ? '#6B7280' : '#FF6B35',
          color: '#fff',
          opacity: saving ? 0.7 : 1,
          cursor: saving ? 'not-allowed' : 'pointer',
        }}
      >
        {saving ? '同步中...' : '保存并同步'}
      </button>
    </div>
  );
}

// ─── 库存状态标签 ───

interface InventoryStatusBadgeProps {
  watchItem: InventoryWatchItem | undefined;
  loadingInventory: boolean;
}

function InventoryStatusBadge({ watchItem, loadingInventory }: InventoryStatusBadgeProps) {
  if (loadingInventory) {
    return (
      <span style={{ fontSize: 12, color: '#6B7280' }}>库存数据加载中</span>
    );
  }

  if (!watchItem) {
    // 无预警条目 → 正常库存（绿色）
    return (
      <span
        style={{
          fontSize: 12,
          color: '#22C55E',
          background: '#052E16',
          border: '1px solid #166534',
          borderRadius: 4,
          padding: '1px 6px',
        }}
      >
        库存正常
      </span>
    );
  }

  const { estimated_servings, is_auto_soldout } = watchItem;

  if (is_auto_soldout || estimated_servings === 0) {
    return (
      <span
        style={{
          fontSize: 12,
          color: '#FCA5A5',
          background: '#450A0A',
          border: '1px solid #EF4444',
          borderRadius: 4,
          padding: '1px 6px',
        }}
      >
        已售完 · 自动下架
      </span>
    );
  }

  if (estimated_servings <= 2) {
    return (
      <span
        style={{
          fontSize: 12,
          color: '#FDBA74',
          background: '#431407',
          border: '1px solid #F97316',
          borderRadius: 4,
          padding: '1px 6px',
        }}
      >
        库存: 预计可出 {estimated_servings} 份 · 即将售完
      </span>
    );
  }

  // 3-10 份 → 低库存黄色
  return (
    <span
      style={{
        fontSize: 12,
        color: '#FDE68A',
        background: '#422006',
        border: '1px solid #CA8A04',
        borderRadius: 4,
        padding: '1px 6px',
      }}
    >
      库存: 预计可出 {estimated_servings} 份 🟡低库存
    </span>
  );
}

// ─── 子组件：菜品行 ───

interface DishRowProps {
  dish: Dish;
  selected: boolean;
  onSelect: (id: string, checked: boolean) => void;
  expanded: boolean;
  onEdit: (id: string) => void;
  onQuickToggle: (id: string, available: boolean) => void;
  onSave: (id: string, edit: EditState) => Promise<void>;
  saving: boolean;
  inventoryItem: InventoryWatchItem | undefined;
  loadingInventory: boolean;
  onRestoreFromInventory: (dishId: string) => Promise<void>;
}

function DishRow({ dish, selected, onSelect, expanded, onEdit, onQuickToggle, onSave, saving, inventoryItem, loadingInventory, onRestoreFromInventory: _onRestoreFromInventory }: DishRowProps) {
  const remaining = dish.daily_limit !== null ? dish.daily_limit - dish.sold_today : null;

  // 判断是否因缺货自动下架（仅显示"等待食材"而非普通恢复按钮）
  const isSoldoutByInventory = !dish.is_available && inventoryItem?.is_auto_soldout;
  const canRestoreNow = !dish.is_available && !inventoryItem?.is_auto_soldout;

  return (
    <div style={{ borderBottom: '1px solid #1F2937' }}>
      {/* 主行 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          padding: '14px 16px',
          gap: 10,
          background: selected ? '#1F2937' : 'transparent',
        }}
      >
        {/* 选择框 */}
        <label style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', minWidth: 32, minHeight: 48 }}>
          <input
            type="checkbox"
            checked={selected}
            onChange={e => onSelect(dish.id, e.target.checked)}
            style={{ width: 18, height: 18, accentColor: '#FF6B35', cursor: 'pointer' }}
          />
        </label>

        {/* 菜品信息 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
            <span style={{ color: '#F9FAFB', fontSize: 16, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {dish.name}
            </span>
            <span style={{ color: '#FF6B35', fontSize: 16, fontWeight: 700, whiteSpace: 'nowrap' }}>
              ¥{fenToYuan(dish.price)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: dish.is_available ? '#22C55E' : '#9CA3AF' }}>
              {dish.is_available ? '● 上架中' : '○ 已下架'}
            </span>
            {dish.daily_limit !== null && (
              <span style={{ fontSize: 13, color: '#9CA3AF' }}>
                限量{dish.daily_limit}份 / 剩{remaining}份
              </span>
            )}
            <span style={{ fontSize: 12, color: '#6B7280' }}>今日已售{dish.sold_today}</span>
            {/* 库存状态标签 */}
            <InventoryStatusBadge
              watchItem={inventoryItem}
              loadingInventory={loadingInventory}
            />
          </div>
        </div>

        {/* 快捷操作 */}
        <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
          {/* 因缺货自动下架：显示"等待食材"灰色按钮（食材到货后应变为可点击状态） */}
          {isSoldoutByInventory && (
            <button
              disabled
              title={`因 ${inventoryItem?.ingredient_name ?? '食材'} 库存不足自动下架，请先补货`}
              style={{
                height: 48,
                padding: '0 14px',
                background: '#1F2937',
                color: '#6B7280',
                border: '1px solid #374151',
                borderRadius: 8,
                cursor: 'not-allowed',
                fontSize: 13,
                fontWeight: 600,
                whiteSpace: 'nowrap',
              }}
            >
              等待食材
            </button>
          )}
          {/* 非库存原因下架：显示正常"恢复上架"绿色按钮 */}
          {canRestoreNow && (
            <button
              onClick={() => onQuickToggle(dish.id, true)}
              style={{
                height: 48,
                padding: '0 14px',
                background: '#065F46',
                color: '#6EE7B7',
                border: '1px solid #059669',
                borderRadius: 8,
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 600,
                whiteSpace: 'nowrap',
              }}
            >
              恢复上架
            </button>
          )}
          <button
            onClick={() => onEdit(dish.id)}
            style={{
              height: 48,
              padding: '0 16px',
              background: expanded ? '#FF6B35' : '#374151',
              color: '#F9FAFB',
              border: 'none',
              borderRadius: 8,
              cursor: 'pointer',
              fontSize: 14,
              fontWeight: 600,
            }}
          >
            {expanded ? '收起' : '编辑'}
          </button>
        </div>
      </div>

      {/* 展开编辑面板 */}
      {expanded && (
        <div style={{ padding: '0 16px 16px' }}>
          <DishEditPanel
            dish={dish}
            onSave={onSave}
            onClose={() => onEdit(dish.id)}
            saving={saving}
          />
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ───

export function LiveMenuEditorPage() {
  const [dishes, setDishes] = useState<Dish[]>(MOCK_DISHES);
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState('全部');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [syncStatus, setSyncStatus] = useState<SyncStatus>('idle');
  const [syncedCount] = useState(0);
  const [savingId, setSavingId] = useState<string | null>(null);
  const successTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ─── 库存状态 ───
  const [inventoryItems, setInventoryItems] = useState<InventoryWatchItem[]>([]);
  const [loadingInventory, setLoadingInventory] = useState(false);

  // 构建 dish_id → InventoryWatchItem 的查找 Map（useMemo 避免重复构建）
  const inventoryMap = useMemo(
    () => new Map<string, InventoryWatchItem>(inventoryItems.map(item => [item.dish_id, item])),
    [inventoryItems]
  );

  const fetchInventoryWatch = useCallback(async () => {
    if (!API_BASE || !STORE_ID) return;
    setLoadingInventory(true);
    try {
      const headers: Record<string, string> = {};
      if (TENANT_ID) headers['X-Tenant-ID'] = TENANT_ID;
      const resp = await fetch(
        `${API_BASE}/api/v1/inventory/soldout-watch?store_id=${encodeURIComponent(STORE_ID)}`,
        { headers }
      );
      if (!resp.ok) return;
      const json = await resp.json() as { ok: boolean; data: { items: InventoryWatchItem[] } };
      if (json.ok && json.data?.items) {
        setInventoryItems(json.data.items);
      }
    } catch {
      // 静默忽略，库存数据不影响主流程
    } finally {
      setLoadingInventory(false);
    }
  }, []);

  // 初始加载库存状态
  useEffect(() => {
    fetchInventoryWatch();
  }, [fetchInventoryWatch]);

  // 食材补货恢复：调用 restock 接口，恢复对应菜品上架
  const handleRestoreFromInventory = useCallback(async (dishId: string) => {
    const watchItem = inventoryMap.get(dishId);
    if (!watchItem) return;
    if (!API_BASE) {
      // 无 API：乐观更新
      setDishes(prev => prev.map(d => d.id === dishId ? { ...d, is_available: true } : d));
      setInventoryItems(prev => prev.filter(i => i.dish_id !== dishId));
      return;
    }
    setSyncStatus('syncing');
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (TENANT_ID) headers['X-Tenant-ID'] = TENANT_ID;
      const resp = await fetch(
        `${API_BASE}/api/v1/inventory/ingredient/${watchItem.ingredient_id ?? ''}/restock`,
        {
          method: 'POST',
          headers,
          body: JSON.stringify({ add_stock: 0, unit: 'kg' }),
        }
      );
      if (resp.ok) {
        setDishes(prev => prev.map(d => d.id === dishId ? { ...d, is_available: true } : d));
        await fetchInventoryWatch();
        setSyncStatus('success');
        successTimerRef.current = setTimeout(() => setSyncStatus('idle'), 3000);
      } else {
        setSyncStatus('error');
      }
    } catch {
      setSyncStatus('error');
    }
  }, [inventoryMap, fetchInventoryWatch]);

  // 过滤
  const filtered = dishes.filter(d => {
    const matchCat = activeCategory === '全部' || d.category === activeCategory;
    const matchSearch = !search || d.name.includes(search);
    return matchCat && matchSearch;
  });

  // 显示短暂 success 后回 idle
  const setSuccess = useCallback(() => {
    setSyncStatus('success');
    if (successTimerRef.current) clearTimeout(successTimerRef.current);
    successTimerRef.current = setTimeout(() => setSyncStatus('idle'), 3000);
  }, []);

  // API 调用
  const callLiveApi = useCallback(async (dishId: string, payload: Record<string, unknown>): Promise<boolean> => {
    if (!API_BASE) {
      // 无 API，乐观更新，模拟成功
      await new Promise<void>(resolve => setTimeout(resolve, 400));
      return true;
    }
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (STORE_ID) headers['X-Store-ID'] = STORE_ID;
    if (TENANT_ID) headers['X-Tenant-ID'] = TENANT_ID;
    const resp = await fetch(`${API_BASE}/api/v1/menu/dishes/${dishId}/live`, {
      method: 'PATCH',
      headers,
      body: JSON.stringify(payload),
    });
    if (!resp.ok) return false;
    const json = await resp.json() as { ok: boolean };
    return json.ok;
  }, []);

  // 保存单个菜品
  const handleSave = useCallback(async (id: string, edit: EditState) => {
    setSavingId(id);
    setSyncStatus('syncing');
    try {
      const payload: Record<string, unknown> = {
        price: yuanToFen(edit.price),
        is_available: edit.is_available,
        daily_limit: edit.daily_limit === '0' || edit.daily_limit === '' ? null : parseInt(edit.daily_limit, 10),
      };
      const ok = await callLiveApi(id, payload);
      if (ok) {
        setDishes(prev => prev.map(d => {
          if (d.id !== id) return d;
          return {
            ...d,
            price: yuanToFen(edit.price),
            is_available: edit.is_available,
            daily_limit: payload.daily_limit as number | null,
          };
        }));
        setExpandedId(null);
        setSuccess();
      } else {
        setSyncStatus('error');
      }
    } catch {
      setSyncStatus('error');
    } finally {
      setSavingId(null);
    }
  }, [callLiveApi, setSuccess]);

  // 快速切换上下架（单个）
  const handleQuickToggle = useCallback(async (id: string, available: boolean) => {
    setSyncStatus('syncing');
    try {
      const ok = await callLiveApi(id, { is_available: available });
      if (ok) {
        setDishes(prev => prev.map(d => d.id === id ? { ...d, is_available: available } : d));
        setSuccess();
      } else {
        setSyncStatus('error');
      }
    } catch {
      setSyncStatus('error');
    }
  }, [callLiveApi, setSuccess]);

  // 批量上/下架
  const handleBulkAvailability = useCallback(async (available: boolean) => {
    if (selectedIds.size === 0) return;
    setSyncStatus('syncing');
    const ids = Array.from(selectedIds);
    try {
      let ok = false;
      if (!API_BASE) {
        await new Promise<void>(resolve => setTimeout(resolve, 400));
        ok = true;
      } else {
        const headers: Record<string, string> = { 'Content-Type': 'application/json' };
        if (STORE_ID) headers['X-Store-ID'] = STORE_ID;
        if (TENANT_ID) headers['X-Tenant-ID'] = TENANT_ID;
        const resp = await fetch(`${API_BASE}/api/v1/menu/dishes/bulk-availability`, {
          method: 'POST',
          headers,
          body: JSON.stringify({
            dish_ids: ids,
            is_available: available,
            reason: available ? '食材到货恢复' : '今日估清',
          }),
        });
        if (resp.ok) {
          const json = await resp.json() as { ok: boolean };
          ok = json.ok;
        }
      }
      if (ok) {
        setDishes(prev => prev.map(d => selectedIds.has(d.id) ? { ...d, is_available: available } : d));
        setSelectedIds(new Set());
        setSuccess();
      } else {
        setSyncStatus('error');
      }
    } catch {
      setSyncStatus('error');
    }
  }, [selectedIds, callLiveApi, setSuccess]);

  const toggleSelect = useCallback((id: string, checked: boolean) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (checked) next.add(id); else next.delete(id);
      return next;
    });
  }, []);

  const toggleEdit = useCallback((id: string) => {
    setExpandedId(prev => (prev === id ? null : id));
  }, []);

  return (
    <div style={{ minHeight: '100vh', background: '#111827', color: '#F9FAFB', fontFamily: 'system-ui, sans-serif', paddingBottom: selectedIds.size > 0 ? 80 : 0 }}>
      {/* 顶部标题栏 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 16px 12px', borderBottom: '1px solid #1F2937', position: 'sticky', top: 0, background: '#111827', zIndex: 10 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: '#F9FAFB' }}>菜单实时编辑</h1>
        <SyncIndicator status={syncStatus} syncedCount={syncedCount} />
      </div>

      {/* 搜索框 */}
      <div style={{ padding: '12px 16px 0' }}>
        <input
          type="search"
          placeholder="搜索菜品..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            width: '100%',
            boxSizing: 'border-box',
            height: 48,
            background: '#1F2937',
            border: '1px solid #374151',
            borderRadius: 10,
            color: '#F9FAFB',
            fontSize: 16,
            padding: '0 16px',
            outline: 'none',
          }}
        />
      </div>

      {/* 分类 Tab */}
      <div style={{ display: 'flex', gap: 8, padding: '12px 16px', overflowX: 'auto' }}>
        {CATEGORIES.map(cat => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            style={{
              height: 40,
              padding: '0 16px',
              borderRadius: 20,
              border: 'none',
              cursor: 'pointer',
              fontSize: 14,
              fontWeight: activeCategory === cat ? 700 : 400,
              background: activeCategory === cat ? '#FF6B35' : '#1F2937',
              color: activeCategory === cat ? '#fff' : '#9CA3AF',
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            {cat}
          </button>
        ))}
      </div>

      {/* 菜品列表 */}
      <div style={{ background: '#111827' }}>
        {filtered.length === 0 && (
          <div style={{ textAlign: 'center', color: '#6B7280', padding: 40, fontSize: 15 }}>暂无菜品</div>
        )}
        {filtered.map(dish => (
          <DishRow
            key={dish.id}
            dish={dish}
            selected={selectedIds.has(dish.id)}
            onSelect={toggleSelect}
            expanded={expandedId === dish.id}
            onEdit={toggleEdit}
            onQuickToggle={handleQuickToggle}
            onSave={handleSave}
            saving={savingId === dish.id}
            inventoryItem={inventoryMap.get(dish.id)}
            loadingInventory={loadingInventory}
            onRestoreFromInventory={handleRestoreFromInventory}
          />
        ))}
      </div>

      {/* 批量操作底部固定栏 */}
      {selectedIds.size > 0 && (
        <div
          style={{
            position: 'fixed',
            bottom: 0,
            left: 0,
            right: 0,
            background: '#1F2937',
            borderTop: '1px solid #374151',
            padding: '12px 16px',
            display: 'flex',
            gap: 12,
            alignItems: 'center',
            zIndex: 20,
          }}
        >
          <span style={{ color: '#9CA3AF', fontSize: 14, flex: 1 }}>
            已选 {selectedIds.size} 项
          </span>
          <button
            onClick={() => handleBulkAvailability(false)}
            style={{
              height: 48,
              padding: '0 20px',
              background: '#7F1D1D',
              color: '#FCA5A5',
              border: '1px solid #EF4444',
              borderRadius: 10,
              cursor: 'pointer',
              fontSize: 15,
              fontWeight: 600,
            }}
          >
            批量下架
          </button>
          <button
            onClick={() => handleBulkAvailability(true)}
            style={{
              height: 48,
              padding: '0 20px',
              background: '#065F46',
              color: '#6EE7B7',
              border: '1px solid #059669',
              borderRadius: 10,
              cursor: 'pointer',
              fontSize: 15,
              fontWeight: 600,
            }}
          >
            批量恢复
          </button>
        </div>
      )}

      {/* 全局 CSS（spin 动画） */}
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
