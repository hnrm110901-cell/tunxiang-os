/**
 * 打印模板可视化编辑 + 小票预览
 *
 * 功能：
 *  - 模板类型选择（小票/厨房单/标签）
 *  - 左侧模板列表 + 中间拖拽编辑 + 右侧实时预览
 *  - 58mm / 80mm 热敏小票模拟
 *  - TXBridge.print 测试打印
 */
import { useState, useCallback, useMemo } from 'react';
import { printReceipt } from '../bridge/TXBridge';

/* ═══════════════════════════════════════════
   类型定义
   ═══════════════════════════════════════════ */

type TemplateType = 'receipt' | 'kitchen' | 'label';
type PaperWidth = '58mm' | '80mm';

interface TemplateElement {
  id: string;
  kind: ElementKind;
  label: string;
  /** 自定义文字内容 */
  text?: string;
  /** 分隔线样式 */
  lineStyle?: 'dashed' | 'solid' | 'blank';
  /** 字体大小 */
  fontSize?: number;
  /** 对齐方式 */
  align?: 'left' | 'center' | 'right';
  /** 是否加粗 */
  bold?: boolean;
}

type ElementKind =
  | 'store_name'
  | 'separator'
  | 'order_info'
  | 'dish_list'
  | 'amount_summary'
  | 'payment_info'
  | 'qrcode'
  | 'custom_text'
  | 'footer';

interface PrintTemplate {
  id: string;
  name: string;
  type: TemplateType;
  paperWidth: PaperWidth;
  elements: TemplateElement[];
  isDefault: boolean;
}

/* ═══════════════════════════════════════════
   默认 / 预设模板
   ═══════════════════════════════════════════ */

const ELEMENT_PALETTE: { kind: ElementKind; label: string }[] = [
  { kind: 'store_name', label: '门店名（大字居中）' },
  { kind: 'separator', label: '分隔线' },
  { kind: 'order_info', label: '订单信息' },
  { kind: 'dish_list', label: '菜品列表' },
  { kind: 'amount_summary', label: '金额汇总' },
  { kind: 'payment_info', label: '支付信息' },
  { kind: 'qrcode', label: '二维码 / 条形码' },
  { kind: 'custom_text', label: '自定义文字' },
  { kind: 'footer', label: '页脚' },
];

let _nextId = 1;
const uid = (): string => `el_${Date.now()}_${_nextId++}`;

const makeElement = (kind: ElementKind, overrides?: Partial<TemplateElement>): TemplateElement => {
  const base = ELEMENT_PALETTE.find(p => p.kind === kind);
  return { id: uid(), kind, label: base?.label ?? kind, ...overrides };
};

const STANDARD_ELEMENTS: TemplateElement[] = [
  makeElement('store_name', { fontSize: 20, align: 'center', bold: true }),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('order_info'),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('dish_list'),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('amount_summary'),
  makeElement('separator', { lineStyle: 'solid' }),
  makeElement('payment_info'),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('qrcode'),
  makeElement('footer', { text: '谢谢惠顾，欢迎再来！' }),
];

const SIMPLE_ELEMENTS: TemplateElement[] = [
  makeElement('store_name', { fontSize: 18, align: 'center', bold: true }),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('order_info'),
  makeElement('dish_list'),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('amount_summary'),
  makeElement('footer', { text: '谢谢惠顾！' }),
];

const DETAIL_ELEMENTS: TemplateElement[] = [
  makeElement('store_name', { fontSize: 22, align: 'center', bold: true }),
  makeElement('custom_text', { text: '地址：XX路XX号  电话：138xxxx', align: 'center', fontSize: 12 }),
  makeElement('separator', { lineStyle: 'solid' }),
  makeElement('order_info'),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('dish_list'),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('amount_summary'),
  makeElement('separator', { lineStyle: 'solid' }),
  makeElement('payment_info'),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('qrcode'),
  makeElement('custom_text', { text: 'WiFi: TunXiang_Guest 密码: 88888888', align: 'center', fontSize: 11 }),
  makeElement('footer', { text: '谢谢惠顾，祝您用餐愉快！' }),
];

