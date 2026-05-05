/**
 * 全渠道订单 API — /api/v1/orders/*
 * 订单列表 / 详情 / 统计
 */
import { txFetchData } from './index';

// ─── 类型 ───

export interface OrderSummary {
  id: string;
  platform: string;
  status: string;
  total_fen: number;
  platform_order_id: string;
  customer_phone: string;
  created_at: string;
}

export interface OrderDetail {
  id: string;
  platform: string;
  platform_order_id: string;
  status: string;
  total_fen: number;
  customer_phone: string;
  delivery_address: string;
  notes: string;
  items: Array<{
    name: string;
    quantity: number;
    price_fen: number;
  }>;
  created_at: string;
  updated_at: string;
}

export interface OrderStats {
  total_orders: number;
  total_fen: number;
  pending: number;
  active: number;
  completed: number;
  cancelled: number;
}

// ─── 接口 ───

/** 获取订单列表（支持筛选/分页） */
export async function fetchOrders(params: {
  platform?: string;
  status?: string;
  store_id?: string;
  keyword?: string;
  page?: number;
  size?: number;
}): Promise<{ items: OrderSummary[]; total: number; page: number; size: number }> {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== '') qs.set(k, String(v));
  });
  return txFetchData(`/api/v1/orders?${qs.toString()}`);
}

/** 获取订单详情 */
export async function fetchOrderDetail(orderId: string): Promise<OrderDetail> {
  return txFetchData(`/api/v1/orders/${orderId}`);
}

/** 获取订单统计（各状态聚合） */
export async function fetchOrderStats(params?: {
  store_id?: string;
  platform?: string;
}): Promise<OrderStats> {
  const qs = new URLSearchParams();
  if (params?.store_id) qs.set('store_id', params.store_id);
  if (params?.platform) qs.set('platform', params.platform);
  const query = qs.toString();
  return txFetchData(`/api/v1/orders/stats${query ? `?${query}` : ''}`);
}
