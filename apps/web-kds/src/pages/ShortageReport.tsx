/**
 * ShortageReport — 缺料上报
 *
 * 选择缺少的原料
 * 一键上报（调用 POST /kds/task/{id}/shortage）
 * 联动沽清
 * 深色背景，触控优化（最小48x48按钮，最小16px字体）
 */
import { useState } from 'react';

// ─── Types ───

interface Ingredient {
  id: string;
  name: string;
  category: string;
  unit: string;
  currentStock: number;
  safetyStock: number;
}

interface ShortageRecord {
  id: string;
  ingredientId: string;
  ingredientName: string;
  reportedAt: number;
  reporter: string;
  affectedDishes: string[];
  status: 'reported' | 'confirmed' | 'resolved';
}

// ─── Mock Data ───

const MOCK_INGREDIENTS: Ingredient[] = [
  { id: 'i1', name: '鲈鱼', category: '海鲜', unit: '条', currentStock: 2, safetyStock: 10 },
  { id: 'i2', name: '活虾', category: '海鲜', unit: '斤', currentStock: 0, safetyStock: 20 },
  { id: 'i3', name: '五花肉', category: '肉类', unit: '斤', currentStock: 3, safetyStock: 15 },
  { id: 'i4', name: '鸡蛋', category: '蛋奶', unit: '个', currentStock: 12, safetyStock: 50 },
  { id: 'i5', name: '西兰花', category: '蔬菜', unit: '斤', currentStock: 0, safetyStock: 8 },
  { id: 'i6', name: '剁椒酱', category: '调料', unit: '瓶', currentStock: 1, safetyStock: 5 },
  { id: 'i7', name: '豆腐', category: '豆制品', unit: '块', currentStock: 8, safetyStock: 20 },
  { id: 'i8', name: '鱼头', category: '海鲜', unit: '个', currentStock: 0, safetyStock: 8 },
  { id: 'i9', name: '青椒', category: '蔬菜', unit: '斤', currentStock: 5, safetyStock: 10 },
  { id: 'i10', name: '排骨', category: '肉类', unit: '斤', currentStock: 1, safetyStock: 12 },
];

const CATEGORIES = ['全部', '海鲜', '肉类', '蔬菜', '蛋奶', '调料', '豆制品'];

const MOCK_RECORDS: ShortageRecord[] = [
  { id: 'r1', ingredientId: 'i2', ingredientName: '活虾', reportedAt: Date.now() - 3600000, reporter: '王师傅', affectedDishes: ['口味虾', '蒜蓉虾'], status: 'confirmed' },
  { id: 'r2', ingredientId: 'i5', ingredientName: '西兰花', reportedAt: Date.now() - 7200000, reporter: '李师傅', affectedDishes: ['蒜蓉西兰花'], status: 'reported' },
];

// ─── Component ───

