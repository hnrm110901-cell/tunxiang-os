// @deprecated — use CartPanel from @tx-ds/biz instead
import { useLang } from '@/i18n/LangContext';
import styles from './CartBar.module.css';

interface CartBarProps {
  count: number;
  total: number;
  onViewCart: () => void;
  onCheckout: () => void;
}

export default function CartBar({ count, total, onViewCart, onCheckout }: CartBarProps) {
  const { t } = useLang();

  if (count === 0) return null;

  return (
    <div className={`${styles.bar} tx-slide-up`}>
      <button className={`${styles.cartIcon} tx-pressable`} onClick={onViewCart}>
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <span className={styles.badge}>{count}</span>
      </button>

      <div className={styles.totalSection} onClick={onViewCart}>
        <span className={styles.totalLabel}>{t('total')}</span>
        <span className={styles.totalAmount}>{t('yuan')}{total.toFixed(2)}</span>
      </div>

      <button className={`${styles.checkoutBtn} tx-pressable`} onClick={onCheckout}>
        {t('submitOrder')}
      </button>
    </div>
  );
}
