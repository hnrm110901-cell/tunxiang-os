/**
 * ReceiptCanvas — 中间画布组件
 * 模拟热敏打印机小票纸张，渲染元素预览，支持上移/下移/删除/选中
 */
import { useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import type { TemplateElement } from '../../api/receiptTemplateApi';

interface ReceiptCanvasProps {
  elements: TemplateElement[];
  paperWidth: 58 | 80;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onReorder: (fromIndex: number, toIndex: number) => void;
  onDelete: (id: string) => void;
}

export function ReceiptCanvas({
  elements,
  paperWidth,
  selectedId,
  onSelect,
  onReorder,
  onDelete,
}: ReceiptCanvasProps) {
  // 80mm ≈ 320px，58mm ≈ 232px（热敏纸的实际打印宽度比例）
  const canvasWidth = paperWidth === 80 ? 320 : 232;

  return (
    <div
      style={{
        width: canvasWidth,
        minHeight: 400,
        backgroundColor: '#FFFFF8',
        boxShadow: '0 2px 8px rgba(0,0,0,0.15), 0 0 0 1px rgba(0,0,0,0.05)',
        fontFamily: "'Courier New', Courier, monospace",
        fontSize: '11px',
        lineHeight: '1.4',
        padding: '16px 8px 12px',
        position: 'relative',
        cursor: 'default',
        borderRadius: 2,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onSelect(null);
      }}
    >
      {/* 模拟纸张顶部锯齿 */}
      <div style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 6,
        background: 'repeating-linear-gradient(90deg, #fff 0 8px, #e5e5e5 8px 10px)',
        borderRadius: '2px 2px 0 0',
      }} />

      <div style={{ marginTop: 4 }}>
        {elements.length === 0 ? (
          <EmptyCanvas />
        ) : (
          elements.map((el, index) => (
            <CanvasElement
              key={el.id}
              element={el}
              index={index}
              total={elements.length}
              isSelected={selectedId === el.id}
              onSelect={() => onSelect(el.id)}
              onMoveUp={() => onReorder(index, index - 1)}
              onMoveDown={() => onReorder(index, index + 1)}
              onDelete={() => onDelete(el.id)}
            />
          ))
        )}
      </div>

      {/* 模拟纸张底部虚线切割线 */}
      {elements.length > 0 && (
        <div style={{
          marginTop: 12,
          borderTop: '1px dashed #ccc',
          paddingTop: 4,
          textAlign: 'center',
          fontSize: 9,
          color: '#ccc',
          fontFamily: 'monospace',
          letterSpacing: 2,
        }}>
          - - - - - - CUT - - - - - -
        </div>
      )}
    </div>
  );
}

// ─── 空画布提示 ───

function EmptyCanvas() {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '48px 16px',
      gap: 8,
    }}>
      <div style={{ fontSize: 32, opacity: 0.3 }}>🧾</div>
      <div style={{ fontSize: 12, color: '#bbb', textAlign: 'center', lineHeight: 1.5 }}>
        从左侧面板点击元素<br />添加到小票
      </div>
    </div>
  );
}

// ─── 单个画布元素（带悬停操作按钮） ───

interface CanvasElementProps {
  element: TemplateElement;
  index: number;
  total: number;
  isSelected: boolean;
  onSelect: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onDelete: () => void;
}

