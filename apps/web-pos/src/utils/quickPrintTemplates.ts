/**
 * quickPrintTemplates — 快餐打印模板
 *
 * 三种模板，对应快餐场景的三类打印需求：
 *
 *   1. 厨打单（Kitchen Ticket）  — 后厨收到的制作工单，大字，突出牌号
 *   2. 标签打印（Item Label）    — 一品一标签，杯贴/盒贴小格式
 *   3. 结账单（Receipt）         — 顾客收到的消费凭证
 *
 * 输出格式：ESC/POS 纯文本（通过 window.TXBridge.print() 或 HTTP 发送到安卓打印队列）
 *
 * 使用方式：
 *   import { formatKitchenTicket, formatItemLabel, formatReceipt } from '../utils/quickPrintTemplates';
 *   const text = formatKitchenTicket(order);
 *   window.TXBridge?.print(text) || fetch('/api/device/print', { method:'POST', body: text });
 */

import { formatPrice } from '@tx-ds/utils';

// ─── 类型定义 ─────────────────────────────────────────────────────────────────

export interface QuickOrderItem {
  name: string;
  qty: number;
  /** 单价（分） */
  unit_price_fen: number;
  notes?: string;
  /** 可选：厨房站（hot/cold/noodle/bar/staple） */
  kitchen_station?: string;
}

export interface QuickOrder {
  /** 取餐号（如 "001"、"A012"） */
  table_number: string;
  /** 快餐订单 UUID */
  quick_order_id: string;
  /** 门店名称 */
  store_name?: string;
  /** 订单类型：dine_in/takeaway/pack */
  order_type: 'dine_in' | 'takeaway' | 'pack';
  /** 订单总额（分） */
  total_fen: number;
  /** 支付方式 */
  payment_method?: string;
  /** 创建时间 ISO 字符串 */
  created_at: string;
  items: QuickOrderItem[];
  /** 备注 */
  remark?: string;
}

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

/** @deprecated Use formatPrice from @tx-ds/utils */
/** 将分转为元字符串，如 8800 → "88.00" */
function fen2yuan(fen: number): string {
  return (fen / 100).toFixed(2);
}

/** 格式化时间，如 "14:35:22" */
function formatTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return `${h}:${m}:${s}`;
  } catch {
    return isoStr.slice(11, 19) || '--:--:--';
  }
}

/** 格式化日期时间，如 "2026-04-06 14:35" */
function formatDateTime(isoStr: string): string {
  try {
    const d = new Date(isoStr);
    return d.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return isoStr.slice(0, 16).replace('T', ' ');
  }
}

/** ESC/POS 居中（58mm 打印机每行约 32 个汉字宽） */
function center(text: string, width = 32): string {
  const len = [...text].length; // 按字符数（汉字算1位）
  const pad = Math.max(0, Math.floor((width - len) / 2));
  return ' '.repeat(pad) + text;
}

/** 左右对齐，如 "品名       ¥88.00" */
function ljust(left: string, right: string, width = 32): string {
  const gap = Math.max(1, width - [...left].length - [...right].length);
  return left + ' '.repeat(gap) + right;
}

const ORDER_TYPE_LABEL: Record<string, string> = {
  dine_in: '堂食',
  takeaway: '外带',
  pack: '打包',
};

const PAYMENT_METHOD_LABEL: Record<string, string> = {
  wechat: '微信支付',
  alipay: '支付宝',
  cash: '现金',
  unionpay: '银联',
  member_balance: '会员余额',
};

// ─── 1. 厨打单 ────────────────────────────────────────────────────────────────

/**
 * formatKitchenTicket — 厨打单
 *
 * 特点：
 *   - 牌号超大展示（#001），厨师远距离可见
 *   - 品项精简（名称 × 数量），不显示价格
 *   - 备注独立一行高亮
 *   - 不含支付信息（后厨不需要）
 */
export function formatKitchenTicket(order: QuickOrder): string {
  const typeLabel = ORDER_TYPE_LABEL[order.order_type] ?? order.order_type;
  const storeLine = order.store_name ? `门店: ${order.store_name}` : '';

  const itemLines = order.items
    .map(item => {
      const noteLine = item.notes ? `    备注: ${item.notes}` : '';
      return `  ${item.name.padEnd(12)} × ${item.qty}${noteLine ? '\n' + noteLine : ''}`;
    })
    .join('\n');

  const remarkLine = order.remark ? `\n备注: ${order.remark}` : '';

  return [
    '================================',
    center('★ 厨  打  单 ★'),
    '================================',
    '',
    center(`#${order.table_number}`),  // 牌号核心，放最显眼位置
    '',
    `类型: ${typeLabel}`,
    `时间: ${formatTime(order.created_at)}`,
    storeLine ? storeLine : null,
    '--------------------------------',
    itemLines,
    '--------------------------------',
    remarkLine || null,
    '',
    `订单: ${order.quick_order_id.slice(-8).toUpperCase()}`,
    '================================',
    '',
  ]
    .filter((line): line is string => line !== null)
    .join('\n');
}

