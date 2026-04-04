/**
 * SoldOutPage — POS端菜品沽清管理
 * Store-POS 终端，触屏横屏，无Ant Design
 * 最小点击区48px，最小字体16px，inline style
 */
import { useState, useCallback } from 'react';

// ── 类型 ──────────────────────────────────────────────────
type DishStatus = 'soldout' | 'available';

interface Dish {
  id: string;
  name: string;
  category: string;
  status: DishStatus;
  soldout_at?: string;
  reason?: string;
  stock?: number | null;
}

type FilterStatus = 'all' | 'soldout' | 'available';

const SOLDOUT_REASONS = ['缺货', '时间限定', '库存不足', '今日已售完'] as const;
type SoldoutReason = typeof SOLDOUT_REASONS[number];

// ── Mock数据 ──────────────────────────────────────────────
const INITIAL_DISHES: Dish[] = [
  { id: 'd1', name: '清蒸桂鱼',   category: '海鲜',  status: 'soldout',   soldout_at: '14:30', reason: '今日已售完' },
  { id: 'd2', name: '椒盐虾',     category: '海鲜',  status: 'available', stock: 8 },
  { id: 'd3', name: '红烧肉',     category: '家常菜', status: 'available', stock: null },
  { id: 'd4', name: '西湖牛肉羹', category: '汤品',  status: 'soldout',   soldout_at: '15:00', reason: '缺货' },
  { id: 'd5', name: '麻婆豆腐',   category: '家常菜', status: 'available', stock: 15 },
  { id: 'd6', name: '扬州炒饭',   category: '主食',  status: 'available', stock: null },
  { id: 'd7', name: '杨枝甘露',   category: '甜品',  status: 'soldout',   soldout_at: '13:45', reason: '库存不足' },
  { id: 'd8', name: '白灼基围虾', category: '海鲜',  status: 'available', stock: 5 },
  { id: 'd9', name: '番茄蛋花汤', category: '汤品',  status: 'available', stock: null },
  { id: 'd10', name: '原味蛋糕',  category: '甜品',  status: 'available', stock: 3 },
];

const ALL_CATEGORIES = ['全部', '海鲜', '家常菜', '汤品', '主食', '甜品'] as const;

// ── API（乐观更新，失败时Mock成功）──────────────────────────
const STORE_ID = (window as Record<string, unknown>).__STORE_ID__ as string || 'demo';

