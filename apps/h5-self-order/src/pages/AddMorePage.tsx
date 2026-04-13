import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';
import { fetchCategories, fetchDishes } from '@/api/menuApi';
import { getOrderSummary, createOrder } from '@/api/orderApi';
import { CategoryNav, DishCard } from '@tx-ds/biz';
import type { DishData } from '@tx-ds/biz';
import type { Category, DishItem } from '@/api/menuApi';
import type { OrderSummary } from '@/api/orderApi';

/** 加菜页 — 已有订单基础上追加菜品 */
export default function AddMorePage() {
  const { t } = useLang();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const existingOrderId = searchParams.get('orderId') ?? '';

  const storeId = useOrderStore((s) => s.storeId);
  const tableNo = useOrderStore((s) => s.tableNo);
  const storeName = useOrderStore((s) => s.storeName);
  const phone = useOrderStore((s) => s.phone);

  const [categories, setCategories] = useState<Category[]>([]);
  const [activeCat, setActiveCat] = useState('');
  const [dishes, setDishes] = useState<DishItem[]>([]);
  const [existingOrder, setExistingOrder] = useState<OrderSummary | null>(null);
  // 加菜选择：dishId -> quantity
  const [addItems, setAddItems] = useState<Record<string, number>>({});
  const [submitting, setSubmitting] = useState(false);

  // 加载分类
  useEffect(() => {
    if (!storeId) return;
    fetchCategories(storeId)
      .then((cats) => {
        setCategories(cats);
        if (cats.length > 0) setActiveCat(cats[0].id);
      })
      .catch(() => {
        // Mock categories
        const mock: Category[] = [
          { id: 'hot', name: '热销', sortOrder: 0 },
          { id: 'meat', name: '荤菜', sortOrder: 1 },
          { id: 'veg', name: '素菜', sortOrder: 2 },
          { id: 'drink', name: '饮品', sortOrder: 3 },
        ];
        setCategories(mock);
        setActiveCat(mock[0].id);
      });
  }, [storeId]);

  // 加载菜品
  useEffect(() => {
    if (!storeId || !activeCat) return;
    fetchDishes(storeId, activeCat)
      .then(setDishes)
      .catch(() => setDishes([]));
  }, [storeId, activeCat]);

  // 加载已有订单摘要
  useEffect(() => {
    if (!existingOrderId) return;
    getOrderSummary(existingOrderId)
      .then(setExistingOrder)
      .catch(() => {
        // Mock
        setExistingOrder({
          orderId: existingOrderId,
          totalAmount: 128,
          discountAmount: 0,
          payableAmount: 128,
          itemCount: 4,
          items: [],
        });
      });
  }, [existingOrderId]);

  // 增减数量
  const handleAdd = useCallback((dishId: string) => {
    setAddItems((prev) => ({ ...prev, [dishId]: (prev[dishId] ?? 0) + 1 }));
  }, []);

  const handleMinus = useCallback((dishId: string) => {
    setAddItems((prev) => {
      const cur = prev[dishId] ?? 0;
      if (cur <= 1) {
        const next = { ...prev };
        delete next[dishId];
        return next;
      }
      return { ...prev, [dishId]: cur - 1 };
    });
  }, []);

  // 计算加菜总价
  const addTotal = Object.entries(addItems).reduce((sum, [dishId, qty]) => {
    const dish = dishes.find((d) => d.id === dishId);
    return sum + (dish?.price ?? 0) * qty;
  }, 0);

  const addCount = Object.values(addItems).reduce((sum, qty) => sum + qty, 0);

  // DishItem → DishData mapper for shared DishCard
  const toDishData = useCallback((d: DishItem): DishData => ({
    id: d.id,
    name: d.name,
    priceFen: Math.round(d.price * 100),
    category: activeCat,
    images: d.images,
    tags: d.tags,
    soldOut: d.soldOut,
  }), [activeCat]);

  // 提交加菜
  const handleSubmit = useCallback(async () => {
    if (submitting || addCount === 0) return;
    setSubmitting(true);
    try {
      const items = Object.entries(addItems).map(([dishId, quantity]) => ({
        dishId,
        quantity,
        customSelections: {} as Record<string, string[]>,
      }));
      const { orderId } = await createOrder({
        storeId,
        tableNo,
        items,
        phone,
        remark: `[加菜] 关联订单: ${existingOrderId}`,
      });
      navigate(`/pay-result/${orderId}?status=success&amount=${addTotal.toFixed(2)}`);
    } catch {
      // Mock
      const mockId = `ADD-${Date.now()}`;
      navigate(`/pay-result/${mockId}?status=success&amount=${addTotal.toFixed(2)}`);
    }
  }, [submitting, addCount, addItems, storeId, tableNo, phone, existingOrderId, addTotal, navigate]);

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--tx-bg-primary)',
      paddingBottom: 100,
    }}>
      {/* 顶部栏 */}
      <div style={{ display: 'flex', alignItems: 'center', padding: 16, gap: 12 }}>
        <button
          className="tx-pressable"
          onClick={() => navigate(-1)}
          style={{
            width: 40, height: 40, borderRadius: 20,
            background: 'var(--tx-bg-tertiary)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M15 19l-7-7 7-7" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
        <h1 style={{ fontSize: 'var(--tx-font-xl)', fontWeight: 700, color: 'var(--tx-text-primary)' }}>
          {t('addMoreTitle')}
        </h1>
      </div>

      {/* 当前桌台 + 已有订单信息 */}
      <div style={{
        margin: '0 16px 12px', padding: '14px 16px',
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 'var(--tx-font-sm)', fontWeight: 600, color: 'var(--tx-text-primary)' }}>
            {storeName || t('storeInfo')} &middot; {t('tableNo')} {tableNo}
          </div>
          {existingOrder && (
            <div style={{ fontSize: 'var(--tx-font-xs)', color: 'var(--tx-text-tertiary)', marginTop: 4 }}>
              {t('addMoreExisting')}: {existingOrder.itemCount}{t('addMoreDishUnit')}
              {' '}{t('yuan')}{existingOrder.payableAmount.toFixed(2)}
            </div>
          )}
        </div>
        <div style={{
          padding: '4px 10px', borderRadius: 'var(--tx-radius-full)',
          background: 'rgba(255,107,53,0.1)',
          fontSize: 'var(--tx-font-xs)', color: '#FF6B35', fontWeight: 600,
        }}>
          {t('addMoreBadge')}
        </div>
      </div>

      {/* 分类 + 菜品 */}
      <div style={{ display: 'flex', minHeight: 'calc(100vh - 260px)' }}>
        {/* 左侧分类栏 — 共享 CategoryNav */}
        <CategoryNav
          categories={categories.map((c) => ({ id: c.id, name: c.name }))}
          activeId={activeCat}
          layout="sidebar"
          onSelect={setActiveCat}
        />

        {/* 右侧菜品列表 — 共享 DishCard */}
        <div style={{ flex: 1, padding: '0 12px', overflowY: 'auto' }}>
          {dishes.length === 0 ? (
            <div style={{ textAlign: 'center', padding: 32, color: 'var(--tx-text-tertiary)', fontSize: 'var(--tx-font-sm)' }}>
              {t('loading')}
            </div>
          ) : (
            dishes.filter((d) => !d.soldOut).map((dish) => (
              <DishCard
                key={dish.id}
                dish={toDishData(dish)}
                variant="horizontal"
                quantity={addItems[dish.id] ?? 0}
                showTags
                showImage
                onAdd={() => handleAdd(dish.id)}
              />
            ))
          )}
        </div>
      </div>

      {/* 底部固定：加菜按钮 */}
      {addCount > 0 && (
        <div style={{
          position: 'fixed', bottom: 0, left: 0, right: 0,
          padding: '12px 16px',
          paddingBottom: 'calc(12px + var(--safe-area-bottom))',
          background: 'var(--tx-bg-secondary)',
          borderTop: '1px solid rgba(255,255,255,0.06)',
        }}>
          <button
            className="tx-pressable"
            onClick={handleSubmit}
            disabled={submitting}
            style={{
              width: '100%', height: 56,
              borderRadius: 'var(--tx-radius-full)',
              background: submitting ? 'var(--tx-bg-tertiary)' : '#FF6B35',
              color: submitting ? 'var(--tx-text-tertiary)' : '#fff',
              fontSize: 'var(--tx-font-lg)', fontWeight: 700,
              transition: 'background 0.2s',
            }}
          >
            {submitting
              ? t('loading')
              : `${t('addMoreSubmit')} ${t('yuan')}${addTotal.toFixed(2)}`}
          </button>
        </div>
      )}
    </div>
  );
}
