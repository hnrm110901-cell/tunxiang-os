/**
 * printUtils — 打印调用工具
 *
 * 封装活鲜称重单 / 宴席通知单的打印调用。
 * 自动判断运行环境：
 *   安卓POS (TXBridge 存在)  → window.TXBridge.print(content)
 *   iPad / 浏览器开发环境    → console.log 打印内容预览
 */

import { txFetch } from '../api/index';

// ─── 活鲜称重单 ───────────────────────────────────────────────────────────────

/** 活鲜称重单 — 单项数据结构 */
export interface LiveSeafoodReceiptItem {
  dish_name: string;
  tank_zone: string;
  weight_kg: number;
  weight_jin: number;
  price_per_jin_fen: number;
  total_fen: number;
  note?: string;
}

/** 活鲜称重单 — 完整数据结构 */
export interface LiveSeafoodReceiptData {
  store_name: string;
  table_no: string;
  printed_at: string;
  operator: string;
  items: LiveSeafoodReceiptItem[];
  total_fen: number;
}

/** 后端打印接口响应 */
interface PrintResponse {
  content: string;
  printer_hint: string;
  description?: string;
  mock?: boolean;
}

/**
 * 打印活鲜称重单
 *
 * 调用后端生成语义标记文本，再通过 TXBridge 发给安卓打印机。
 * 非安卓环境（iPad / 浏览器）打印内容输出到 console，方便调试。
 */
export async function printLiveSeafoodReceipt(
  data: LiveSeafoodReceiptData,
): Promise<void> {
  const result = await txFetch<PrintResponse>('/api/v1/print/live-seafood-receipt', {
    method: 'POST',
    body: JSON.stringify(data),
  });

  if (window.TXBridge) {
    window.TXBridge.print(result.content);
  } else {
    // 浏览器 / iPad 开发模式：输出到控制台
    console.log('[打印预览 - 活鲜称重单]', result.description);
    console.log(result.content);
  }
}

// ─── 宴席通知单 ───────────────────────────────────────────────────────────────

/** 宴席通知单 — 菜品条目 */
export interface BanquetSectionItem {
  name: string;
  qty_per_table: number;
  note?: string;
}

/** 宴席通知单 — 出品节次 */
export interface BanquetSection {
  section_name: string;
  serve_time?: string;
  items: BanquetSectionItem[];
}

/** 宴席通知单 — 完整数据结构 */
export interface BanquetNoticeData {
  store_name: string;
  banquet_name: string;
  session_no: number;
  table_count: number;
  party_size: number;
  arrive_time: string;
  start_time: string;
  printed_at: string;
  contact_name: string;
  contact_phone: string;
  package_name: string;
  sections: BanquetSection[];
  special_notes?: string;
  dept?: string;
}

/**
 * 打印宴席出品通知单
 *
 * 调用后端生成语义标记文本，再通过 TXBridge 发给安卓打印机。
 * 非安卓环境（iPad / 浏览器）打印内容输出到 console，方便调试。
 */
export async function printBanquetNotice(data: BanquetNoticeData): Promise<void> {
  const result = await txFetch<PrintResponse>('/api/v1/print/banquet-notice-v2', {
    method: 'POST',
    body: JSON.stringify(data),
  });

  if (window.TXBridge) {
    window.TXBridge.print(result.content);
  } else {
    // 浏览器 / iPad 开发模式：输出到控制台
    console.log('[打印预览 - 宴席通知单]', result.description);
    console.log(result.content);
  }
}
