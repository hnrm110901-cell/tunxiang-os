import { txFetch } from './index';

/* ---- 类型定义 ---- */

export type PayMethod = 'wechat' | 'alipay' | 'unionpay';

export interface Coupon {
  id: string;
  name: string;
  description: string;
  discountAmount: number;
  minSpend: number;
  expiresAt: string;
}

export interface PaymentRequest {
  orderId: string;
  method: PayMethod;
  couponId?: string;
  phone: string;
}

export interface PaymentResult {
  paymentId: string;
  status: 'pending' | 'success' | 'failed';
  /** 支付宝/银联H5跳转链接；微信走JSAPI */
  redirectUrl?: string;
  /** 微信JSAPI支付参数 */
  wechatPayParams?: {
    appId: string;
    timeStamp: string;
    nonceStr: string;
    package: string;
    signType: string;
    paySign: string;
  };
}

/* ---- API 函数 ---- */

export function fetchCoupons(phone: string) {
  return txFetch<Coupon[]>(`/coupons?phone=${encodeURIComponent(phone)}`);
}

export function initiatePayment(payload: PaymentRequest) {
  return txFetch<PaymentResult>('/payments', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function queryPaymentStatus(paymentId: string) {
  return txFetch<{ status: 'pending' | 'success' | 'failed' }>(`/payments/${paymentId}/status`);
}
