/**
 * POS 操作 API — 复用 mobile_ops 后端接口
 * 25 个操作面板所需的后端调用
 */
import { txFetch } from './index';

// ─── 基础操作 ───

/** 埋单（预结账）— 打印预结账单，不关台 */
export async function preBill(orderId: string): Promise<{ pre_bill_no: string; amount_fen: number }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/pre-bill`, {
    method: 'POST',
  });
}

/** 起菜 — 通知后厨开始制作 */
export async function fireToKitchen(orderId: string, itemIds?: string[]): Promise<{ fired_count: number }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/fire`, {
    method: 'POST',
    body: JSON.stringify({ item_ids: itemIds }),
  });
}

/** 标记上菜完成 */
export async function markServed(orderId: string, itemId: string): Promise<{ served_at: string }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/served`, {
    method: 'POST',
  });
}

/** 停菜 — 标记某道菜暂停制作 */
export async function pauseItem(orderId: string, itemId: string, reason?: string): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/pause`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

/** 变价 — 修改单品价格 */
export async function overridePrice(
  orderId: string,
  itemId: string,
  newPriceFen: number,
  reason: string,
): Promise<{ new_subtotal_fen: number }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/price`, {
    method: 'PUT',
    body: JSON.stringify({ new_price_fen: newPriceFen, reason }),
  });
}

/** 称重 — 获取称重数据并绑定到菜品 */
export async function bindWeight(
  orderId: string,
  itemId: string,
  weightGram: number,
): Promise<{ new_subtotal_fen: number }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/items/${encodeURIComponent(itemId)}/weight`, {
    method: 'POST',
    body: JSON.stringify({ weight_gram: weightGram }),
  });
}

/** 赠单 — 整单或单品赠送 */
export async function giftOrder(
  orderId: string,
  itemIds?: string[],
  reason?: string,
): Promise<{ gifted_amount_fen: number }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/gift`, {
    method: 'POST',
    body: JSON.stringify({ item_ids: itemIds, reason }),
  });
}

/** 退单 — 退回整单或部分菜品 */
export async function returnOrder(
  orderId: string,
  itemIds?: string[],
  reason?: string,
): Promise<{ returned_amount_fen: number }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/return`, {
    method: 'POST',
    body: JSON.stringify({ item_ids: itemIds, reason }),
  });
}

// ─── 高级操作 ───

/** 催单 — 催促后厨加急 */
export async function rushOrder(orderId: string, itemIds?: string[]): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/rush`, {
    method: 'POST',
    body: JSON.stringify({ item_ids: itemIds }),
  });
}

/** 修改开台信息 — 人数/备注等 */
export async function modifyTableOpen(
  orderId: string,
  guestCount?: number,
  remark?: string,
): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/modify-open`, {
    method: 'PUT',
    body: JSON.stringify({ guest_count: guestCount, remark }),
  });
}

/** 单品转台 — 将部分菜品转到另一桌 */
export async function transferItem(
  orderId: string,
  itemIds: string[],
  targetTableNo: string,
): Promise<{ target_order_id: string }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/transfer-items`, {
    method: 'POST',
    body: JSON.stringify({ item_ids: itemIds, target_table_no: targetTableNo }),
  });
}

/** 换台 — 整单换到另一桌 */
export async function transferTable(
  orderId: string,
  targetTableNo: string,
): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/transfer-table`, {
    method: 'POST',
    body: JSON.stringify({ target_table_no: targetTableNo }),
  });
}

/** 关台 — 清理桌台，标记空闲 */
export async function closeTable(tableNo: string): Promise<void> {
  await txFetch(`/api/v1/trade/tables/${encodeURIComponent(tableNo)}/close`, {
    method: 'POST',
  });
}

/** 核对 — 获取当前桌台的完整订单摘要 */
export async function verifyOrder(orderId: string): Promise<{
  items: Array<{ name: string; qty: number; subtotal_fen: number; status: string }>;
  total_fen: number;
  discount_fen: number;
  final_fen: number;
}> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/verify`);
}

/** 打印小票 */
export async function printReceipt(orderId: string): Promise<{ content_base64: string }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/print/receipt`, {
    method: 'POST',
  });
}

/** 验会员 — 扫码/手机号查询会员信息 */
export async function verifyMember(query: string): Promise<{
  member_id: string;
  name: string;
  phone: string;
  level: string;
  balance_fen: number;
  points: number;
}> {
  return txFetch(`/api/v1/member/verify?q=${encodeURIComponent(query)}`);
}

/** 后厨通知 — 向后厨发送自定义文字消息 */
export async function kitchenMessage(
  storeId: string,
  message: string,
  station?: string,
): Promise<void> {
  await txFetch('/api/v1/trade/kitchen/message', {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, message, station }),
  });
}

/** 转账 — 将订单金额转移到其他支付方式 */
export async function transferPayment(
  orderId: string,
  fromPaymentId: string,
  toMethod: string,
  amountFen: number,
): Promise<{ new_payment_id: string }> {
  return txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/transfer-payment`, {
    method: 'POST',
    body: JSON.stringify({ from_payment_id: fromPaymentId, to_method: toMethod, amount_fen: amountFen }),
  });
}

// ─── 财务操作 ───

/** 并账 — 多桌合并结账 */
export async function mergeOrders(
  orderIds: string[],
  mainOrderId: string,
): Promise<{ merged_order_id: string; total_fen: number }> {
  return txFetch('/api/v1/trade/orders/merge', {
    method: 'POST',
    body: JSON.stringify({ order_ids: orderIds, main_order_id: mainOrderId }),
  });
}

/** 沽清 — 设置菜品当日沽清 */
export async function markSoldOut(
  storeId: string,
  dishId: string,
): Promise<void> {
  await txFetch(`/api/v1/menu/dishes/${encodeURIComponent(dishId)}/sold-out`, {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId }),
  });
}

/** 限量 — 设置菜品当日限量 */
export async function setDishLimit(
  storeId: string,
  dishId: string,
  limit: number,
): Promise<void> {
  await txFetch(`/api/v1/menu/dishes/${encodeURIComponent(dishId)}/limit`, {
    method: 'POST',
    body: JSON.stringify({ store_id: storeId, limit }),
  });
}

/** 改服务员 — 更换订单绑定的服务员 */
export async function changeWaiter(
  orderId: string,
  newWaiterId: string,
): Promise<void> {
  await txFetch(`/api/v1/trade/orders/${encodeURIComponent(orderId)}/waiter`, {
    method: 'PUT',
    body: JSON.stringify({ waiter_id: newWaiterId }),
  });
}

// ─── 桌台状态 ───

export interface TableStatus {
  table_no: string;
  area: string;
  seats: number;
  status: 'free' | 'occupied' | 'overtime' | 'reserved' | 'vip';
  guest_count: number;
  order_id?: string;
  order_amount_fen?: number;
  dining_minutes?: number;
  waiter_name?: string;
}

/** 获取全部桌台状态 */
export async function fetchTableStatus(storeId: string): Promise<{ tables: TableStatus[] }> {
  return txFetch(`/api/v1/trade/tables?store_id=${encodeURIComponent(storeId)}`);
}