const KITCHEN_ELEMENTS: TemplateElement[] = [
  makeElement('store_name', { fontSize: 20, align: 'center', bold: true, text: '厨房出品单' }),
  makeElement('separator', { lineStyle: 'solid' }),
  makeElement('order_info'),
  makeElement('separator', { lineStyle: 'dashed' }),
  makeElement('dish_list'),
  makeElement('separator', { lineStyle: 'solid' }),
  makeElement('custom_text', { text: '备注：', fontSize: 14, bold: true }),
];

const LABEL_ELEMENTS: TemplateElement[] = [
  makeElement('store_name', { fontSize: 14, align: 'center', bold: true }),
  makeElement('custom_text', { text: '品名：宫保鸡丁', fontSize: 12 }),
  makeElement('custom_text', { text: '制作：2026-04-02 12:30', fontSize: 10 }),
  makeElement('custom_text', { text: '保质：4小时', fontSize: 10 }),
];

const buildPresets = (): PrintTemplate[] => [
  { id: 'preset_std', name: '标准小票', type: 'receipt', paperWidth: '80mm', elements: STANDARD_ELEMENTS, isDefault: true },
  { id: 'preset_simple', name: '简洁小票', type: 'receipt', paperWidth: '58mm', elements: SIMPLE_ELEMENTS, isDefault: false },
  { id: 'preset_detail', name: '详细小票', type: 'receipt', paperWidth: '80mm', elements: DETAIL_ELEMENTS, isDefault: false },
  { id: 'preset_kitchen', name: '标准厨房单', type: 'kitchen', paperWidth: '80mm', elements: KITCHEN_ELEMENTS, isDefault: true },
  { id: 'preset_label', name: '标签模板', type: 'label', paperWidth: '58mm', elements: LABEL_ELEMENTS, isDefault: true },
];

/* ═══════════════════════════════════════════
   色彩 & 通用样式
   ═══════════════════════════════════════════ */

const C = {
  bg: '#0B1A20',
  card: '#112228',
  cardAlt: '#112B36',
  border: '#1A3A48',
  accent: '#FF6B35',
  accentHover: '#FF8255',
  text: '#E0E0E0',
  textDim: '#8899A6',
  white: '#FFFFFF',
  danger: '#EF4444',
  success: '#22C55E',
} as const;

const BTN_BASE: React.CSSProperties = {
  minWidth: 48,
  minHeight: 48,
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  fontFamily: 'inherit',
  fontSize: 14,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 6,
  padding: '0 16px',
  transition: 'background 0.15s',
};

/* ═══════════════════════════════════════════
   子组件：元素编辑弹窗
   ═══════════════════════════════════════════ */

