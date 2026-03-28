/**
 * TXCartPanel — POS 右侧购物车面板（触控优化）
 *
 * 规范:
 *   - 所有按钮 ≥ 48×48px
 *   - 结算按钮 72px 高
 *   - 数量加减按钮 48×48px
 *   - 触控反馈 scale(0.97)
 *   - 毛利率低于阈值红色标注
 */
import { useCallback } from 'react';
import type { OrderItem } from '../../store/orderStore';
import styles from './TXCartPanel.module.css';

export interface TXCartPanelProps {
  tableNo: string;
  orderNo?: string | null;
  items: OrderItem[];
  totalFen: number;
  discountFen: number;
  onUpdateQuantity: (id: string, qty: number) => void;
  onRemoveItem: (id: string) => void;
  onSettle: () => void;
  onBack: () => void;
  onHold?: () => void;       // 挂单
}

const fen2yuan = (fen: number) => `¥${(fen / 100).toFixed(2)}`;

export function TXCartPanel({
  tableNo,
  orderNo,
  items,
  totalFen,
  discountFen,
  onUpdateQuantity,
  onRemoveItem,
  onSettle,
  onBack,
  onHold,
}: TXCartPanelProps) {
  const finalFen = totalFen - discountFen;
  const itemCount = items.reduce((s, i) => s + i.quantity, 0);

  const handleMinus = useCallback((item: OrderItem) => {
    if (item.quantity > 1) {
      onUpdateQuantity(item.id, item.quantity - 1);
    } else {
      onRemoveItem(item.id);
    }
  }, [onUpdateQuantity, onRemoveItem]);

  return (
    <aside className={styles.panel} aria-label="购物车">
      {/* 顶部: 桌号+订单号 */}
      <header className={styles.header}>
        <div className={styles.tableInfo}>
          <span className={styles.tableNo}>{tableNo}号桌</span>
          {orderNo && <span className={styles.orderNo}>{orderNo}</span>}
        </div>
        <span className={styles.itemCount}>{itemCount}道菜</span>
      </header>

      {/* 订单列表 */}
      <div className={styles.list}>
        {items.length === 0 && (
          <div className={styles.empty}>
            <span className={styles.emptyIcon}>📋</span>
            <span className={styles.emptyText}>点击菜品加入订单</span>
          </div>
        )}
        {items.map(item => (
          <div key={item.id} className={styles.cartItem}>
            <div className={styles.cartItemInfo}>
              <div className={styles.cartItemName}>{item.name}</div>
              <div className={styles.cartItemPrice}>{fen2yuan(item.priceFen * item.quantity)}</div>
            </div>
            <div className={styles.cartItemActions}>
              <button
                className={`${styles.qtyBtn} tx-pressable`}
                onClick={() => handleMinus(item)}
                aria-label={`减少 ${item.name}`}
              >
                −
              </button>
              <span className={styles.qty}>{item.quantity}</span>
              <button
                className={`${styles.qtyBtn} tx-pressable`}
                onClick={() => onUpdateQuantity(item.id, item.quantity + 1)}
                aria-label={`增加 ${item.name}`}
              >
                +
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* 底部: 汇总 + 操作 */}
      <footer className={styles.footer}>
        {discountFen > 0 && (
          <div className={styles.discountRow}>
            <span>优惠</span>
            <span className={styles.discountAmount}>−{fen2yuan(discountFen)}</span>
          </div>
        )}
        <div className={styles.totalRow}>
          <span className={styles.totalLabel}>应付</span>
          <span className={styles.totalAmount}>{fen2yuan(finalFen)}</span>
        </div>

        <div className={styles.actions}>
          <button className={`${styles.btnSecondary} tx-pressable`} onClick={onBack}>
            返回
          </button>
          {onHold && (
            <button className={`${styles.btnSecondary} tx-pressable`} onClick={onHold}>
              挂单
            </button>
          )}
          <button
            className={`${styles.btnPrimary} tx-pressable`}
            onClick={onSettle}
            disabled={items.length === 0}
          >
            结算
          </button>
        </div>
      </footer>
    </aside>
  );
}
