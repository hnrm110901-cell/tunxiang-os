/**
 * 预订 API 客户端 — 统一预订收件箱 + 多渠道聚合
 *
 * 渠道: meituan / dianping / wechat / phone / walkin
 * 状态: pending → confirmed → arrived → seated → completed / cancelled / no_show
 */
import { txFetch } from './index';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

export type ReservationChannel = 'meituan' | 'dianping' | 'wechat' | 'phone' | 'walkin';

export type ReservationStatus =
  | 'pending'
  | 'confirmed'
  | 'arrived'
  | 'seated'
  | 'completed'
  | 'cancelled'
  | 'no_show';

export interface Reservation {
  id: string;                        // 内部主键（UUID hex）
  reservation_id: string;            // 业务ID，如 RSV-XXXXXXXXXXXX
  reservation_no?: string;           // 确认码（6位）
  source_channel: ReservationChannel;
  platform_order_id?: string;        // 平台原始订单号
  customer_name: string;
  customer_phone: string;            // 后端字段 phone
  phone?: string;                    // 兼容后端 phone 字段
  party_size: number;
  date: string;                      // YYYY-MM-DD
  time: string;                      // HH:MM
  arrive_time?: string;              // ISO datetime（备用）
  table_type?: string;               // '大厅'/'包厢'/'靠窗'（room_name）
  room_name?: string;
  special_request?: string;
  special_requests?: string;         // 兼容后端
  status: ReservationStatus;
  member_id?: string;
  assigned_table?: string;           // table_no
  table_no?: string;
  created_at: string;
}

export interface ReservationListResult {
  items: Reservation[];
  total: number;
}

export interface ReservationStats {
  total: number;
  arrived: number;
  pending_arrive: number;           // confirmed 状态
  no_show: number;
  by_channel: Record<ReservationChannel, number>;
}

// ─── 辅助：适配后端字段到前端接口 ────────────────────────────────────────────

function adaptReservation(raw: Record<string, unknown>): Reservation {
  return {
    id: (raw.id ?? raw.reservation_id ?? '') as string,
    reservation_id: (raw.reservation_id ?? '') as string,
    reservation_no: (raw.confirmation_code ?? raw.reservation_no) as string | undefined,
    source_channel: ((raw.source_channel as string) || 'phone') as ReservationChannel,
    platform_order_id: raw.platform_order_id as string | undefined,
    customer_name: (raw.customer_name ?? '') as string,
    customer_phone: (raw.phone ?? raw.customer_phone ?? '') as string,
    phone: raw.phone as string | undefined,
    party_size: (raw.party_size ?? 0) as number,
    date: (raw.date ?? '') as string,
    time: (raw.time ?? '') as string,
    table_type: (raw.room_name ?? raw.table_type) as string | undefined,
    room_name: raw.room_name as string | undefined,
    special_request: (raw.special_requests ?? raw.special_request) as string | undefined,
    special_requests: raw.special_requests as string | undefined,
    status: (raw.status ?? 'pending') as ReservationStatus,
    member_id: (raw.consumer_id ?? raw.member_id) as string | undefined,
    assigned_table: (raw.table_no ?? raw.assigned_table) as string | undefined,
    table_no: raw.table_no as string | undefined,
    created_at: (raw.created_at ?? '') as string,
  };
}

// ─── API 函数 ─────────────────────────────────────────────────────────────────

/** 查询预订列表（支持日期/状态/渠道筛选） */
export async function fetchReservations(
  storeId: string,
  params?: {
    date?: string;
    status?: ReservationStatus | ReservationStatus[];
    channel?: ReservationChannel;
    page?: number;
    size?: number;
  },
): Promise<ReservationListResult> {
  const qs = new URLSearchParams({ store_id: storeId });
  if (params?.date) qs.set('date', params.date);
  if (params?.status) {
    const statuses = Array.isArray(params.status) ? params.status : [params.status];
    statuses.forEach(s => qs.append('status', s));
  }
  if (params?.channel) qs.set('channel', params.channel);
  if (params?.page) qs.set('page', String(params.page));
  if (params?.size) qs.set('size', String(params.size));

  const raw = await txFetch<{ items: Record<string, unknown>[]; total: number }>(
    `/api/v1/reservations?${qs.toString()}`,
  );
  return {
    items: raw.items.map(adaptReservation),
    total: raw.total,
  };
}