function CanvasElement({
  element,
  index,
  total,
  isSelected,
  onSelect,
  onMoveUp,
  onMoveDown,
  onDelete,
}: CanvasElementProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      onClick={(e) => { e.stopPropagation(); onSelect(); }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        position: 'relative',
        borderRadius: 2,
        outline: isSelected
          ? '2px solid #FF6B35'
          : hovered
          ? '1px dashed #bbb'
          : '1px solid transparent',
        outlineOffset: 1,
        marginBottom: 1,
        cursor: 'pointer',
        transition: 'outline 0.1s',
      }}
    >
      {/* 元素预览内容 */}
      <ElementPreview element={element} />

      {/* 悬停操作按钮 */}
      {(hovered || isSelected) && (
        <div
          style={{
            position: 'absolute',
            top: 2,
            right: 2,
            display: 'flex',
            gap: 2,
            zIndex: 10,
          }}
          onClick={(e) => e.stopPropagation()}
        >
          <ActionBtn
            title="上移"
            disabled={index === 0}
            onClick={onMoveUp}
          >
            ↑
          </ActionBtn>
          <ActionBtn
            title="下移"
            disabled={index === total - 1}
            onClick={onMoveDown}
          >
            ↓
          </ActionBtn>
          <ActionBtn
            title="删除"
            onClick={onDelete}
            danger
          >
            ✕
          </ActionBtn>
        </div>
      )}

      {/* 选中状态标签 */}
      {isSelected && (
        <div style={{
          position: 'absolute',
          top: 2,
          left: 2,
          fontSize: 9,
          background: '#FF6B35',
          color: '#fff',
          borderRadius: 3,
          padding: '1px 5px',
          lineHeight: 1.5,
          pointerEvents: 'none',
        }}>
          已选中
        </div>
      )}
    </div>
  );
}

// ─── 操作按钮 ───

interface ActionBtnProps {
  title: string;
  disabled?: boolean;
  danger?: boolean;
  onClick: () => void;
  children: ReactNode;
}

function ActionBtn({ title, disabled, danger, onClick, children }: ActionBtnProps) {
  const [hov, setHov] = useState(false);
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        width: 20,
        height: 20,
        border: 'none',
        borderRadius: 3,
        cursor: disabled ? 'not-allowed' : 'pointer',
        fontSize: 10,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: disabled
          ? 'rgba(0,0,0,0.1)'
          : danger
          ? hov ? '#A32D2D' : 'rgba(163,45,45,0.8)'
          : hov ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.15)',
        color: disabled ? '#bbb' : '#fff',
        transition: 'background 0.1s',
        padding: 0,
      }}
    >
      {children}
    </button>
  );
}

// ─── 元素预览渲染器 ───

