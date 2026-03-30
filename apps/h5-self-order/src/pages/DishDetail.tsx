import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';
import { fetchDishDetail } from '@/api/menuApi';
import type { DishItem } from '@/api/menuApi';
import AllergenBadge from '@/components/AllergenBadge';

/** 菜品详情页 — 大图轮播 + 溯源 + 营养 + 定制 */
export default function DishDetail() {
  const { id } = useParams<{ id: string }>();
  const { t } = useLang();
  const navigate = useNavigate();
  const storeId = useOrderStore((s) => s.storeId);
  const addToCart = useOrderStore((s) => s.addToCart);

  const [dish, setDish] = useState<DishItem | null>(null);
  const [activeImage, setActiveImage] = useState(0);
  const [quantity, setQuantity] = useState(1);
  const [selections, setSelections] = useState<Record<string, string[]>>({});

  useEffect(() => {
    if (!storeId || !id) return;
    fetchDishDetail(storeId, id).then(setDish).catch(() => { /* 404 */ });
  }, [storeId, id]);

  const handleSelect = (groupName: string, itemId: string, maxSelect: number) => {
    setSelections((prev) => {
      const current = prev[groupName] ?? [];
      if (current.includes(itemId)) {
        return { ...prev, [groupName]: current.filter((i) => i !== itemId) };
      }
      if (maxSelect === 1) {
        return { ...prev, [groupName]: [itemId] };
      }
      if (current.length >= maxSelect) return prev;
      return { ...prev, [groupName]: [...current, itemId] };
    });
  };

  const handleAdd = () => {
    if (!dish) return;
    addToCart(dish, quantity, selections);
    navigate(-1);
  };

  // 计算加价后单价
  const unitPrice = (() => {
    if (!dish) return 0;
    let p = dish.price;
    for (const opt of dish.customOptions) {
      const sel = selections[opt.groupName] ?? [];
      for (const item of opt.items) {
        if (sel.includes(item.id)) p += item.priceAdjust;
      }
    }
    return p;
  })();

  if (!dish) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--tx-bg-primary)', color: 'var(--tx-text-tertiary)',
      }}>
        {t('loading')}
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--tx-bg-primary)', paddingBottom: 100 }}>
      {/* 大图轮播 */}
      <div style={{ position: 'relative', aspectRatio: '4/3', background: '#000' }}>
        <img
          src={dish.images[activeImage] ?? '/placeholder-dish.png'}
          alt={dish.name}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
        {/* 返回按钮 */}
        <button
          className="tx-pressable"
          onClick={() => navigate(-1)}
          style={{
            position: 'absolute', top: 12, left: 12,
            width: 40, height: 40, borderRadius: 20,
            background: 'rgba(0,0,0,0.5)', display: 'flex',
            alignItems: 'center', justifyContent: 'center',
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
            <path d="M15 19l-7-7 7-7" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
        {/* 图片指示器 */}
        {dish.images.length > 1 && (
          <div style={{
            position: 'absolute', bottom: 12, left: 0, right: 0,
            display: 'flex', justifyContent: 'center', gap: 6,
          }}>
            {dish.images.map((_, idx) => (
              <button
                key={idx}
                onClick={() => setActiveImage(idx)}
                style={{
                  width: activeImage === idx ? 20 : 8, height: 8,
                  borderRadius: 4, transition: 'width 0.2s',
                  background: activeImage === idx ? 'var(--tx-brand)' : 'rgba(255,255,255,0.4)',
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* 菜品基本信息 */}
      <div style={{ padding: '20px 16px' }}>
        <h1 style={{ fontSize: 'var(--tx-font-xl)', fontWeight: 700, color: 'var(--tx-text-primary)' }}>
          {dish.name}
        </h1>
        <p style={{ marginTop: 6, fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)' }}>
          {dish.description}
        </p>
        <div style={{ marginTop: 12, display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ fontSize: 'var(--tx-font-xxl)', fontWeight: 700, color: 'var(--tx-brand)' }}>
            {t('yuan')}{dish.price}
          </span>
          {dish.memberPrice != null && dish.memberPrice < dish.price && (
            <span style={{
              fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-tertiary)',
              textDecoration: 'line-through',
            }}>
              {t('yuan')}{dish.memberPrice}
            </span>
          )}
        </div>

        {/* 标签 */}
        {dish.tags.length > 0 && (
          <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap' }}>
            {dish.tags.map((tag) => (
              <span key={tag.type} style={{
                padding: '4px 10px', borderRadius: 'var(--tx-radius-sm)',
                background: 'var(--tx-brand-light)', color: 'var(--tx-brand)',
                fontSize: 'var(--tx-font-xs)', fontWeight: 600,
              }}>
                {tag.label}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 食材溯源 */}
      {dish.traceability && (
        <Section title={t('traceability')}>
          <InfoRow label={t('origin')} value={dish.traceability.origin} />
          <InfoRow label={t('supplier')} value={dish.traceability.supplier} />
          <InfoRow label={t('arrivalDate')} value={dish.traceability.arrivalDate} />
        </Section>
      )}

      {/* 营养信息 */}
      {dish.nutrition && (
        <Section title={t('nutrition')}>
          <div style={{ display: 'flex', gap: 16 }}>
            <NutritionPill label={t('calories')} value={`${dish.nutrition.calories}kcal`} />
            <NutritionPill label={t('protein')} value={`${dish.nutrition.protein}g`} />
            <NutritionPill label={t('fat')} value={`${dish.nutrition.fat}g`} />
          </div>
        </Section>
      )}

      {/* 过敏原提示 */}
      {dish.allergens.length > 0 && (
        <Section title={t('allergens')}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {dish.allergens.map((a) => (
              <AllergenBadge key={a.code} allergen={a} />
            ))}
          </div>
        </Section>
      )}

      {/* 定制选项 */}
      {dish.customOptions.length > 0 && (
        <Section title={t('customize')}>
          {dish.customOptions.map((opt) => (
            <div key={opt.groupName} style={{ marginBottom: 16 }}>
              <div style={{
                fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)',
                marginBottom: 8,
              }}>
                {opt.groupName}
                {opt.required && <span style={{ color: 'var(--tx-danger)', marginLeft: 4 }}>*</span>}
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {opt.items.map((item) => {
                  const selected = (selections[opt.groupName] ?? []).includes(item.id);
                  return (
                    <button
                      key={item.id}
                      className="tx-pressable"
                      onClick={() => handleSelect(opt.groupName, item.id, opt.maxSelect)}
                      style={{
                        padding: '10px 16px',
                        borderRadius: 'var(--tx-radius-md)',
                        background: selected ? 'var(--tx-brand-light)' : 'var(--tx-bg-tertiary)',
                        border: selected ? '1.5px solid var(--tx-brand)' : '1.5px solid transparent',
                        color: selected ? 'var(--tx-brand)' : 'var(--tx-text-secondary)',
                        fontSize: 'var(--tx-font-sm)', fontWeight: selected ? 600 : 400,
                        transition: 'all 0.15s',
                      }}
                    >
                      {item.name}
                      {item.priceAdjust > 0 && (
                        <span style={{ marginLeft: 4, fontSize: 'var(--tx-font-xs)' }}>
                          +{t('yuan')}{item.priceAdjust}
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </Section>
      )}

      {/* 底部加入购物车 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        padding: '12px 16px',
        paddingBottom: 'calc(12px + var(--safe-area-bottom))',
        background: 'var(--tx-bg-secondary)',
        borderTop: '1px solid rgba(255,255,255,0.06)',
        display: 'flex', alignItems: 'center', gap: 12,
      }}>
        {/* 数量选择 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button
            className="tx-pressable"
            onClick={() => setQuantity((q) => Math.max(1, q - 1))}
            style={{
              width: 36, height: 36, borderRadius: 18,
              background: 'var(--tx-bg-tertiary)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'var(--tx-text-primary)', fontSize: 20,
            }}
          >
            -
          </button>
          <span style={{ fontSize: 'var(--tx-font-lg)', fontWeight: 700, color: 'var(--tx-text-primary)', minWidth: 24, textAlign: 'center' }}>
            {quantity}
          </span>
          <button
            className="tx-pressable"
            onClick={() => setQuantity((q) => q + 1)}
            style={{
              width: 36, height: 36, borderRadius: 18,
              background: 'var(--tx-brand)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontSize: 20,
            }}
          >
            +
          </button>
        </div>

        {/* 加入购物车按钮 */}
        <button
          className="tx-pressable"
          onClick={handleAdd}
          style={{
            flex: 1, height: 50, borderRadius: 'var(--tx-radius-full)',
            background: 'var(--tx-brand)',
            color: '#fff', fontSize: 'var(--tx-font-md)', fontWeight: 700,
          }}
        >
          {t('addToCart')} {t('yuan')}{(unitPrice * quantity).toFixed(2)}
        </button>
      </div>
    </div>
  );
}

/* ---- 辅助组件 ---- */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      margin: '0 16px 16px', padding: 16,
      borderRadius: 'var(--tx-radius-md)',
      background: 'var(--tx-bg-card)',
    }}>
      <div style={{
        fontSize: 'var(--tx-font-md)', fontWeight: 600,
        color: 'var(--tx-text-primary)', marginBottom: 12,
      }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between',
      padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.04)',
    }}>
      <span style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-tertiary)' }}>{label}</span>
      <span style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-primary)' }}>{value}</span>
    </div>
  );
}

function NutritionPill({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      flex: 1, padding: '12px 8px', borderRadius: 'var(--tx-radius-md)',
      background: 'var(--tx-bg-tertiary)', textAlign: 'center',
    }}>
      <div style={{ fontSize: 'var(--tx-font-lg)', fontWeight: 700, color: 'var(--tx-text-primary)' }}>
        {value}
      </div>
      <div style={{ fontSize: 'var(--tx-font-xs)', color: 'var(--tx-text-tertiary)', marginTop: 2 }}>
        {label}
      </div>
    </div>
  );
}
