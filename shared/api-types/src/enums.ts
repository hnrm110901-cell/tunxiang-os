/**
 * 枚举类型 — 与 shared/ontology/src/enums.py 一一对应
 */

export type OrderStatus =
  | 'pending'
  | 'confirmed'
  | 'preparing'
  | 'ready'
  | 'served'
  | 'completed'
  | 'cancelled';

export type StoreStatus =
  | 'active'
  | 'inactive'
  | 'renovating'
  | 'preparing'
  | 'closed';

export type InventoryStatus =
  | 'normal'
  | 'low'
  | 'critical'
  | 'out_of_stock';

export type TransactionType =
  | 'purchase'
  | 'usage'
  | 'waste'
  | 'adjustment'
  | 'transfer'
  | 'receiving'
  | 'transfer_out'
  | 'transfer_in';

export type ReceivingOrderStatus =
  | 'draft'
  | 'inspecting'
  | 'partially_received'
  | 'fully_received'
  | 'rejected';

export type ReceivingItemStatus =
  | 'pending'
  | 'accepted'
  | 'partial'
  | 'rejected';

export type TransferOrderStatus =
  | 'draft'
  | 'approved'
  | 'shipped'
  | 'received'
  | 'cancelled';

export type EmploymentStatus =
  | 'trial'
  | 'probation'
  | 'regular'
  | 'resigned';

export type EmploymentType =
  | 'regular'
  | 'part_time'
  | 'intern'
  | 'trainee'
  | 'temp';

export type StorageType =
  | 'frozen'
  | 'chilled'
  | 'ambient'
  | 'live';

export type RFMLevel =
  | 'S1'
  | 'S2'
  | 'S3'
  | 'S4'
  | 'S5';

/** 订单类型（对应 Order.order_type） */
export type OrderType =
  | 'dine_in'
  | 'takeaway'
  | 'delivery'
  | 'retail'
  | 'catering'
  | 'banquet';

/** 门店类型（对应 Store.store_type） */
export type StoreType =
  | 'physical'
  | 'virtual'
  | 'central_kitchen'
  | 'warehouse';

/** 员工角色 */
export type EmployeeRole =
  | 'waiter'
  | 'chef'
  | 'cashier'
  | 'manager';

/** 定价模式（对应 OrderItem.pricing_mode） */
export type PricingMode =
  | 'fixed'
  | 'weight'
  | 'market_price';