function ElementPreview({ element }: { element: TemplateElement }) {
  const textAlign = element.align || 'left';
  const fontWeight = element.bold ? 700 : 400;
  const baseFontSize = (() => {
    switch (element.size) {
      case 'double_both':   return 16;
      case 'double_width':  return 14;
      case 'double_height': return 14;
      default:              return 11;
    }
  })();

  const baseStyle: CSSProperties = {
    fontFamily: '"Courier New", Courier, monospace',
    fontSize: baseFontSize,
    fontWeight,
    textAlign: textAlign as CSSProperties['textAlign'],
    padding: '3px 4px',
    color: '#1a1a1a',
    lineHeight: 1.4,
    wordBreak: 'break-all',
  };

  switch (element.type) {
    case 'store_name':
      return (
        <div style={baseStyle}>
          <div>【 示例门店名称 】</div>
        </div>
      );

    case 'store_address':
      return (
        <div style={{ ...baseStyle, fontSize: 10 }}>
          地址：湖南省长沙市示例路 88 号
        </div>
      );

    case 'separator': {
      const char = element.char || '-';
      const line = char.repeat(32);
      return (
        <div style={{ ...baseStyle, textAlign: 'center', letterSpacing: 1, fontSize: 10 }}>
          {line}
        </div>
      );
    }

    case 'order_info': {
      const fields = element.fields || ['table_no', 'order_no', 'datetime'];
      const fieldLabels: Record<string, string> = {
        table_no: '桌号',
        order_no: '单号',
        cashier: '收银',
        datetime: '时间',
      };
      return (
        <div style={{ ...baseStyle, fontSize: 10 }}>
          {fields.map((f) => (
            <div key={f} style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>{fieldLabels[f] || f}：</span>
              <span style={{ color: '#555' }}>
                {f === 'datetime' ? '2026-03-31 12:00'
                  : f === 'table_no' ? 'A-05'
                  : f === 'order_no' ? 'ORD-20260331-0001'
                  : f === 'cashier' ? '张收银'
                  : '—'}
              </span>
            </div>
          ))}
        </div>
      );
    }

    case 'order_items':
      return (
        <div style={{ ...baseStyle, fontSize: 10 }}>
          {/* 表头 */}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            borderBottom: '1px solid #ddd',
            paddingBottom: 2,
            marginBottom: 2,
            fontWeight: 700,
          }}>
            <span style={{ flex: 3 }}>菜品名称</span>
            {element.show_qty !== false && <span style={{ flex: 1, textAlign: 'right' }}>数量</span>}
            {element.show_price !== false && <span style={{ flex: 1, textAlign: 'right' }}>单价</span>}
            {element.show_subtotal !== false && <span style={{ flex: 1, textAlign: 'right' }}>小计</span>}
          </div>
          {/* 示例行 */}
          {[
            { name: '招牌红烧肉', qty: 1, price: '88.00', sub: '88.00' },
            { name: '清蒸武昌鱼', qty: 2, price: '128.00', sub: '256.00' },
            { name: '农家小炒肉', qty: 1, price: '38.00', sub: '38.00' },
          ].map((item) => (
            <div key={item.name} style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: 1 }}>
              <span style={{ flex: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {item.name}
              </span>
              {element.show_qty !== false && <span style={{ flex: 1, textAlign: 'right' }}>x{item.qty}</span>}
              {element.show_price !== false && <span style={{ flex: 1, textAlign: 'right' }}>¥{item.price}</span>}
              {element.show_subtotal !== false && <span style={{ flex: 1, textAlign: 'right' }}>¥{item.sub}</span>}
            </div>
          ))}
        </div>
      );

    case 'total_summary':
      return (
        <div style={{ ...baseStyle, fontSize: 10 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700 }}>
            <span>合计：</span>
            <span>¥382.00</span>
          </div>
          {element.show_discount && (
            <div style={{ display: 'flex', justifyContent: 'space-between', color: '#c00' }}>
              <span>优惠：</span>
              <span>-¥20.00</span>
            </div>
          )}
          {element.show_service_fee && (
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>服务费：</span>
              <span>¥36.20</span>
            </div>
          )}
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontWeight: 700,
            fontSize: 13,
            borderTop: '1px solid #ddd',
            marginTop: 2,
            paddingTop: 2,
          }}>
            <span>实付：</span>
            <span>¥362.00</span>
          </div>
        </div>
      );

    case 'payment_method':
      return (
        <div style={{ ...baseStyle, fontSize: 10, textAlign: textAlign as CSSProperties['textAlign'] }}>
          支付方式：微信支付
        </div>
      );

    case 'qrcode':
      return (
        <div style={{ ...baseStyle, textAlign: 'center' }}>
          <div style={{
            display: 'inline-flex',
            width: 60,
            height: 60,
            background: '#f0f0f0',
            border: '1px solid #ccc',
            borderRadius: 2,
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 9,
            color: '#888',
          }}>
            [二维码]
          </div>
          {element.content && (
            <div style={{ fontSize: 9, color: '#888', marginTop: 2 }}>{element.content}</div>
          )}
        </div>
      );

    case 'barcode':
      return (
        <div style={{ ...baseStyle, textAlign: 'center' }}>
          <div style={{
            display: 'inline-block',
            width: 120,
            height: 32,
            background: 'repeating-linear-gradient(90deg, #000 0 2px, #fff 2px 4px)',
            border: '1px solid #ccc',
          }} />
          <div style={{ fontSize: 9, color: '#888', marginTop: 2 }}>ORD-20260331-0001</div>
        </div>
      );

    case 'custom_text':
      return (
        <div style={{ ...baseStyle }}>
          {element.content || '自定义文字内容'}
        </div>
      );

    case 'logo_text':
      return (
        <div style={{ ...baseStyle, textAlign: 'center', fontStyle: 'italic' }}>
          {element.content || '品牌口号文字'}
        </div>
      );

    case 'blank_lines': {
      const count = element.count || 1;
      return (
        <div style={{ height: count * 14, fontSize: 10, color: '#ddd', textAlign: 'center', lineHeight: `${count * 14}px` }}>
          {/* 空行 × {count} */}
        </div>
      );
    }

    case 'inverted_header': {
      const sizeStyle: CSSProperties = {
        double_both:   { fontSize: 16, fontWeight: 700 },
        double_height: { fontSize: 14, fontWeight: 700 },
        double_width:  { fontSize: 12, fontWeight: 700, letterSpacing: '0.15em' },
        normal:        { fontSize: 11, fontWeight: 700 },
      }[element.size ?? 'double_height'] ?? { fontSize: 14, fontWeight: 700 };
      return (
        <div style={{
          backgroundColor: '#000',
          color: '#fff',
          textAlign: 'center',
          padding: `${(element.padding ?? 2) * 3}px 8px`,
          fontFamily: '"Courier New", Courier, monospace',
          ...sizeStyle,
        }}>
          <div style={{ opacity: 0, fontSize: 9, lineHeight: '1em' }}>█</div>
          {element.content || '示例门店名称'}
          <div style={{ opacity: 0, fontSize: 9, lineHeight: '1em' }}>█</div>
        </div>
      );
    }

    case 'styled_separator': {
      const styleMap: Record<string, string> = {
        double:    '════════════════════════════════════════════',
        dots:      '················································',
        diamond:   '◆ ◆ ◆ ◆ ◆ ◆ ◆ ◆ ◆ ◆ ◆ ◆',
        star:      '★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★ ★',
        wave:      '～～～～～～～～～～～～～～～～～～～',
        dash:      '------------------------------------------------',
        bold_dash: '================================================',
        dot_line:  '·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·',
        ornament:  '✦──────────────────────────────────────✦',
        bracket:   '【──────────────────────────────────────】',
      };
      return (
        <div style={{
          textAlign: 'center',
          color: '#888',
          overflow: 'hidden',
          fontSize: 10,
          padding: '2px 0',
          fontFamily: '"Courier New", Courier, monospace',
        }}>
          {styleMap[element.style ?? 'dash'] ?? '--------------------------------'}
        </div>
      );
    }

    case 'box_section': {
      const isDouble = element.style === 'double';
      const [tl, tr, bl, br, h, v] = isDouble
        ? ['╔', '╗', '╚', '╝', '═', '║']
        : ['┌', '┐', '└', '┘', '─', '│'];
      const lines = element.lines ?? ['感谢光临'];
      const width = 38;
      return (
        <div style={{
          fontSize: 10,
          padding: '2px 0',
          fontFamily: '"Courier New", Courier, monospace',
          color: '#1a1a1a',
          whiteSpace: 'pre',
          overflow: 'hidden',
        }}>
          <div>{tl}{h.repeat(width)}{tr}</div>
          {lines.map((line, i) => {
            const padded = line.padStart(Math.floor((width + line.length) / 2)).padEnd(width);
            return <div key={i}>{v}{padded}{v}</div>;
          })}
          <div>{bl}{h.repeat(width)}{br}</div>
        </div>
      );
    }

    case 'logo_image': {
      return (
        <div style={{ display: 'flex', justifyContent: 'center', padding: '4px 0' }}>
          {element.image_base64 ? (
            <img
              src={`data:image/png;base64,${element.image_base64}`}
              alt="logo"
              style={{ maxHeight: 64, objectFit: 'contain', filter: 'grayscale(100%)' }}
            />
          ) : (
            <div style={{
              border: '1px dashed #ccc',
              width: 96,
              height: 48,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#aaa',
              fontSize: 10,
              gap: 4,
            }}>
              🖼 点击上传Logo
            </div>
          )}
        </div>
      );
    }

    case 'underlined_text': {
      const alignStyle = { left: 'left', center: 'center', right: 'right' }[element.align ?? 'left'] as CSSProperties['textAlign'];
      return (
        <div style={{
          fontSize: 11,
          textDecoration: 'underline',
          padding: '2px 4px',
          textAlign: alignStyle,
          fontWeight: element.bold ? 700 : 400,
          fontFamily: '"Courier New", Courier, monospace',
          color: '#1a1a1a',
        }}>
          {element.content || '下划线文字'}
        </div>
      );
    }

    default:
      return (
        <div style={{ ...baseStyle, fontSize: 10, color: '#aaa' }}>
          [{(element as TemplateElement).type}]
        </div>
      );
  }
}
