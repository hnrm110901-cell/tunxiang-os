/**
 * useCouponEligibility — 结账时查询可用优惠券
 *
 * 在 SettlePage 挂载后自动调用 campaign apply-to-order，
 * 若有可用券则将 eligible 设为 true，触发弹窗提示收银员。
 */
import { useState, useEffect, useCallback } from 'react';
import {
  checkCouponEligibility,
  applyCouponToOrder,
  type EligibleCoupon,
} from '../api/couponApi';

interface UseCouponEligibilityOptions {
  orderId: string;
  storeId: string;
  customerId: string;
  orderAmountFen: number;
  tenantId: string;
  operatorId: string;
  /** 核销成功后回调，传入减免金额（分） */
  onApplied: (discountFen: number) => void;
}

interface UseCouponEligibilityReturn {
  eligible: boolean;
  coupons: EligibleCoupon[];
  applying: boolean;
  sheetVisible: boolean;
  openSheet: () => void;
  closeSheet: () => void;
  apply: (couponId: string) => Promise<void>;
}

export function useCouponEligibility({
  orderId,
  storeId,
  customerId,
  orderAmountFen,
  tenantId,
  operatorId,
  onApplied,
}: UseCouponEligibilityOptions): UseCouponEligibilityReturn {
  const [coupons, setCoupons] = useState<EligibleCoupon[]>([]);
  const [sheetVisible, setSheetVisible] = useState(false);
  const [applying, setApplying] = useState(false);

  // 结账页面挂载时自动检查（仅在有 customerId 时触发）
  useEffect(() => {
    if (!orderId || !customerId || orderAmountFen <= 0) return;

    let cancelled = false;
    checkCouponEligibility({ order_id: orderId, store_id: storeId, customer_id: customerId, order_amount_fen: orderAmountFen, tenant_id: tenantId })
      .then((result) => {
        if (cancelled) return;
        if (result.eligible_coupons.length > 0) {
          setCoupons(result.eligible_coupons);
          setSheetVisible(true); // 有可用券自动弹出
        }
      })
      .catch(() => {
        // 查询失败静默处理，不阻断结账
      });

    return () => { cancelled = true; };
  }, [orderId, customerId, orderAmountFen, storeId, tenantId]);

  const apply = useCallback(async (couponId: string) => {
    setApplying(true);
    try {
      const result = await applyCouponToOrder({
        coupon_id: couponId,
        order_id: orderId,
        store_id: storeId,
        order_amount_fen: orderAmountFen,
        operator_id: operatorId,
      });
      onApplied(result.discount_amount_fen);
      setSheetVisible(false);
    } finally {
      setApplying(false);
    }
  }, [orderId, storeId, orderAmountFen, operatorId, onApplied]);

  return {
    eligible: coupons.length > 0,
    coupons,
    applying,
    sheetVisible,
    openSheet: () => setSheetVisible(true),
    closeSheet: () => setSheetVisible(false),
    apply,
  };
}
