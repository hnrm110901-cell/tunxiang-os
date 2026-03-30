import { useNavigate } from 'react-router-dom';
import { useLang } from '@/i18n/LangContext';
import { useOrderStore } from '@/store/useOrderStore';

/** 智能购物车页 — 凑单推荐 + AA分摊 */
export default function Cart() {
  const { t } = useLang();
  const navigate = useNavigate();
  const cart = useOrderStore((s) => s.cart);
  const remark = useOrderStore((s) => s.remark);
  const aaPeople = useOrderStore((s) => s.aaPeople);
  const updateQuantity = useOrderStore((s) => s.updateQuantity);
  const removeFromCart = useOrderStore((s) => s.removeFromCart);
  const setRemark = useOrderStore((s) => s.setRemark);
  const setAaPeople = useOrderStore((s) => s.setAaPeople);
  const cartTotal = useOrderStore((s) => s.cartTotal);
  const perPersonAmount = useOrderStore((s) => s.perPersonAmount);

  const total = cartTotal();

  // 凑单推荐逻辑（示例：满100减20）
  const dealThreshold = 100;
  const dealDiscount = 20;
  const amountToNextDeal = total < dealThreshold ? dealThreshold - total : 0;

  if (cart.length === 0) {
    return (
      <div style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        background: 'var(--tx-bg-primary)', padding: 32,
      }}>
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" style={{ opacity: 0.3 }}>
          <path d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z" stroke="#666" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <div style={{ marginTop: 16, color: 'var(--tx-text-secondary)', fontSize: 'var(--tx-font-md)' }}>
          {t('cartEmpty')}
        </div>
        <div style={{ marginTop: 8, color: 'var(--tx-text-tertiary)', fontSize: 'var(--tx-font-sm)' }}>
          {t('cartEmptyHint')}
        </div>
        <button
          className="tx-pressable"
          onClick={() => navigate('/menu')}
          style={{
            marginTop: 32, padding: '12px 40px',
            borderRadius: 'var(--tx-radius-full)',
            background: 'var(--tx-brand)', color: '#fff',
            fontSize: 'var(--tx-font-md)', fontWeight: 600,
          }}
        >
          {t('menuTitle')}
        </button>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: '100vh', background: 'var(--tx-bg-primary)',
      paddingBottom: 120,
    }}>
      {/* 顶部栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', padding: '16px',
        gap: 12,
      }}>
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
          {t('cartTitle')}
        </h1>
      </div>

      {/* 凑单推荐 */}
      {amountToNextDeal > 0 && (
        <div
          className="tx-fade-in"
          style={{
            margin: '0 16px 16px', padding: '12px 16px',
            borderRadius: 'var(--tx-radius-md)',
            background: 'var(--tx-brand-light)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}
        >
          <span style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-brand)' }}>
            {t('dealRecommend')}: {t('yuan')}{amountToNextDeal.toFixed(0)} {t('yuan')}{dealDiscount}
          </span>
          <button
            className="tx-pressable"
            onClick={() => navigate('/menu')}
            style={{
              padding: '6px 14px', borderRadius: 'var(--tx-radius-full)',
              background: 'var(--tx-brand)', color: '#fff',
              fontSize: 'var(--tx-font-xs)', fontWeight: 600,
            }}
          >
            +
          </button>
        </div>
      )}

      {/* 菜品列表 */}
      <div style={{ padding: '0 16px' }}>
        {cart.map((item) => (
          <div
            key={item.cartKey}
            className="tx-fade-in"
            style={{
              display: 'flex', gap: 12, padding: 12,
              background: 'var(--tx-bg-card)',
              borderRadius: 'var(--tx-radius-md)',
              marginBottom: 10,
            }}
          >
            <img
              src={item.dish.images[0] ?? '/placeholder-dish.png'}
              alt={item.dish.name}
              loading="lazy"
              style={{ width: 72, height: 72, borderRadius: 8, objectFit: 'cover', flexShrink: 0 }}
            />
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
              <div style={{
                fontSize: 'var(--tx-font-sm)', fontWeight: 600,
                color: 'var(--tx-text-primary)',
              }}>
                {item.dish.name}
              </div>
              {/* 选项摘要 */}
              {Object.keys(item.customSelections).length > 0 && (
                <div style={{
                  fontSize: 'var(--tx-font-xs)', color: 'var(--tx-text-tertiary)', marginTop: 2,
                }}>
                  {Object.entries(item.customSelections)
                    .map(([k, v]) => `${k}: ${v.join(',')}`)
                    .join(' | ')}
                </div>
              )}
              <div style={{ flex: 1 }} />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 'var(--tx-font-md)', fontWeight: 700, color: 'var(--tx-brand)' }}>
                  {t('yuan')}{item.subtotal.toFixed(2)}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <button
                    className="tx-pressable"
                    onClick={() => {
                      if (item.quantity <= 1) removeFromCart(item.cartKey);
                      else updateQuantity(item.cartKey, item.quantity - 1);
                    }}
                    style={{
                      width: 30, height: 30, borderRadius: 15,
                      background: 'var(--tx-bg-tertiary)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: 'var(--tx-text-secondary)', fontSize: 18,
                    }}
                  >
                    {item.quantity <= 1 ? (
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                        <path d="M6 6l12 12M6 18L18 6" stroke="#A0A0A0" strokeWidth="2" strokeLinecap="round"/>
                      </svg>
                    ) : '-'}
                  </button>
                  <span style={{
                    fontSize: 'var(--tx-font-sm)', fontWeight: 600,
                    color: 'var(--tx-text-primary)', minWidth: 20, textAlign: 'center',
                  }}>
                    {item.quantity}
                  </span>
                  <button
                    className="tx-pressable"
                    onClick={() => updateQuantity(item.cartKey, item.quantity + 1)}
                    style={{
                      width: 30, height: 30, borderRadius: 15,
                      background: 'var(--tx-brand)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: '#fff', fontSize: 18,
                    }}
                  >
                    +
                  </button>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* AA分摊 */}
      <div style={{
        margin: '16px', padding: 16,
        borderRadius: 'var(--tx-radius-md)',
        background: 'var(--tx-bg-card)',
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <span style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)' }}>
            {t('aaSplit')}
          </span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <button
              className="tx-pressable"
              onClick={() => setAaPeople(aaPeople - 1)}
              style={{
                width: 30, height: 30, borderRadius: 15,
                background: 'var(--tx-bg-tertiary)',
                color: 'var(--tx-text-secondary)', fontSize: 18,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              -
            </button>
            <span style={{ fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-primary)', minWidth: 20, textAlign: 'center' }}>
              {aaPeople}
            </span>
            <button
              className="tx-pressable"
              onClick={() => setAaPeople(aaPeople + 1)}
              style={{
                width: 30, height: 30, borderRadius: 15,
                background: 'var(--tx-brand)',
                color: '#fff', fontSize: 18,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              +
            </button>
          </div>
        </div>
        {aaPeople > 1 && (
          <div style={{
            marginTop: 8, textAlign: 'right',
            fontSize: 'var(--tx-font-sm)', color: 'var(--tx-text-secondary)',
          }}>
            {t('aaPeople').replace('{count}', String(aaPeople))}
            {', '}
            {t('aaPerPerson')} <span style={{ color: 'var(--tx-brand)', fontWeight: 700 }}>
              {t('yuan')}{perPersonAmount().toFixed(2)}
            </span>
          </div>
        )}
      </div>

      {/* 备注 */}
      <div style={{ margin: '0 16px 16px' }}>
        <textarea
          value={remark}
          onChange={(e) => setRemark(e.target.value)}
          placeholder={t('remarkPlaceholder')}
          rows={3}
          style={{
            width: '100%', padding: 14,
            borderRadius: 'var(--tx-radius-md)',
            background: 'var(--tx-bg-card)',
            color: 'var(--tx-text-primary)',
            fontSize: 'var(--tx-font-sm)',
            resize: 'none',
          }}
        />
      </div>

      {/* 底部结算 */}
      <div style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        padding: '12px 16px',
        paddingBottom: 'calc(12px + var(--safe-area-bottom))',
        background: 'var(--tx-bg-secondary)',
        borderTop: '1px solid rgba(255,255,255,0.06)',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 'var(--tx-font-xs)', color: 'var(--tx-text-secondary)' }}>{t('total')}</div>
          <div style={{ fontSize: 'var(--tx-font-xxl)', fontWeight: 700, color: 'var(--tx-brand)' }}>
            {t('yuan')}{total.toFixed(2)}
          </div>
        </div>
        <button
          className="tx-pressable"
          onClick={() => navigate('/checkout')}
          style={{
            padding: '0 32px', height: 50,
            borderRadius: 'var(--tx-radius-full)',
            background: 'var(--tx-brand)', color: '#fff',
            fontSize: 'var(--tx-font-md)', fontWeight: 700,
          }}
        >
          {t('submitOrder')}
        </button>
      </div>
    </div>
  );
}