/** 创建预订 */
export async function createReservation(data: {
  store_id: string;
  customer_name: string;
  phone: string;
  party_size: number;
  date: string;
  time: string;
  room_name?: string;
  special_requests?: string;
  source_channel?: ReservationChannel;
}): Promise<Reservation> {
  const raw = await txFetch<Record<string, unknown>>('/api/v1/reservations', {
    method: 'POST',
    body: JSON.stringify({
      ...data,
      type: 'regular',
    }),
  });
  return adaptReservation(raw);
}

/** 更新预订状态（通用） */
export async function updateReservationStatus(
  id: string,
  action: 'confirm' | 'arrive' | 'seat' | 'complete' | 'cancel' | 'no_show',
  opts?: { table_no?: string; reason?: string; note?: string },
): Promise<Reservation> {
  const raw = await txFetch<Record<string, unknown>>(
    `/api/v1/reservations/${encodeURIComponent(id)}/status`,
    {
      method: 'PUT',
      body: JSON.stringify({
        action,
        table_no: opts?.table_no,
        reason: opts?.reason || opts?.note,
        confirmed_by: 'crew',
      }),
    },
  );
  return adaptReservation(raw);
}

/** 分配桌台（status → seated 需另调用） */
export async function assignTable(id: string, tableNo: string): Promise<Reservation> {
  return updateReservationStatus(id, 'seat', { table_no: tableNo });
}

/** 确认到店（status → arrived） */
export async function confirmArrival(id: string): Promise<Reservation> {
  return updateReservationStatus(id, 'arrive');
}

/** 标记爽约（status → no_show） */
export async function markNoShow(id: string): Promise<Reservation> {
  return updateReservationStatus(id, 'no_show');
}

/** 取消预订 */
export async function cancelReservation(id: string, reason: string): Promise<Reservation> {
  return updateReservationStatus(id, 'cancel', { reason });
}

/** 完成预订（已入座结束） */
export async function completeReservation(id: string): Promise<Reservation> {
  return updateReservationStatus(id, 'complete');
}

/** 触发 Mock 预订（开发测试用） */
export async function triggerMockReservation(storeId: string): Promise<{
  mock_channel: ReservationChannel;
  mock_order_id: string;
  reservation: Reservation;
}> {
  const raw = await txFetch<{
    mock_channel: string;
    mock_order_id: string;
    reservation: Record<string, unknown>;
  }>(`/api/v1/booking/mock/new-reservation?store_id=${encodeURIComponent(storeId)}`, {
    method: 'POST',
  });
  return {
    mock_channel: raw.mock_channel as ReservationChannel,
    mock_order_id: raw.mock_order_id,
    reservation: adaptReservation(raw.reservation),
  };
}

// ─── 统计辅助（客户端计算，避免额外 API 调用） ────────────────────────────────

export function computeStats(items: Reservation[]): ReservationStats {
  const byChannel: Record<string, number> = {};
  let arrived = 0;
  let pendingArrive = 0;
  let noShow = 0;

  for (const r of items) {
    byChannel[r.source_channel] = (byChannel[r.source_channel] ?? 0) + 1;
    if (r.status === 'arrived') arrived++;
    if (r.status === 'confirmed' || r.status === 'pending') pendingArrive++;
    if (r.status === 'no_show') noShow++;
  }

  return {
    total: items.length,
    arrived,
    pending_arrive: pendingArrive,
    no_show: noShow,
    by_channel: byChannel as Record<ReservationChannel, number>,
  };
}
