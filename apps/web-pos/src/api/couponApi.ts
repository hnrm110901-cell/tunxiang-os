/**
 * 券权益 API — /api/v1/trade/coupon/*
 * 核销优惠券、查询可用券、校验券码
 */
import { txFetch } from './index';

// ─── 类型 ───

export interface Coupon {
  coupon_id: string;
  coupon_code: string;
  name: string;
  type: 'discount' | 'cash' | 'gift' | 'free_dish';
  value_fen: number;
  min_order_fen: number;
  valid_from: string;
  valid_to: string;
  status: 'available' | 'used' | 'expired';
  applicable_dishes: string[];  // 空数组=全场通用
}

export interface CouponVerifyResult {
  valid: boolean;
  coupon: Coupon | null;
  reason: string;
  discount_fen: number;
}

// ─── 接口 ───

/** 查询订单可用优惠券列表 */
export async function fetchAvailableCoupons(
  orderId: string,
  memberId?: string,
): Promise<{ items: Coupon[] }> {
  const memberParam = memberId ? `&member_id=${encodeURIComponent(memberId)}` : '';
  return txFetch(
    `/api/v1/trade/coupon/available?order_id=${encodeURIComponent(orderId)}${memberParam}`,
  );
}

/** 校验券码有效性 */
export async function verifyCoupon(
  couponCode: string,
  orderId: string,
): Promise<CouponVerifyResult> {
  return txFetch('/api/v1/trade/coupon/verify', {
    method: 'POST',
    body: JSON.stringify({ coupon_code: couponCode, order_id: orderId }),
  });
}

/** 核销优惠券（应用到订单） */
export async function redeemCoupon(
  orderId: string,
  couponId: string,
): Promise<{ order_id: string; coupon_id: string; discount_fen: number }> {
  return txFetch('/api/v1/trade/coupon/redeem', {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId, coupon_id: couponId }),
  });
}

/** 取消已核销的优惠券 */
export async function cancelCouponRedemption(
  orderId: string,
  couponId: string,
): Promise<{ order_id: string; coupon_id: string }> {
  return txFetch('/api/v1/trade/coupon/cancel', {
    method: 'POST',
    body: JSON.stringify({ order_id: orderId, coupon_id: couponId }),
  });
}