// ─── 2. 标签打印 ──────────────────────────────────────────────────────────────

/**
 * formatItemLabel — 单品标签
 *
 * 适用：奶茶/咖啡/盒饭等需要贴签的单品
 * 格式：小格式（58mm × 约 30mm），每品单独打印一张
 */
export function formatItemLabel(item: QuickOrderItem, tableNumber: string): string {
  const notePart = item.notes ? `\n备注: ${item.notes}` : '';

  return [
    '========================',
    `[${tableNumber}]  ${item.name}`,
    `数量: ×${item.qty}`,
    notePart || null,
    '========================',
  ]
    .filter((line): line is string => line !== null)
    .join('\n');
}

/**
 * formatAllItemLabels — 批量生成所有品项标签（一品一张）
 *
 * 返回数组，每个元素对应一张标签的打印文本
 */
export function formatAllItemLabels(order: QuickOrder): string[] {
  return order.items.flatMap(item =>
    Array.from({ length: item.qty }, () =>
      formatItemLabel({ ...item, qty: 1 }, order.table_number),
    ),
  );
}

// ─── 3. 结账单 ────────────────────────────────────────────────────────────────

/**
 * formatReceipt — 结账单/消费凭证
 *
 * 特点：
 *   - 包含门店名、牌号、品项+单价+小计
 *   - 合计金额大字
 *   - 支付方式清晰展示
 *   - 不含厨房操作信息
 */
export function formatReceipt(order: QuickOrder): string {
  const typeLabel = ORDER_TYPE_LABEL[order.order_type] ?? order.order_type;
  const payLabel =
    PAYMENT_METHOD_LABEL[order.payment_method ?? ''] ??
    order.payment_method ??
    '未知';

  const storeLine = order.store_name
    ? center(order.store_name)
    : center('屯象OS · 快餐收银');

  const itemLines = order.items
    .map(item => {
      const subtotalFen = item.unit_price_fen * item.qty;
      const priceStr =
        item.qty > 1
          ? `¥${fen2yuan(item.unit_price_fen)}×${item.qty}=¥${fen2yuan(subtotalFen)}`
          : `¥${fen2yuan(subtotalFen)}`;
      return ljust(item.name, priceStr);
    })
    .join('\n');

  const remarkLine = order.remark ? `\n备注: ${order.remark}` : '';

  return [
    '================================',
    storeLine,
    center('结  账  单'),
    '================================',
    `牌号: ${order.table_number}        ${typeLabel}`,
    `时间: ${formatDateTime(order.created_at)}`,
    `单号: ${order.quick_order_id.slice(-12).toUpperCase()}`,
    '--------------------------------',
    itemLines,
    '--------------------------------',
    ljust('合  计', `¥${fen2yuan(order.total_fen)}`),
    '--------------------------------',
    `支付: ${payLabel}`,
    remarkLine || null,
    '',
    center('感谢惠顾，欢迎再次光临！'),
    '================================',
    '',
  ]
    .filter((line): line is string => line !== null)
    .join('\n');
}

// ─── 4. 打印调度器（统一入口） ────────────────────────────────────────────────

export type PrintType = 'kitchen' | 'label' | 'receipt' | 'all_labels';

interface PrintOptions {
  /** 打印类型 */
  type: PrintType;
  order: QuickOrder;
  /** 单品标签模式时指定某个品项（不传则打印全部） */
  item?: QuickOrderItem;
}

/**
 * getPrintContent — 根据类型生成打印内容
 *
 * 返回 string（kitchen/label/receipt）或 string[]（all_labels）
 */
export function getPrintContent(opts: PrintOptions): string | string[] {
  switch (opts.type) {
    case 'kitchen':
      return formatKitchenTicket(opts.order);
    case 'label':
      if (opts.item) return formatItemLabel(opts.item, opts.order.table_number);
      return formatAllItemLabels(opts.order).join('\n\n');
    case 'all_labels':
      return formatAllItemLabels(opts.order);
    case 'receipt':
      return formatReceipt(opts.order);
    default:
      return formatReceipt(opts.order);
  }
}
