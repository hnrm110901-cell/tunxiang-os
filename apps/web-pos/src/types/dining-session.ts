/**
 * 堂食会话类型定义 (v149 桌台中心化架构)
 * dining_sessions 表的前端映射
 */

/** 堂食会话9态状态机 */
export type DiningSessionStatus =
  | 'reserved'      // 预留（管理员提前锁桌）
  | 'seated'        // 已就坐（开台完成，等待点菜）
  | 'ordering'      // 点菜中
  | 'dining'        // 用餐中
  | 'add_ordering'  // 加菜中
  | 'billing'       // 结账中（已请求买单）
  | 'paid'          // 已结账
  | 'clearing'      // 清台中
  | 'disabled';     // 暂停服务

/** 会话类型 */
export type DiningSessionType =
  | 'dine_in'    // 普通堂食
  | 'banquet'    // 宴席
  | 'vip_room'   // VIP包间
  | 'self_order' // 扫码自助
  | 'hotpot';    // 拼台（热锅/BBQ）

/** 服务呼叫类型 */
export type ServiceCallType =
  | 'call_waiter'
  | 'urge_dish'
  | 'need_item'
  | 'complaint'
  | 'checkout_request'
  | 'other';

/** 桌台区域信息 */
export interface TableZone {
  id: string;
  zoneName: string;
  zoneType: 'hall' | 'private_room' | 'bar' | 'outdoor' | 'takeaway';
}

/** 堂食会话（完整） */
export interface DiningSession {
  id: string;
  sessionNo: string;
  status: DiningSessionStatus;
  sessionType: DiningSessionType;

  // 桌台信息
  tableId: string;
  tableNo: string;
  area: string | null;
  floor: number;
  seats: number;

  // 就餐人信息
  guestCount: number;
  vipCustomerId: string | null;
  bookingId: string | null;

  // 服务归属
  leadWaiterId: string;
  leadWaiterName: string | null;
  zoneName: string | null;
  zoneType: string | null;

  // 时间轴
  openedAt: string;                  // ISO 8601
  firstOrderAt: string | null;
  firstDishServedAt: string | null;
  lastDishServedAt: string | null;
  billRequestedAt: string | null;
  paidAt: string | null;
  clearedAt: string | null;

  // 实时汇总
  totalOrders: number;
  totalItems: number;
  totalAmountFen: number;
  discountAmountFen: number;
  finalAmountFen: number;
  perCapitaFen: number;
  serviceCallCount: number;

  // 计算字段（后端返回）
  diningMinutes?: number;
  pendingCalls?: number;

  // 包间配置
  roomConfig?: Record<string, unknown>;
}

/** 桌台大板看板卡片（get_store_board 返回，含轻量计算字段） */
export interface SessionBoardCard {
  id: string;
  sessionNo: string;
  status: DiningSessionStatus;
  sessionType: DiningSessionType;
  tableId: string;
  tableNo: string;
  area: string | null;
  floor: number;
  seats: number;
  guestCount: number;
  openedAt: string;
  firstOrderAt: string | null;
  billRequestedAt: string | null;
  totalAmountFen: number;
  finalAmountFen: number;
  perCapitaFen: number;
  serviceCallCount: number;
  totalOrders: number;
  vipCustomerId: string | null;
  leadWaiterName: string | null;
  zoneName: string | null;
  zoneType: string | null;
  diningMinutes: number;
  pendingCalls: number;
}

/** 桌台大板汇总 */
export interface BoardSummary {
  totalSessions: number;
  seatedTables: number;         // 就坐/点菜/用餐中
  billingTables: number;        // 待结账
  availableTables: number;      // 空台（从 tables 表补充）
  totalGuests: number;
  avgDiningMinutes: number;
  totalRevenueFen: number;      // 今日已结账总收入
}

/** 开台请求 */
export interface OpenTableRequest {
  storeId: string;
  tableId: string;
  guestCount: number;
  leadWaiterId: string;
  zoneId?: string;
  bookingId?: string;
  vipCustomerId?: string;
  sessionType?: DiningSessionType;
}

/** 转台请求 */
export interface TransferTableRequest {
  targetTableId: string;
  reason: string;
  operatorId: string;
}

/** 并台请求 */
export interface MergeSessionsRequest {
  secondarySessionIds: string[];
  operatorId: string;
}

/** 服务呼叫请求 */
export interface CreateServiceCallRequest {
  storeId: string;
  tableSessionId: string;
  callType: ServiceCallType;
  content?: string;
  targetDishId?: string;
  calledBy?: 'pos' | 'self_order' | 'crew_app' | 'kds';
  callerName?: string;
}

/** 服务呼叫记录 */
export interface ServiceCall {
  id: string;
  tableSessionId: string;
  callType: ServiceCallType;
  content: string | null;
  status: 'pending' | 'handling' | 'handled' | 'cancelled';
  calledBy: string;
  callerName: string | null;
  handledBy: string | null;
  calledAt: string;
  handledAt: string | null;
  responseSeconds: number | null;
  // 关联信息（看板用）
  sessionNo?: string;
  tableNo?: string;
  guestCount?: number;
}
