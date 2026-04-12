import React from 'react';
import styles from './CartPanel.module.css';
import { formatPrice } from '../../utils/formatPrice';
import { cn } from '../../utils/cn';
import type { CartPanelProps } from './types';

/**
 * CartPanel - 购物车面板（两种 mode）
 *
 * sidebar:    POS 右侧固定面板（320px），深色背景
 * bottom-bar: H5/移动端底部栏（56px），含购物车图标 + 结算按钮
 */
export default function CartPanel({
  mode,
  items,
  totalFen,
  discountFen = 0,
  tableNo,
  onUpdateQuantity,
  onRemoveItem,
  onClear,
  onSettle,
  onHold,
  className,
}: CartPanelProps) {
  const finalFen = totalFen - discountFen;
  const itemCount = items.reduce((sum, i) => sum + i.quantity, 0);

  // ── bottom-bar mode ──────────────────────────────────────────────────────────

  if (mode === 'bottom-bar') {
    if (items.length === 0) return null;

    return (
      <div className={cn(styles.bottomBar, 'tx-slide-up', className)}>
        <div className={styles.cartIconWrap}>
          <svg
            className={styles.cartSvg}
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 100 4 2 2 0 000-4z"
              stroke="#fff"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          <span className={styles.badge}>{itemCount}</span>
        </div>

        <div className={styles.totalSection}>
          <span className={styles.totalLabel}>合计</span>
          <span className={styles.totalAmount}>{formatPrice(finalFen)}</span>
        </div>

        <button
          type="button"
          className={cn(styles.checkoutBtn, 'tx-pressable')}
          onClick={onSettle}
        >
          去结算
        </button>
      </div>
    );
  }

  // ── sidebar mode ─────────────────────────────────────────────────────────────

  return (
    <div className={cn(styles.sidebar, className)}>
      {/* Header */}
      <div className={styles.sidebarHeader}>
        <div className={styles.sidebarTitle}>
          <span>当前订单</span>
          {tableNo && <span className={styles.tableTag}>桌号 {tableNo}</span>}
        </div>
        {onClear && items.length > 0 && (
          <button
            type="button"
            className={styles.clearBtn}
            onClick={onClear}
          >
            清空
          </button>
        )}
      </div>

      {/* Item list */}
      <div className={styles.itemList}>
        {items.length === 0 && (
          <div className={styles.emptyHint}>点击菜品加入订单</div>
        )}
        {items.map((item) => (
          <div key={item.id} className={styles.itemRow}>
            <div className={styles.itemInfo}>
              <div className={styles.itemName}>{item.name}</div>
              {item.notes && (
                <div className={styles.itemNotes}>{item.notes}</div>
              )}
              <div className={styles.itemPrice}>
                {formatPrice(item.priceFen)} x {item.quantity}
              </div>
            </div>
            <div className={styles.qtyControls}>
              <button
                type="button"
                className={cn(styles.qtyBtn, 'tx-pressable')}
                onClick={() =>
                  item.quantity > 1
                    ? onUpdateQuantity(item.id, item.quantity - 1)
                    : onRemoveItem(item.id)
                }
              >
                -
              </button>
              <span className={styles.qtyValue}>{item.quantity}</span>
              <button
                type="button"
                className={cn(styles.qtyBtn, 'tx-pressable')}
                onClick={() => onUpdateQuantity(item.id, item.quantity + 1)}
              >
                +
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className={styles.sidebarFooter}>
        {/* Subtotal */}
        <div className={styles.subtotalRow}>
          <span>小计</span>
          <span>{formatPrice(totalFen)}</span>
        </div>

        {/* Discount */}
        {discountFen > 0 && (
          <div className={styles.discountRow}>
            <span>优惠</span>
            <span>-{formatPrice(discountFen)}</span>
          </div>
        )}

        {/* Final total */}
        <div className={styles.finalRow}>
          <span>应付</span>
          <span>{formatPrice(finalFen)}</span>
        </div>

        {/* Action buttons */}
        <div className={styles.actionRow}>
          {onHold && (
            <button
              type="button"
              className={cn(styles.holdBtn, 'tx-pressable')}
              onClick={onHold}
            >
              挂单
            </button>
          )}
          <button
            type="button"
            className={cn(styles.settleBtn, 'tx-pressable')}
            disabled={items.length === 0}
            onClick={onSettle}
          >
            结算 {formatPrice(finalFen)}
          </button>
        </div>
      </div>
    </div>
  );
}
