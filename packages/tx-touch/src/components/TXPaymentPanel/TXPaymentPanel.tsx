import React, { useState } from 'react';
import { TXButton } from '../TXButton/TXButton';
import { TXNumpad } from '../TXNumpad/TXNumpad';
import styles from './TXPaymentPanel.module.css';

export interface TXPaymentPanelItem {
  name: string;
  qty: number;
  price: number; // 分
}

export interface TXPaymentPanelProps {
  /** 合计，单位：分 */
  total: number;
  /** 优惠金额，单位：分 */
  discount?: number;
  items: TXPaymentPanelItem[];
  onPayByQR: () => void;
  onPayByCash: (amount: number) => void;
  onPayByCard: () => void;
  onPayByCredit: () => void;
  onCancel: () => void;
}

function fenToYuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

export function TXPaymentPanel({
  total,
  discount = 0,
  items,
  onPayByQR,
  onPayByCash,
  onPayByCard,
  onPayByCredit,
  onCancel,
}: TXPaymentPanelProps) {
  const [showNumpad, setShowNumpad] = useState(false);
  const [cashInput, setCashInput] = useState('');
  const [detailExpanded, setDetailExpanded] = useState(false);

  const actualTotal = total - discount;
  const cashAmount = parseFloat(cashInput) * 100; // 元转分
  const change = isNaN(cashAmount) ? 0 : Math.max(0, cashAmount - actualTotal);

  const handleCashConfirm = (val: number) => {
    onPayByCash(val * 100); // 元转分
    setShowNumpad(false);
  };

  return (
    <div className={styles.panel}>
      {/* 金额汇总 */}
      <div className={styles.summary}>
        <div className={styles.totalRow}>
          <span className={styles.totalLabel}>合计</span>
          <span className={styles.totalAmount}>¥{fenToYuan(actualTotal)}</span>
        </div>
        {discount > 0 && (
          <div className={styles.discountRow}>
            <span className={styles.discountLabel}>优惠</span>
            <span className={styles.discountAmount}>-¥{fenToYuan(discount)}</span>
          </div>
        )}
      </div>

      {/* 支付方式 */}
      {!showNumpad ? (
        <div className={styles.payMethods}>
          <div className={styles.payRow}>
            <TXButton size="large" variant="primary" onPress={onPayByQR}>
              扫码支付
            </TXButton>
            <TXButton
              size="large"
              variant="secondary"
              onPress={() => setShowNumpad(true)}
            >
              现金支付
            </TXButton>
          </div>
          <div className={styles.payRow}>
            <TXButton size="large" variant="secondary" onPress={onPayByCard}>
              银联刷卡
            </TXButton>
            <TXButton size="large" variant="ghost" onPress={onPayByCredit}>
              企业挂账
            </TXButton>
          </div>
        </div>
      ) : (
        <div className={styles.cashSection}>
          <div className={styles.cashHeader}>
            <span className={styles.cashTitle}>现金收款</span>
            {!isNaN(cashAmount) && cashAmount >= actualTotal && (
              <span className={styles.changeHint}>
                找零：¥{fenToYuan(change)}
              </span>
            )}
          </div>
          <TXNumpad
            value={cashInput}
            onChange={setCashInput}
            onConfirm={handleCashConfirm}
            allowDecimal={true}
            label="请输入收款金额（元）"
          />
          <TXButton
            variant="ghost"
            size="normal"
            onPress={() => {
              setShowNumpad(false);
              setCashInput('');
            }}
          >
            返回其他支付方式
          </TXButton>
        </div>
      )}

      {/* 订单明细（可折叠） */}
      <div className={styles.detail}>
        <button
          type="button"
          className={styles.detailToggle}
          onClick={() => setDetailExpanded(!detailExpanded)}
        >
          <span>订单明细（{items.length}项）</span>
          <span className={styles.detailArrow}>{detailExpanded ? '▲' : '▼'}</span>
        </button>
        {detailExpanded && (
          <ul className={styles.detailList}>
            {items.map((item, idx) => (
              <li key={idx} className={styles.detailItem}>
                <span className={styles.detailName}>
                  {item.name}
                  <span className={styles.detailQty}> ×{item.qty}</span>
                </span>
                <span className={styles.detailPrice}>¥{fenToYuan(item.price * item.qty)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* 取消按钮 */}
      <div className={styles.cancelRow}>
        <TXButton variant="ghost" size="fullwidth" onPress={onCancel}>
          取消
        </TXButton>
      </div>
    </div>
  );
}

export default TXPaymentPanel;