export function ShortageReport() {
  const [ingredients] = useState<Ingredient[]>(MOCK_INGREDIENTS);
  const [records, setRecords] = useState<ShortageRecord[]>(MOCK_RECORDS);
  const [selectedCategory, setSelectedCategory] = useState('全部');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [tab, setTab] = useState<'report' | 'history'>('report');

  const filtered = selectedCategory === '全部'
    ? ingredients
    : ingredients.filter(i => i.category === selectedCategory);

  const toggleSelect = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    // 实际调用 POST /api/v1/kds/task/{id}/shortage
    await new Promise(r => setTimeout(r, 800));

    const newRecords: ShortageRecord[] = [...selectedIds].map(id => {
      const ing = ingredients.find(i => i.id === id)!;
      return {
        id: `r${Date.now()}_${id}`,
        ingredientId: id,
        ingredientName: ing.name,
        reportedAt: Date.now(),
        reporter: '当前操作员',
        affectedDishes: [],
        status: 'reported' as const,
      };
    });

    setRecords(prev => [...newRecords, ...prev]);
    setSelectedIds(new Set());
    setShowConfirm(false);
    setSubmitting(false);
  };

  const getStockColor = (ing: Ingredient): string => {
    if (ing.currentStock === 0) return '#A32D2D';
    if (ing.currentStock < ing.safetyStock * 0.3) return '#BA7517';
    return '#0F6E56';
  };

  const statusLabel: Record<string, { text: string; color: string }> = {
    reported: { text: '已上报', color: '#BA7517' },
    confirmed: { text: '已确认沽清', color: '#A32D2D' },
    resolved: { text: '已补货', color: '#0F6E56' },
  };

  return (
    <div style={{
      background: '#0A0A0A', minHeight: '100vh', color: '#E0E0E0',
      fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      padding: 20,
    }}>
      {/* 顶栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 28, color: '#FF6B35' }}>缺料上报</h1>
        {tab === 'report' && selectedIds.size > 0 && (
          <button
            onClick={() => setShowConfirm(true)}
            style={{
              padding: '12px 32px', background: '#A32D2D', color: '#fff',
              border: 'none', borderRadius: 8, cursor: 'pointer',
              fontSize: 20, fontWeight: 'bold', minHeight: 56,
              transition: 'transform 200ms ease',
            }}
            onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
            onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
          >
            上报缺料 ({selectedIds.size})
          </button>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <button
          onClick={() => setTab('report')}
          style={{
            padding: '12px 28px', minHeight: 48,
            fontSize: 18, fontWeight: 'bold',
            background: tab === 'report' ? '#FF6B35' : '#1a1a1a',
            color: tab === 'report' ? '#fff' : '#888',
            border: 'none', borderRadius: 8, cursor: 'pointer',
          }}
        >
          选择原料
        </button>
        <button
          onClick={() => setTab('history')}
          style={{
            padding: '12px 28px', minHeight: 48,
            fontSize: 18, fontWeight: 'bold',
            background: tab === 'history' ? '#1890ff' : '#1a1a1a',
            color: tab === 'history' ? '#fff' : '#888',
            border: 'none', borderRadius: 8, cursor: 'pointer',
          }}
        >
          上报记录 ({records.length})
        </button>
      </div>

      {tab === 'report' && (
        <>
          {/* 分类筛选 */}
          <div style={{
            display: 'flex', gap: 8, marginBottom: 16,
            overflowX: 'auto', WebkitOverflowScrolling: 'touch',
            paddingBottom: 4,
          }}>
            {CATEGORIES.map(cat => (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                style={{
                  padding: '8px 20px', minHeight: 48,
                  fontSize: 16, fontWeight: selectedCategory === cat ? 'bold' : 'normal',
                  color: selectedCategory === cat ? '#fff' : '#888',
                  background: selectedCategory === cat ? '#333' : '#1a1a1a',
                  border: 'none', borderRadius: 8, cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {cat}
              </button>
            ))}
          </div>

          {/* 原料网格 */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: 12,
          }}>
            {filtered.map(ing => {
              const isSelected = selectedIds.has(ing.id);
              const stockColor = getStockColor(ing);
              const isOutOfStock = ing.currentStock === 0;

              return (
                <button
                  key={ing.id}
                  onClick={() => toggleSelect(ing.id)}
                  style={{
                    background: isSelected ? '#1a0a00' : '#111',
                    borderRadius: 12, padding: 16,
                    border: isSelected ? '3px solid #FF6B35' : `2px solid ${isOutOfStock ? '#A32D2D' : '#222'}`,
                    cursor: 'pointer', textAlign: 'left',
                    color: '#E0E0E0', minHeight: 100,
                    transition: 'transform 200ms ease',
                    display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
                  }}
                  onTouchStart={e => (e.currentTarget.style.transform = 'scale(0.97)')}
                  onTouchEnd={e => (e.currentTarget.style.transform = 'scale(1)')}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <span style={{ fontSize: 20, fontWeight: 'bold', color: '#fff' }}>{ing.name}</span>
                    {isSelected && (
                      <span style={{ fontSize: 20, color: '#FF6B35', fontWeight: 'bold' }}>已选</span>
                    )}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span style={{ fontSize: 16, color: '#888' }}>{ing.category}</span>
                    <span style={{
                      fontSize: 22, fontWeight: 'bold', color: stockColor,
                      fontFamily: 'JetBrains Mono, monospace',
                    }}>
                      {ing.currentStock}{ing.unit}
                    </span>
                  </div>
                  {isOutOfStock && (
                    <div style={{
                      marginTop: 6, fontSize: 16, fontWeight: 'bold',
                      color: '#A32D2D', textAlign: 'center',
                    }}>
                      已缺货
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </>
      )}

      {tab === 'history' && (
        <div>
          {records.length === 0 && (
            <div style={{ textAlign: 'center', padding: 60, color: '#666', fontSize: 20 }}>
              暂无上报记录
            </div>
          )}
          {records.map(r => {
            const st = statusLabel[r.status];
            return (
              <div key={r.id} style={{
                background: '#111', borderRadius: 10, padding: 16, marginBottom: 10,
                borderLeft: `5px solid ${st.color}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                  <span style={{ fontSize: 22, fontWeight: 'bold', color: '#fff' }}>{r.ingredientName}</span>
                  <span style={{
                    fontSize: 16, padding: '4px 12px', borderRadius: 6,
                    background: `${st.color}22`, color: st.color,
                    fontWeight: 'bold',
                  }}>
                    {st.text}
                  </span>
                </div>
                <div style={{ fontSize: 16, color: '#888' }}>
                  上报人: {r.reporter} | {new Date(r.reportedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                </div>
                {r.affectedDishes.length > 0 && (
                  <div style={{ fontSize: 16, color: '#BA7517', marginTop: 4 }}>
                    影响菜品: {r.affectedDishes.join('、')}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 确认弹窗 */}
      {showConfirm && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }}>
          <div style={{
            background: '#111', borderRadius: 16, padding: 28, width: 440,
            border: '2px solid #333',
          }}>
            <h2 style={{ margin: '0 0 16px', fontSize: 24, color: '#fff' }}>确认上报缺料</h2>
            <div style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 18, color: '#888', marginBottom: 10 }}>以下原料将标记为缺料并联动沽清：</div>
              {[...selectedIds].map(id => {
                const ing = ingredients.find(i => i.id === id);
                return ing ? (
                  <div key={id} style={{
                    padding: '10px 14px', background: '#1a0505', borderRadius: 8,
                    marginBottom: 6, fontSize: 20, fontWeight: 'bold',
                    display: 'flex', justifyContent: 'space-between',
                    border: '1px solid #A32D2D',
                  }}>
                    <span>{ing.name}</span>
                    <span style={{ color: '#A32D2D' }}>库存 {ing.currentStock}{ing.unit}</span>
                  </div>
                ) : null;
              })}
            </div>
            <div style={{ display: 'flex', gap: 12 }}>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                style={{
                  flex: 1, padding: '14px 0', background: '#A32D2D', color: '#fff',
                  border: 'none', borderRadius: 8, cursor: submitting ? 'wait' : 'pointer',
                  fontSize: 20, fontWeight: 'bold', minHeight: 56,
                  opacity: submitting ? 0.6 : 1,
                }}
              >
                {submitting ? '上报中...' : '确认上报'}
              </button>
              <button
                onClick={() => setShowConfirm(false)}
                style={{
                  flex: 1, padding: '14px 0', background: '#222', color: '#888',
                  border: 'none', borderRadius: 8, cursor: 'pointer',
                  fontSize: 20, minHeight: 56,
                }}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
