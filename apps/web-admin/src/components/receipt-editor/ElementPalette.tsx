/**
 * ElementPalette — 左侧元素面板（240px）
 * 按分类分组展示可拖拽的元素卡片，支持搜索过滤
 */
import { useState } from 'react';
import type { ElementType, TemplateElement } from '../../api/receiptTemplateApi';

// ─── 元素目录配置 ───

interface ElementMeta {
  label: string;
  icon: string;
  category: string;
  defaultConfig: Partial<TemplateElement>;
}

const ELEMENT_CATALOG: Record<ElementType, ElementMeta> = {
  store_name: {
    label: '店名',
    icon: '🏪',
    category: '基础信息',
    defaultConfig: { align: 'center', bold: true, size: 'double_both' },
  },
  store_address: {
    label: '地址',
    icon: '📍',
    category: '基础信息',
    defaultConfig: { align: 'center', size: 'normal' },
  },
  order_info: {
    label: '订单信息',
    icon: '📋',
    category: '订单内容',
    defaultConfig: { fields: ['table_no', 'order_no', 'cashier', 'datetime'] },
  },
  order_items: {
    label: '菜品明细',
    icon: '🍜',
    category: '订单内容',
    defaultConfig: { show_price: true, show_qty: true, show_subtotal: true },
  },
  total_summary: {
    label: '合计区',
    icon: '💰',
    category: '合计支付',
    defaultConfig: { show_discount: true, show_service_fee: false },
  },
  payment_method: {
    label: '支付方式',
    icon: '💳',
    category: '合计支付',
    defaultConfig: { align: 'left' },
  },
  separator: {
    label: '分隔线',
    icon: '➖',
    category: '装饰元素',
    defaultConfig: { char: '-', align: 'center' },
  },
  qrcode: {
    label: '二维码',
    icon: '⬛',
    category: '装饰元素',
    defaultConfig: { content_field: 'order_id', align: 'center' },
  },
  barcode: {
    label: '条形码',
    icon: '▌▌▌',
    category: '装饰元素',
    defaultConfig: { content_field: 'order_no', align: 'center' },
  },
  custom_text: {
    label: '自定义文字',
    icon: '✏️',
    category: '装饰元素',
    defaultConfig: { content: '感谢光临！', align: 'center' },
  },
  blank_lines: {
    label: '空行',
    icon: '↕️',
    category: '装饰元素',
    defaultConfig: { count: 1 },
  },
  logo_text: {
    label: '品牌口号',
    icon: '⭐',
    category: '装饰元素',
    defaultConfig: { content: '美食之旅，从这里开始', align: 'center', bold: true },
  },
  inverted_header: {
    label: '反色横幅',
    icon: '▓',
    category: '设计增强',
    defaultConfig: { content: '{{store_name}}', align: 'center', size: 'double_height' },
  },
  styled_separator: {
    label: '创意分隔线',
    icon: '〰',
    category: '设计增强',
    defaultConfig: { style: 'dash' },
  },
  box_section: {
    label: '边框区块',
    icon: '▢',
    category: '设计增强',
    defaultConfig: { style: 'single', lines: ['感谢光临'], align: 'center' },
  },
  logo_image: {
    label: 'Logo图片',
    icon: '🖼',
    category: '设计增强',
    defaultConfig: { align: 'center', max_width_dots: 384 },
  },
  underlined_text: {
    label: '下划线文字',
    icon: 'U̲',
    category: '设计增强',
    defaultConfig: { content: '下划线文字', align: 'left', bold: false },
  },
};

const CATEGORIES = ['基础信息', '订单内容', '合计支付', '装饰元素', '设计增强'];

interface ElementPaletteProps {
  onAdd: (type: ElementType, defaults: Partial<TemplateElement>) => void;
}

export function ElementPalette({ onAdd }: ElementPaletteProps) {
  const [search, setSearch] = useState('');

  const filtered = (Object.entries(ELEMENT_CATALOG) as [ElementType, ElementMeta][]).filter(
    ([, meta]) =>
      !search ||
      meta.label.includes(search) ||
      meta.category.includes(search),
  );

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--bg-1, #112228)',
      borderRight: '1px solid var(--bg-2, #1a2a33)',
    }}>
      {/* 面板标题 */}
      <div style={{
        padding: '12px 14px 8px',
        borderBottom: '1px solid var(--bg-2, #1a2a33)',
      }}>
        <div style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: 'var(--text-3, #999)',
          marginBottom: 8,
        }}>
          元素面板
        </div>
        <input
          placeholder="搜索元素..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            width: '100%',
            padding: '6px 10px',
            borderRadius: 6,
            border: '1px solid var(--bg-2, #1a2a33)',
            background: 'var(--bg-0, #0B1A20)',
            color: 'var(--text-2, #ccc)',
            fontSize: 12,
            outline: 'none',
            boxSizing: 'border-box',
          }}
        />
      </div>

      {/* 元素列表（按分类） */}
      <div style={{ flex: 1, overflow: 'auto', padding: '8px 8px' }}>
        {CATEGORIES.map((category) => {
          const items = filtered.filter(([, meta]) => meta.category === category);
          if (items.length === 0) return null;
          return (
            <div key={category} style={{ marginBottom: 12 }}>
              <div style={{
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                color: 'var(--text-4, #666)',
                padding: '6px 4px 4px',
              }}>
                {category}
              </div>
              {items.map(([type, meta]) => (
                <ElementCard
                  key={type}
                  type={type}
                  meta={meta}
                  onAdd={() => onAdd(type, meta.defaultConfig)}
                />
              ))}
            </div>
          );
        })}
      </div>

      {/* 底部提示 */}
      <div style={{
        padding: '10px 14px',
        borderTop: '1px solid var(--bg-2, #1a2a33)',
        fontSize: 11,
        color: 'var(--text-4, #666)',
        textAlign: 'center',
      }}>
        点击元素即可添加到画布
      </div>
    </div>
  );
}

// ─── 单个元素卡片 ───

interface ElementCardProps {
  type: ElementType;
  meta: ElementMeta;
  onAdd: () => void;
}

function ElementCard({ meta, onAdd }: ElementCardProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      onClick={onAdd}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title={`点击添加「${meta.label}」`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 10px',
        borderRadius: 8,
        cursor: 'pointer',
        fontSize: 13,
        background: hovered ? 'var(--bg-2, #1a2a33)' : 'transparent',
        transition: 'background 0.15s',
        userSelect: 'none',
      }}
    >
      <span style={{ fontSize: 15, width: 20, textAlign: 'center', flexShrink: 0 }}>
        {meta.icon}
      </span>
      <span style={{ color: 'var(--text-2, #ccc)', flex: 1 }}>{meta.label}</span>
      <span style={{
        fontSize: 10,
        color: hovered ? 'var(--brand, #FF6B35)' : 'transparent',
        transition: 'color 0.15s',
      }}>
        +
      </span>
    </div>
  );
}
