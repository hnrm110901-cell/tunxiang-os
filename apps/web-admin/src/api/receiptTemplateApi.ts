/**
 * 小票模板 API — /api/v1/receipt-templates/*
 * 小票模板的增删改查、预览、复制、设为默认
 */
import { txFetch } from './index';

// ─── 类型定义 ───

export type ElementType =
  | 'store_name'
  | 'store_address'
  | 'separator'
  | 'order_info'
  | 'order_items'
  | 'total_summary'
  | 'payment_method'
  | 'qrcode'
  | 'barcode'
  | 'custom_text'
  | 'blank_lines'
  | 'logo_text';

export interface TemplateElement {
  id: string;
  type: ElementType;
  align?: 'left' | 'center' | 'right';
  bold?: boolean;
  size?: 'normal' | 'double_width' | 'double_height' | 'double_both';
  char?: string;           // separator
  fields?: string[];       // order_info
  show_price?: boolean;    // order_items
  show_qty?: boolean;
  show_subtotal?: boolean;
  show_discount?: boolean; // total_summary
  show_service_fee?: boolean;
  content?: string;        // custom_text, logo_text
  content_field?: string;  // qrcode
  count?: number;          // blank_lines
}

export interface TemplateConfig {
  paper_width: 58 | 80;
  elements: TemplateElement[];
}

export interface ReceiptTemplate {
  id: string;
  store_id: string;
  name: string;
  print_type: string;
  is_default: boolean;
  config: TemplateConfig;
  created_at: string;
  updated_at: string;
}

export interface CreateTemplateReq {
  store_id: string;
  name: string;
  print_type?: string;
  config: TemplateConfig;
}

export interface UpdateTemplateReq {
  name?: string;
  config?: TemplateConfig;
}

export interface ElementCatalogItem {
  type: ElementType;
  label: string;
  icon: string;
  category: string;
  default_config: Partial<TemplateElement>;
}

// ─── API ───

export const receiptTemplateApi = {
  /** 获取门店模板列表 */
  list: (storeId: string, printType?: string): Promise<{ items: ReceiptTemplate[]; total: number }> => {
    const params = new URLSearchParams({ store_id: storeId });
    if (printType) params.set('print_type', printType);
    return txFetch(`/api/v1/receipt-templates?${params.toString()}`);
  },

  /** 获取单个模板 */
  get: (id: string): Promise<ReceiptTemplate> =>
    txFetch(`/api/v1/receipt-templates/${encodeURIComponent(id)}`),

  /** 创建模板 */
  create: (data: CreateTemplateReq): Promise<ReceiptTemplate> =>
    txFetch('/api/v1/receipt-templates', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  /** 更新模板 */
  update: (id: string, data: UpdateTemplateReq): Promise<ReceiptTemplate> =>
    txFetch(`/api/v1/receipt-templates/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  /** 删除模板 */
  delete: (id: string): Promise<void> =>
    txFetch(`/api/v1/receipt-templates/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  /** 设为默认 */
  setDefault: (id: string): Promise<void> =>
    txFetch(`/api/v1/receipt-templates/${encodeURIComponent(id)}/set-default`, {
      method: 'POST',
    }),

  /** 预览（传入config返回渲染结果） */
  preview: (config: TemplateConfig): Promise<{ html: string }> =>
    txFetch('/api/v1/receipt-templates/preview', {
      method: 'POST',
      body: JSON.stringify({ config, context: 'sample' }),
    }),

  /** 复制模板 */
  duplicate: (id: string): Promise<ReceiptTemplate> =>
    txFetch(`/api/v1/receipt-templates/${encodeURIComponent(id)}/duplicate`, {
      method: 'POST',
    }),

  /** 获取元素目录 */
  getElementCatalog: (): Promise<{ items: ElementCatalogItem[] }> =>
    txFetch('/api/v1/receipt-templates/elements/catalog'),
};