async function apiMarkSoldout(id: string, reason: string): Promise<void> {
  try {
    await fetch(`/api/v1/menu/dishes/${id}/soldout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': STORE_ID },
      body: JSON.stringify({ reason }),
    });
  } catch {
    // 乐观更新：网络失败时静默处理，UI已更新
  }
}

async function apiRestoreAvailable(id: string): Promise<void> {
  try {
    await fetch(`/api/v1/menu/dishes/${id}/soldout`, {
      method: 'DELETE',
      headers: { 'X-Tenant-ID': STORE_ID },
    });
  } catch {
    // 乐观更新：网络失败时静默处理，UI已更新
  }
}

// ── 按钮触控样式（scale反馈）──────────────────────────────
const btnBase: React.CSSProperties = {
  border: 'none', cursor: 'pointer', borderRadius: 10,
  fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
  fontWeight: 600, fontSize: 16, transition: 'transform 200ms ease, opacity 200ms ease',
  WebkitTapHighlightColor: 'transparent', outline: 'none',
};

function useTouchScale() {
  const [pressed, setPressed] = useState(false);
  return {
    pressed,
    handlers: {
      onTouchStart: () => setPressed(true),
      onTouchEnd:   () => setPressed(false),
      onMouseDown:  () => setPressed(true),
      onMouseUp:    () => setPressed(false),
      onMouseLeave: () => setPressed(false),
    },
  };
}

// ── 沽清原因弹窗 ──────────────────────────────────────────
interface SoldoutModalProps {
  dish: Dish;
  onConfirm: (reason: SoldoutReason) => void;
  onCancel: () => void;
}

function SoldoutModal({ dish, onConfirm, onCancel }: SoldoutModalProps) {
  const [selectedReason, setSelectedReason] = useState<SoldoutReason | null>(null);

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}
      onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}
    >
      <div style={{
        background: '#fff', borderRadius: 16, padding: 32,
        minWidth: 380, maxWidth: 480, width: '90vw',
        boxShadow: '0 8px 24px rgba(0,0,0,0.12)',
      }}>
        {/* 标题 */}
        <div style={{ fontSize: 22, fontWeight: 700, color: '#2C2C2A', marginBottom: 6 }}>
          标记沽清
        </div>
        <div style={{
          fontSize: 18, fontWeight: 600, color: '#A32D2D',
          marginBottom: 24, paddingBottom: 20,
          borderBottom: '1px solid #E8E6E1',
        }}>
          {dish.name}
        </div>

        {/* 原因选择 */}
        <div style={{ fontSize: 16, color: '#5F5E5A', marginBottom: 16 }}>选择沽清原因</div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 28 }}>
          {SOLDOUT_REASONS.map(reason => {
            const isSelected = selectedReason === reason;
            return (
              <button
                key={reason}
                onClick={() => setSelectedReason(reason)}
                style={{
                  ...btnBase,
                  height: 56, padding: '0 16px',
                  background: isSelected ? '#FFF3ED' : '#F8F7F5',
                  color: isSelected ? '#FF6B35' : '#2C2C2A',
                  border: isSelected ? '2px solid #FF6B35' : '2px solid transparent',
                  fontSize: 17,
                }}
              >
                {reason}
              </button>
            );
          })}
        </div>

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 12 }}>
          <button
            onClick={onCancel}
            style={{
              ...btnBase, flex: 1, height: 56,
              background: '#F0EDE6', color: '#5F5E5A', fontSize: 17,
            }}
          >
            取消
          </button>
          <button
            onClick={() => selectedReason && onConfirm(selectedReason)}
            disabled={!selectedReason}
            style={{
              ...btnBase, flex: 2, height: 56,
              background: selectedReason ? '#A32D2D' : '#ccc',
              color: '#fff', fontSize: 17,
              opacity: selectedReason ? 1 : 0.5,
              cursor: selectedReason ? 'pointer' : 'not-allowed',
            }}
          >
            确认沽清
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 菜品列表行 ────────────────────────────────────────────
interface DishRowProps {
  dish: Dish;
  selected: boolean;
  multiSelectMode: boolean;
  onToggleSelect: (id: string) => void;
  onMarkSoldout: (dish: Dish) => void;
  onRestore: (id: string) => void;
}

function DishRow({ dish, selected, multiSelectMode, onToggleSelect, onMarkSoldout, onRestore }: DishRowProps) {
  const isSoldout = dish.status === 'soldout';

  return (
    <div
      onClick={() => multiSelectMode && onToggleSelect(dish.id)}
      style={{
        display: 'flex', alignItems: 'center',
        minHeight: 72, padding: '12px 20px', gap: 16,
        background: selected ? '#FFF3ED' : isSoldout ? '#FFF8F8' : '#fff',
        borderBottom: '1px solid #E8E6E1',
        cursor: multiSelectMode ? 'pointer' : 'default',
        transition: 'background 150ms',
      }}
    >
      {/* 多选复选框 */}
      {multiSelectMode && (
        <div style={{
          width: 28, height: 28, borderRadius: 6, flexShrink: 0,
          border: `2px solid ${selected ? '#FF6B35' : '#B4B2A9'}`,
          background: selected ? '#FF6B35' : '#fff',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {selected && (
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M2 7L5.5 10.5L12 3" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </div>
      )}

      {/* 菜品信息 */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4,
        }}>
          <span style={{
            fontSize: 20, fontWeight: 600,
            color: isSoldout ? '#A32D2D' : '#2C2C2A',
            textDecoration: isSoldout ? 'line-through' : 'none',
          }}>
            {dish.name}
          </span>
          {/* 状态Badge */}
          <span style={{
            display: 'inline-flex', alignItems: 'center',
            padding: '2px 10px', borderRadius: 20, fontSize: 14, fontWeight: 600,
            background: isSoldout ? '#FDEDED' : '#EEF7F3',
            color: isSoldout ? '#A32D2D' : '#0F6E56',
          }}>
            {isSoldout ? '已沽清' : '可供应'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 16, color: '#5F5E5A' }}>{dish.category}</span>
          {dish.stock != null && !isSoldout && (
            <span style={{ fontSize: 16, color: '#BA7517' }}>剩余 {dish.stock} 份</span>
          )}
          {isSoldout && dish.soldout_at && (
            <span style={{ fontSize: 16, color: '#B4B2A9' }}>
              沽清于 {dish.soldout_at} · {dish.reason}
            </span>
          )}
        </div>
      </div>

      {/* 操作按钮（非多选模式下显示） */}
      {!multiSelectMode && (
        <div style={{ flexShrink: 0 }}>
          {isSoldout ? (
            <RestoreButton dishId={dish.id} onRestore={onRestore} />
          ) : (
            <MarkSoldoutButton dish={dish} onMark={onMarkSoldout} />
          )}
        </div>
      )}
    </div>
  );
}

function RestoreButton({ dishId, onRestore }: { dishId: string; onRestore: (id: string) => void }) {
  const { pressed, handlers } = useTouchScale();
  return (
    <button
      {...handlers}
      onClick={(e) => { e.stopPropagation(); onRestore(dishId); }}
      style={{
        ...btnBase,
        height: 48, padding: '0 20px',
        background: '#0F6E56', color: '#fff', fontSize: 16,
        transform: pressed ? 'scale(0.97)' : 'scale(1)',
      }}
    >
      恢复供应
    </button>
  );
}

function MarkSoldoutButton({ dish, onMark }: { dish: Dish; onMark: (d: Dish) => void }) {
  const { pressed, handlers } = useTouchScale();
  return (
    <button
      {...handlers}
      onClick={(e) => { e.stopPropagation(); onMark(dish); }}
      style={{
        ...btnBase,
        height: 48, padding: '0 20px',
        background: '#A32D2D', color: '#fff', fontSize: 16,
        transform: pressed ? 'scale(0.97)' : 'scale(1)',
      }}
    >
      标记沽清
    </button>
  );
}

// ── 主页面 ────────────────────────────────────────────────
export function SoldOutPage() {
  const [dishes, setDishes] = useState<Dish[]>(INITIAL_DISHES);
  const [search, setSearch] = useState('');
  const [activeCategory, setActiveCategory] = useState<string>('全部');
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [multiSelectMode, setMultiSelectMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [soldoutModal, setSoldoutModal] = useState<Dish | null>(null);

  // ── 过滤逻辑 ────────────────────────────────────────────
  const filtered = dishes
    .filter(d => {
      const matchSearch = !search || d.name.includes(search);
      const matchCategory = activeCategory === '全部' || d.category === activeCategory;
      const matchStatus =
        filterStatus === 'all' ||
        (filterStatus === 'soldout' && d.status === 'soldout') ||
        (filterStatus === 'available' && d.status === 'available');
      return matchSearch && matchCategory && matchStatus;
    })
    // 沽清菜品排在前面
    .sort((a, b) => {
      if (a.status === 'soldout' && b.status !== 'soldout') return -1;
      if (a.status !== 'soldout' && b.status === 'soldout') return 1;
      return 0;
    });

  // ── 操作：标记沽清 ──────────────────────────────────────
  const handleMarkSoldout = useCallback((dish: Dish) => {
    setSoldoutModal(dish);
  }, []);

  const handleConfirmSoldout = useCallback((reason: SoldoutReason) => {
    if (!soldoutModal) return;
    const id = soldoutModal.id;
    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    // 乐观更新
    setDishes(prev => prev.map(d =>
      d.id === id
        ? { ...d, status: 'soldout', soldout_at: timeStr, reason }
        : d
    ));
    setSoldoutModal(null);
    void apiMarkSoldout(id, reason);
  }, [soldoutModal]);

  // ── 操作：恢复供应 ──────────────────────────────────────
  const handleRestore = useCallback((id: string) => {
    setDishes(prev => prev.map(d =>
      d.id === id
        ? { ...d, status: 'available', soldout_at: undefined, reason: undefined }
        : d
    ));
    void apiRestoreAvailable(id);
  }, []);

  // ── 多选操作 ────────────────────────────────────────────
  const toggleSelect = useCallback((id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const handleBatchSoldout = useCallback(() => {
    if (selectedIds.size === 0) return;
    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;
    setDishes(prev => prev.map(d =>
      selectedIds.has(d.id)
        ? { ...d, status: 'soldout', soldout_at: timeStr, reason: '缺货' }
        : d
    ));
    selectedIds.forEach(id => void apiMarkSoldout(id, '缺货'));
    setSelectedIds(new Set());
    setMultiSelectMode(false);
  }, [selectedIds]);

  const handleBatchRestore = useCallback(() => {
    if (selectedIds.size === 0) return;
    setDishes(prev => prev.map(d =>
      selectedIds.has(d.id)
        ? { ...d, status: 'available', soldout_at: undefined, reason: undefined }
        : d
    ));
    selectedIds.forEach(id => void apiRestoreAvailable(id));
    setSelectedIds(new Set());
    setMultiSelectMode(false);
  }, [selectedIds]);

  const toggleMultiSelect = () => {
    setMultiSelectMode(v => !v);
    setSelectedIds(new Set());
  };

  const soldoutCount = dishes.filter(d => d.status === 'soldout').length;

  return (
    <div style={{
      height: '100vh', display: 'flex', flexDirection: 'column',
      background: '#F8F7F5', overflow: 'hidden',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
    }}>
      {/* ── 顶部搜索/筛选区 ────────────────────────────────── */}
      <div style={{
        background: '#fff', flexShrink: 0,
        borderBottom: '1px solid #E8E6E1',
        boxShadow: '0 1px 2px rgba(0,0,0,0.05)',
      }}>
        {/* 页头 */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 20px 12px',
        }}>
          <div>
            <div style={{ fontSize: 24, fontWeight: 700, color: '#2C2C2A' }}>菜品沽清管理</div>
            <div style={{ fontSize: 16, color: '#5F5E5A', marginTop: 2 }}>
              当前已沽清
              <span style={{ color: '#A32D2D', fontWeight: 700, margin: '0 4px' }}>{soldoutCount}</span>
              道菜品
            </div>
          </div>
        </div>

        {/* 搜索框 */}
        <div style={{ padding: '0 20px 12px' }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            background: '#F8F7F5', borderRadius: 10, padding: '0 16px',
            border: '1px solid #E8E6E1', height: 48,
          }}>
            <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
              <circle cx="9" cy="9" r="6" stroke="#B4B2A9" strokeWidth="2" />
              <path d="M14 14l3 3" stroke="#B4B2A9" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="搜索菜品名称..."
              style={{
                flex: 1, border: 'none', background: 'transparent',
                fontSize: 17, color: '#2C2C2A', outline: 'none',
                fontFamily: 'inherit',
              }}
            />
            {search && (
              <button onClick={() => setSearch('')} style={{ ...btnBase, background: 'none', padding: 4 }}>
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                  <path d="M4 4l8 8M12 4l-8 8" stroke="#B4B2A9" strokeWidth="2" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
        </div>

        {/* 分类 Tab（横向滚动） */}
        <div style={{
          overflowX: 'auto', display: 'flex', gap: 8, padding: '0 20px 12px',
          scrollbarWidth: 'none', WebkitOverflowScrolling: 'touch' as React.CSSProperties['WebkitOverflowScrolling'],
        }}>
          {ALL_CATEGORIES.map(cat => {
            const isActive = activeCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => setActiveCategory(cat)}
                style={{
                  ...btnBase, flexShrink: 0, height: 40, padding: '0 18px',
                  background: isActive ? '#FF6B35' : '#F0EDE6',
                  color: isActive ? '#fff' : '#5F5E5A',
                  fontSize: 16, fontWeight: isActive ? 600 : 400,
                  borderRadius: 20,
                }}
              >
                {cat}
              </button>
            );
          })}
        </div>

        {/* 状态筛选 */}
        <div style={{ display: 'flex', padding: '0 20px 16px', gap: 10 }}>
          {([['all', '全部'], ['soldout', '已沽清'], ['available', '可供应']] as [FilterStatus, string][]).map(([val, label]) => {
            const isActive = filterStatus === val;
            return (
              <button
                key={val}
                onClick={() => setFilterStatus(val)}
                style={{
                  ...btnBase, height: 40, padding: '0 18px',
                  background: isActive
                    ? (val === 'soldout' ? '#FDEDED' : val === 'available' ? '#EEF7F3' : '#FFF3ED')
                    : '#F8F7F5',
                  color: isActive
                    ? (val === 'soldout' ? '#A32D2D' : val === 'available' ? '#0F6E56' : '#FF6B35')
                    : '#5F5E5A',
                  border: isActive ? `2px solid ${val === 'soldout' ? '#A32D2D' : val === 'available' ? '#0F6E56' : '#FF6B35'}` : '2px solid transparent',
                  fontSize: 16, fontWeight: isActive ? 600 : 400, borderRadius: 20,
                }}
              >
                {label}
                {val === 'soldout' && soldoutCount > 0 && (
                  <span style={{
                    marginLeft: 6, background: '#A32D2D', color: '#fff',
                    borderRadius: 10, padding: '0 6px', fontSize: 13, fontWeight: 700,
                  }}>
                    {soldoutCount}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* ── 菜品列表（主区域，可滚动） ─────────────────────── */}
      <div style={{
        flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' as React.CSSProperties['WebkitOverflowScrolling'],
        paddingBottom: multiSelectMode ? 80 : 20,
      }}>
        {filtered.length === 0 ? (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            padding: '60px 20px', color: '#B4B2A9',
          }}>
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none" style={{ marginBottom: 16 }}>
              <circle cx="24" cy="24" r="20" stroke="#E8E6E1" strokeWidth="2" />
              <path d="M16 24h16M24 16v16" stroke="#E8E6E1" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <div style={{ fontSize: 18, color: '#B4B2A9' }}>没有符合条件的菜品</div>
          </div>
        ) : (
          <div style={{ background: '#fff', borderRadius: 12, margin: '12px 12px 0', overflow: 'hidden', boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
            {filtered.map((dish, index) => (
              <div key={dish.id}>
                <DishRow
                  dish={dish}
                  selected={selectedIds.has(dish.id)}
                  multiSelectMode={multiSelectMode}
                  onToggleSelect={toggleSelect}
                  onMarkSoldout={handleMarkSoldout}
                  onRestore={handleRestore}
                />
                {index < filtered.length - 1 && (
                  <div style={{ height: 1, background: '#E8E6E1', marginLeft: 20 }} />
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── 底部批量操作栏（固定，80px） ──────────────────── */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0, height: 80,
        background: '#fff', borderTop: '1px solid #E8E6E1',
        display: 'flex', alignItems: 'center', padding: '0 16px', gap: 12,
        boxShadow: '0 -2px 8px rgba(0,0,0,0.06)', zIndex: 100,
      }}>
        {/* 多选切换按钮 */}
        <button
          onClick={toggleMultiSelect}
          style={{
            ...btnBase, height: 52, padding: '0 20px', flexShrink: 0,
            background: multiSelectMode ? '#FFF3ED' : '#F0EDE6',
            color: multiSelectMode ? '#FF6B35' : '#5F5E5A',
            border: multiSelectMode ? '2px solid #FF6B35' : '2px solid transparent',
            fontSize: 16,
          }}
        >
          {multiSelectMode ? '取消多选' : '多选'}
        </button>

        {multiSelectMode ? (
          <>
            {/* 已选数量 */}
            <div style={{ flex: 1, fontSize: 17, color: '#5F5E5A', fontWeight: 500 }}>
              已选
              <span style={{ color: '#FF6B35', fontWeight: 700, margin: '0 4px' }}>
                {selectedIds.size}
              </span>
              项
            </div>

            {/* 批量恢复 */}
            <button
              onClick={handleBatchRestore}
              disabled={selectedIds.size === 0}
              style={{
                ...btnBase, height: 52, padding: '0 20px', flexShrink: 0,
                background: selectedIds.size > 0 ? '#EEF7F3' : '#F0EDE6',
                color: selectedIds.size > 0 ? '#0F6E56' : '#B4B2A9',
                border: selectedIds.size > 0 ? '2px solid #0F6E56' : '2px solid transparent',
                fontSize: 16, fontWeight: 600,
                cursor: selectedIds.size > 0 ? 'pointer' : 'not-allowed',
              }}
            >
              批量恢复
            </button>

            {/* 批量沽清 */}
            <button
              onClick={handleBatchSoldout}
              disabled={selectedIds.size === 0}
              style={{
                ...btnBase, height: 52, padding: '0 24px', flexShrink: 0,
                background: selectedIds.size > 0 ? '#A32D2D' : '#ccc',
                color: '#fff', fontSize: 16, fontWeight: 600,
                cursor: selectedIds.size > 0 ? 'pointer' : 'not-allowed',
              }}
            >
              批量沽清
            </button>
          </>
        ) : (
          <div style={{ flex: 1, fontSize: 16, color: '#B4B2A9' }}>
            共 {filtered.length} 道菜品
          </div>
        )}
      </div>

      {/* ── 沽清原因弹窗 ────────────────────────────────────── */}
      {soldoutModal && (
        <SoldoutModal
          dish={soldoutModal}
          onConfirm={handleConfirmSoldout}
          onCancel={() => setSoldoutModal(null)}
        />
      )}
    </div>
  );
}

export default SoldOutPage;