function ElementEditor({
  element,
  onSave,
  onClose,
}: {
  element: TemplateElement;
  onSave: (updated: TemplateElement) => void;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<TemplateElement>({ ...element });

  const field = (label: string, node: React.ReactNode) => (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 12, color: C.textDim, marginBottom: 4 }}>{label}</div>
      {node}
    </div>
  );

  const inputStyle: React.CSSProperties = {
    background: C.card,
    color: C.white,
    border: `1px solid ${C.border}`,
    borderRadius: 4,
    padding: '8px 10px',
    fontSize: 13,
    width: '100%',
    boxSizing: 'border-box',
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: C.cardAlt,
          borderRadius: 12,
          padding: 24,
          width: 360,
          maxHeight: '80vh',
          overflowY: 'auto',
        }}
        onClick={e => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 16px', color: C.white, fontSize: 16 }}>
          编辑 - {element.label}
        </h3>

        {/* 所有元素公共字段 */}
        {field(
          '对齐',
          <div style={{ display: 'flex', gap: 8 }}>
            {(['left', 'center', 'right'] as const).map(a => (
              <button
                key={a}
                style={{
                  ...BTN_BASE,
                  flex: 1,
                  background: draft.align === a ? C.accent : C.card,
                  color: C.white,
                }}
                onClick={() => setDraft(d => ({ ...d, align: a }))}
              >
                {a === 'left' ? '左' : a === 'center' ? '中' : '右'}
              </button>
            ))}
          </div>,
        )}

        {field(
          '字号',
          <input
            type="number"
            min={8}
            max={32}
            value={draft.fontSize ?? 13}
            onChange={e => setDraft(d => ({ ...d, fontSize: Number(e.target.value) }))}
            style={inputStyle}
          />,
        )}

        {field(
          '加粗',
          <button
            style={{
              ...BTN_BASE,
              background: draft.bold ? C.accent : C.card,
              color: C.white,
              width: '100%',
            }}
            onClick={() => setDraft(d => ({ ...d, bold: !d.bold }))}
          >
            {draft.bold ? '粗体 ON' : '粗体 OFF'}
          </button>,
        )}

        {/* 分隔线特有 */}
        {draft.kind === 'separator' &&
          field(
            '线型',
            <div style={{ display: 'flex', gap: 8 }}>
              {(['dashed', 'solid', 'blank'] as const).map(ls => (
                <button
                  key={ls}
                  style={{
                    ...BTN_BASE,
                    flex: 1,
                    background: draft.lineStyle === ls ? C.accent : C.card,
                    color: C.white,
                  }}
                  onClick={() => setDraft(d => ({ ...d, lineStyle: ls }))}
                >
                  {ls === 'dashed' ? '虚线' : ls === 'solid' ? '实线' : '空行'}
                </button>
              ))}
            </div>,
          )}

        {/* 自定义文字 / 页脚 / store_name */}
        {(draft.kind === 'custom_text' || draft.kind === 'footer' || draft.kind === 'store_name') &&
          field(
            '文字内容',
            <textarea
              rows={3}
              value={draft.text ?? ''}
              onChange={e => setDraft(d => ({ ...d, text: e.target.value }))}
              style={{ ...inputStyle, resize: 'vertical' }}
            />,
          )}

        <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
          <button
            style={{ ...BTN_BASE, flex: 1, background: C.accent, color: C.white }}
            onClick={() => onSave(draft)}
          >
            确定
          </button>
          <button
            style={{ ...BTN_BASE, flex: 1, background: C.card, color: C.text }}
            onClick={onClose}
          >
            取消
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   子组件：小票预览
   ═══════════════════════════════════════════ */

/** 模拟热敏小票打印效果 */
function ReceiptPreview({
  elements,
  paperWidth,
}: {
  elements: TemplateElement[];
  paperWidth: PaperWidth;
}) {
  const widthPx = paperWidth === '58mm' ? 220 : 300;

  const renderElement = (el: TemplateElement) => {
    const base: React.CSSProperties = {
      fontFamily: '"Courier New", "Noto Sans Mono", monospace',
      fontSize: el.fontSize ?? 13,
      textAlign: el.align ?? 'left',
      fontWeight: el.bold ? 'bold' : 'normal',
      lineHeight: 1.5,
      color: '#000',
      wordBreak: 'break-all',
    };

    switch (el.kind) {
      case 'store_name':
        return (
          <div key={el.id} style={{ ...base, fontSize: el.fontSize ?? 20, textAlign: 'center', fontWeight: 'bold', margin: '4px 0' }}>
            {el.text || '屯象餐厅'}
          </div>
        );
      case 'separator': {
        if (el.lineStyle === 'blank') return <div key={el.id} style={{ height: 12 }} />;
        const ch = el.lineStyle === 'solid' ? '━' : '- ';
        const count = el.lineStyle === 'solid' ? Math.floor(widthPx / 9) : Math.floor(widthPx / 12);
        return (
          <div key={el.id} style={{ ...base, textAlign: 'center', color: '#333', margin: '4px 0', letterSpacing: el.lineStyle === 'solid' ? -2 : 0 }}>
            {ch.repeat(count)}
          </div>
        );
      }
      case 'order_info':
        return (
          <div key={el.id} style={{ ...base, margin: '4px 0' }}>
            <div>订单号：TX20260402001</div>
            <div>桌号：A05</div>
            <div>时间：2026-04-02 12:30</div>
            <div>收银员：张三</div>
          </div>
        );
      case 'dish_list':
        return (
          <div key={el.id} style={{ ...base, margin: '4px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', borderBottom: '1px dashed #999', paddingBottom: 2 }}>
              <span style={{ flex: 2 }}>品名</span>
              <span style={{ width: 30, textAlign: 'center' }}>数量</span>
              <span style={{ width: 50, textAlign: 'right' }}>单价</span>
              <span style={{ width: 50, textAlign: 'right' }}>小计</span>
            </div>
            {[
              { name: '宫保鸡丁', qty: 1, price: 38 },
              { name: '水煮鱼', qty: 1, price: 58 },
              { name: '米饭', qty: 2, price: 3 },
            ].map((d, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <span style={{ flex: 2 }}>{d.name}</span>
                <span style={{ width: 30, textAlign: 'center' }}>{d.qty}</span>
                <span style={{ width: 50, textAlign: 'right' }}>{d.price.toFixed(2)}</span>
                <span style={{ width: 50, textAlign: 'right' }}>{(d.qty * d.price).toFixed(2)}</span>
              </div>
            ))}
          </div>
        );
      case 'amount_summary':
        return (
          <div key={el.id} style={{ ...base, margin: '4px 0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>小计</span><span>102.00</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>折扣</span><span>-10.00</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 'bold', fontSize: (el.fontSize ?? 13) + 2 }}><span>应付</span><span>92.00</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>实付</span><span>100.00</span></div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>找零</span><span>8.00</span></div>
          </div>
        );
      case 'payment_info':
        return (
          <div key={el.id} style={{ ...base, margin: '4px 0' }}>
            <div>支付方式：微信支付</div>
            <div>交易号：4200001234202604020001</div>
          </div>
        );
      case 'qrcode':
        return (
          <div key={el.id} style={{ ...base, textAlign: 'center', margin: '8px 0' }}>
            <div style={{
              width: 80,
              height: 80,
              border: '2px solid #000',
              margin: '0 auto',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 10,
              color: '#666',
            }}>
              [二维码]
            </div>
          </div>
        );
      case 'custom_text':
        return (
          <div key={el.id} style={{ ...base, margin: '4px 0' }}>
            {el.text || '自定义文字'}
          </div>
        );
      case 'footer':
        return (
          <div key={el.id} style={{ ...base, textAlign: 'center', margin: '8px 0', fontSize: el.fontSize ?? 12 }}>
            {el.text || '谢谢惠顾，欢迎再来！'}
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div
      style={{
        width: widthPx,
        background: '#FFFFFF',
        color: '#000000',
        padding: '12px 8px',
        fontFamily: '"Courier New", "Noto Sans Mono", monospace',
        fontSize: 13,
        borderRadius: 4,
        boxShadow: '0 2px 12px rgba(0,0,0,0.4)',
        margin: '0 auto',
        minHeight: 200,
      }}
    >
      {elements.map(renderElement)}
    </div>
  );
}

/* ═══════════════════════════════════════════
   主页面
   ═══════════════════════════════════════════ */

export function PrintTemplatePage() {
  const [templates, setTemplates] = useState<PrintTemplate[]>(buildPresets);
  const [activeType, setActiveType] = useState<TemplateType>('receipt');
  const [selectedId, setSelectedId] = useState<string>('preset_std');
  const [editingElement, setEditingElement] = useState<TemplateElement | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  /* 当前选中模板 */
  const current = useMemo(
    () => templates.find(t => t.id === selectedId) ?? templates.find(t => t.type === activeType) ?? templates[0],
    [templates, selectedId, activeType],
  );

  /* 按类型过滤 */
  const filteredTemplates = useMemo(
    () => templates.filter(t => t.type === activeType),
    [templates, activeType],
  );

  /* toast 工具 */
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2000);
  }, []);

  /* ── 模板操作 ── */

  const createTemplate = () => {
    const id = `tpl_${Date.now()}`;
    const newTpl: PrintTemplate = {
      id,
      name: `新模板 ${filteredTemplates.length + 1}`,
      type: activeType,
      paperWidth: '80mm',
      elements: [makeElement('store_name', { fontSize: 20, align: 'center', bold: true })],
      isDefault: false,
    };
    setTemplates(prev => [...prev, newTpl]);
    setSelectedId(id);
  };

  const setAsDefault = () => {
    setTemplates(prev =>
      prev.map(t =>
        t.type === activeType
          ? { ...t, isDefault: t.id === current.id }
          : t,
      ),
    );
    showToast(`"${current.name}" 已设为默认`);
  };

  const saveTemplate = () => {
    // 将来对接后端存储
    showToast('模板已保存');
  };

  const togglePaperWidth = () => {
    setTemplates(prev =>
      prev.map(t =>
        t.id === current.id
          ? { ...t, paperWidth: t.paperWidth === '58mm' ? '80mm' : '58mm' }
          : t,
      ),
    );
  };

  /* ── 元素操作 ── */

  const updateElements = (fn: (els: TemplateElement[]) => TemplateElement[]) => {
    setTemplates(prev =>
      prev.map(t => (t.id === current.id ? { ...t, elements: fn(t.elements) } : t)),
    );
  };

  const moveElement = (idx: number, dir: -1 | 1) => {
    const target = idx + dir;
    if (target < 0 || target >= current.elements.length) return;
    updateElements(els => {
      const next = [...els];
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };

  const removeElement = (idx: number) => {
    updateElements(els => els.filter((_, i) => i !== idx));
  };

  const addElement = (kind: ElementKind) => {
    updateElements(els => [...els, makeElement(kind)]);
  };

  const saveEditedElement = (updated: TemplateElement) => {
    updateElements(els => els.map(el => (el.id === updated.id ? updated : el)));
    setEditingElement(null);
  };

  /* ── 测试打印 ── */

  const handleTestPrint = async () => {
    // 生成简单文本表示并发送打印
    const lines: string[] = [];
    for (const el of current.elements) {
      switch (el.kind) {
        case 'store_name':
          lines.push(`\x1b\x61\x01\x1b\x45\x01${el.text || '屯象餐厅'}\x1b\x45\x00`);
          break;
        case 'separator':
          lines.push(el.lineStyle === 'blank' ? '' : (el.lineStyle === 'solid' ? '━'.repeat(32) : '- '.repeat(16)));
          break;
        case 'order_info':
          lines.push('订单号：TX20260402001');
          lines.push('桌号：A05  时间：12:30');
          break;
        case 'dish_list':
          lines.push('宫保鸡丁     x1  38.00');
          lines.push('水煮鱼       x1  58.00');
          lines.push('米饭         x2   6.00');
          break;
        case 'amount_summary':
          lines.push('合计：         102.00');
          lines.push('折扣：         -10.00');
          lines.push('应付：          92.00');
          break;
        case 'payment_info':
          lines.push('微信支付 92.00');
          break;
        case 'custom_text':
        case 'footer':
          lines.push(el.text || '');
          break;
        default:
          break;
      }
    }
    const text = lines.join('\n');
    const base64 = btoa(unescape(encodeURIComponent(text)));

    try {
      const result = await printReceipt(base64);
      showToast(result.ok ? `打印成功 (${result.channel})` : '打印失败');
    } catch {
      showToast('打印失败：无可用打印机');
    }
  };

  /* ── 渲染 ── */

  const TAB_TYPES: { key: TemplateType; label: string }[] = [
    { key: 'receipt', label: '小票' },
    { key: 'kitchen', label: '厨房单' },
    { key: 'label', label: '标签' },
  ];

  return (
    <div style={{ background: C.bg, minHeight: '100vh', color: C.text, fontFamily: '"Noto Sans SC", sans-serif' }}>
      {/* ── 顶部Tab ── */}
      <div style={{ display: 'flex', alignItems: 'center', background: C.card, padding: '0 20px', borderBottom: `1px solid ${C.border}` }}>
        <h2 style={{ margin: 0, marginRight: 32, fontSize: 18, color: C.white, padding: '14px 0' }}>
          打印模板
        </h2>
        {TAB_TYPES.map(tab => (
          <button
            key={tab.key}
            onClick={() => {
              setActiveType(tab.key);
              const first = templates.find(t => t.type === tab.key);
              if (first) setSelectedId(first.id);
            }}
            style={{
              ...BTN_BASE,
              background: activeType === tab.key ? C.accent : 'transparent',
              color: activeType === tab.key ? C.white : C.textDim,
              borderRadius: 0,
              borderBottom: activeType === tab.key ? `3px solid ${C.accent}` : '3px solid transparent',
              padding: '14px 20px',
              fontSize: 15,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── 三栏布局 ── */}
      <div style={{ display: 'flex', height: 'calc(100vh - 55px)' }}>
        {/* ━━ 左侧：模板列表（30%）━━ */}
        <div style={{ width: '30%', borderRight: `1px solid ${C.border}`, overflowY: 'auto', padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <span style={{ fontSize: 14, color: C.textDim }}>模板列表</span>
            <button
              onClick={createTemplate}
              style={{ ...BTN_BASE, background: C.accent, color: C.white, fontSize: 13, padding: '0 14px' }}
            >
              + 新建模板
            </button>
          </div>

          {filteredTemplates.map(tpl => (
            <div
              key={tpl.id}
              onClick={() => setSelectedId(tpl.id)}
              style={{
                background: tpl.id === selectedId ? C.accent + '22' : C.cardAlt,
                border: tpl.id === selectedId ? `2px solid ${C.accent}` : `1px solid ${C.border}`,
                borderRadius: 8,
                padding: 14,
                marginBottom: 10,
                cursor: 'pointer',
                transition: 'border 0.15s',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 15, color: C.white, fontWeight: tpl.id === selectedId ? 'bold' : 'normal' }}>
                  {tpl.name}
                </span>
                {tpl.isDefault && (
                  <span style={{
                    fontSize: 10,
                    background: C.success,
                    color: C.white,
                    borderRadius: 4,
                    padding: '2px 6px',
                    fontWeight: 'bold',
                  }}>
                    默认
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: C.textDim, marginTop: 4 }}>
                {tpl.paperWidth} | {tpl.elements.length} 个元素
              </div>
            </div>
          ))}

          {/* 元素面板 */}
          <div style={{ marginTop: 20 }}>
            <div style={{ fontSize: 14, color: C.textDim, marginBottom: 10 }}>添加元素</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {ELEMENT_PALETTE.map(p => (
                <button
                  key={p.kind}
                  onClick={() => addElement(p.kind)}
                  style={{
                    ...BTN_BASE,
                    background: C.card,
                    color: C.text,
                    border: `1px solid ${C.border}`,
                    fontSize: 12,
                    padding: '6px 12px',
                    minHeight: 36,
                  }}
                >
                  + {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ━━ 中间：编辑区（40%）━━ */}
        <div style={{ width: '40%', borderRight: `1px solid ${C.border}`, overflowY: 'auto', padding: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
            <span style={{ fontSize: 16, color: C.white, fontWeight: 'bold' }}>
              {current.name}
            </span>
            <button
              onClick={togglePaperWidth}
              style={{
                ...BTN_BASE,
                background: C.cardAlt,
                color: C.text,
                border: `1px solid ${C.border}`,
                fontSize: 12,
                padding: '0 12px',
              }}
            >
              纸宽：{current.paperWidth}
            </button>
          </div>

          {current.elements.length === 0 && (
            <div style={{ textAlign: 'center', color: C.textDim, padding: 40 }}>
              暂无元素，从左侧添加
            </div>
          )}

          {current.elements.map((el, idx) => (
            <div
              key={el.id}
              style={{
                background: C.cardAlt,
                border: `1px solid ${C.border}`,
                borderRadius: 8,
                padding: '12px 14px',
                marginBottom: 8,
                display: 'flex',
                alignItems: 'center',
                gap: 10,
              }}
            >
              {/* 序号 */}
              <span style={{ fontSize: 12, color: C.textDim, width: 24, textAlign: 'center', flexShrink: 0 }}>
                {idx + 1}
              </span>

              {/* 元素描述 */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 14, color: C.white }}>{el.label}</div>
                {el.text && (
                  <div style={{ fontSize: 12, color: C.textDim, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {el.text}
                  </div>
                )}
                {el.kind === 'separator' && (
                  <div style={{ fontSize: 11, color: C.textDim }}>
                    {el.lineStyle === 'dashed' ? '虚线' : el.lineStyle === 'solid' ? '实线' : '空行'}
                  </div>
                )}
              </div>

              {/* 操作按钮 */}
              <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                <button
                  onClick={() => moveElement(idx, -1)}
                  disabled={idx === 0}
                  style={{
                    ...BTN_BASE,
                    minWidth: 36,
                    minHeight: 36,
                    padding: 0,
                    background: idx === 0 ? C.card : C.border,
                    color: idx === 0 ? C.textDim : C.white,
                    fontSize: 16,
                  }}
                  title="上移"
                >
                  &#8593;
                </button>
                <button
                  onClick={() => moveElement(idx, 1)}
                  disabled={idx === current.elements.length - 1}
                  style={{
                    ...BTN_BASE,
                    minWidth: 36,
                    minHeight: 36,
                    padding: 0,
                    background: idx === current.elements.length - 1 ? C.card : C.border,
                    color: idx === current.elements.length - 1 ? C.textDim : C.white,
                    fontSize: 16,
                  }}
                  title="下移"
                >
                  &#8595;
                </button>
                <button
                  onClick={() => setEditingElement(el)}
                  style={{
                    ...BTN_BASE,
                    minWidth: 36,
                    minHeight: 36,
                    padding: 0,
                    background: C.border,
                    color: C.accent,
                    fontSize: 14,
                  }}
                  title="编辑"
                >
                  &#9998;
                </button>
                <button
                  onClick={() => removeElement(idx)}
                  style={{
                    ...BTN_BASE,
                    minWidth: 36,
                    minHeight: 36,
                    padding: 0,
                    background: C.card,
                    color: C.danger,
                    fontSize: 16,
                  }}
                  title="删除"
                >
                  &times;
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* ━━ 右侧：预览区（30%）━━ */}
        <div style={{ width: '30%', overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
          <div style={{ fontSize: 14, color: C.textDim, marginBottom: 12, alignSelf: 'flex-start' }}>
            实时预览 ({current.paperWidth})
          </div>

          {/* 小票模拟 */}
          <div style={{ background: '#2A2A2A', borderRadius: 8, padding: 16, width: '100%', maxWidth: 340, display: 'flex', justifyContent: 'center' }}>
            <ReceiptPreview elements={current.elements} paperWidth={current.paperWidth} />
          </div>

          {/* 操作按钮 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 20, width: '100%', maxWidth: 340 }}>
            <button
              onClick={handleTestPrint}
              style={{ ...BTN_BASE, background: C.accent, color: C.white, width: '100%', height: 52, fontSize: 15, fontWeight: 'bold' }}
            >
              打印测试
            </button>
            <button
              onClick={saveTemplate}
              style={{ ...BTN_BASE, background: C.cardAlt, color: C.white, border: `1px solid ${C.accent}`, width: '100%', height: 52, fontSize: 15 }}
            >
              保存模板
            </button>
            <button
              onClick={setAsDefault}
              style={{
                ...BTN_BASE,
                background: current.isDefault ? C.card : C.cardAlt,
                color: current.isDefault ? C.textDim : C.success,
                border: `1px solid ${current.isDefault ? C.border : C.success}`,
                width: '100%',
                height: 52,
                fontSize: 15,
              }}
            >
              {current.isDefault ? '已是默认模板' : '设为默认'}
            </button>
          </div>
        </div>
      </div>

      {/* ── 编辑弹窗 ── */}
      {editingElement && (
        <ElementEditor
          element={editingElement}
          onSave={saveEditedElement}
          onClose={() => setEditingElement(null)}
        />
      )}

      {/* ── Toast ── */}
      {toast && (
        <div
          style={{
            position: 'fixed',
            bottom: 40,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(0,0,0,0.85)',
            color: C.white,
            padding: '12px 28px',
            borderRadius: 8,
            fontSize: 14,
            zIndex: 2000,
            pointerEvents: 'none',
          }}
        >
          {toast}
        </div>
      )}
    </div>
  );
}
