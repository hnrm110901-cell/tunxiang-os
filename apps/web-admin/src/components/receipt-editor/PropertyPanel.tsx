/**
 * PropertyPanel — 右侧属性编辑面板（280px）
 * 根据选中元素类型动态显示对应属性
 */
import type { CSSProperties, ReactNode, ChangeEvent } from 'react';
import type { TemplateElement } from '../../api/receiptTemplateApi';

interface PropertyPanelProps {
  element: TemplateElement | null;
  onChange: (id: string, updates: Partial<TemplateElement>) => void;
}

export function PropertyPanel({ element, onChange }: PropertyPanelProps) {
  if (!element) {
    return (
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        padding: 24,
        background: 'var(--bg-1, #112228)',
        color: 'var(--text-4, #666)',
        fontSize: 13,
        textAlign: 'center',
        gap: 12,
      }}>
        <div style={{ fontSize: 28, opacity: 0.3 }}>⚙️</div>
        <div style={{ lineHeight: 1.6 }}>
          点击画布中的元素<br />编辑其属性
        </div>
      </div>
    );
  }

  const update = (updates: Partial<TemplateElement>) => onChange(element.id, updates);

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--bg-1, #112228)',
      overflow: 'hidden',
    }}>
      {/* 面板标题 */}
      <div style={{
        padding: '12px 14px 10px',
        borderBottom: '1px solid var(--bg-2, #1a2a33)',
        flexShrink: 0,
      }}>
        <div style={{
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: 'var(--text-3, #999)',
          marginBottom: 4,
        }}>
          属性面板
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-1, #fff)', fontWeight: 600 }}>
          {ELEMENT_LABELS[element.type] || element.type}
        </div>
      </div>

      {/* 属性内容 */}
      <div style={{ flex: 1, overflow: 'auto', padding: '12px 14px' }}>
        {/* 文字类：对齐、字体大小、加粗 */}
        {isTextElement(element.type) && (
          <>
            <PropSection title="对齐方式">
              <AlignSelector
                value={element.align || 'left'}
                onChange={(v) => update({ align: v })}
              />
            </PropSection>

            <PropSection title="字体大小">
              <RadioGroup
                value={element.size || 'normal'}
                options={[
                  { value: 'normal', label: '正常' },
                  { value: 'double_width', label: '宽大' },
                  { value: 'double_height', label: '高大' },
                  { value: 'double_both', label: '双倍' },
                ]}
                onChange={(v) => update({ size: v as TemplateElement['size'] })}
              />
            </PropSection>

            <PropSection title="加粗">
              <Toggle
                value={element.bold ?? false}
                onChange={(v) => update({ bold: v })}
                label="粗体文字"
              />
            </PropSection>
          </>
        )}

        {/* separator：分隔字符 */}
        {element.type === 'separator' && (
          <PropSection title="分隔字符">
            <RadioGroup
              value={element.char || '-'}
              options={[
                { value: '-', label: '- - -' },
                { value: '=', label: '= = =' },
                { value: '*', label: '* * *' },
                { value: '─', label: '─ ─ ─' },
                { value: '~', label: '~ ~ ~' },
              ]}
              onChange={(v) => update({ char: v })}
            />
          </PropSection>
        )}

        {/* order_info：字段勾选 */}
        {element.type === 'order_info' && (
          <PropSection title="显示字段">
            {[
              { key: 'table_no', label: '桌号' },
              { key: 'order_no', label: '单号' },
              { key: 'cashier', label: '收银员' },
              { key: 'datetime', label: '日期时间' },
            ].map(({ key, label }) => (
              <Checkbox
                key={key}
                label={label}
                checked={(element.fields || []).includes(key)}
                onChange={(checked) => {
                  const current = element.fields || [];
                  const next = checked
                    ? [...current, key]
                    : current.filter((f) => f !== key);
                  update({ fields: next });
                }}
              />
            ))}
          </PropSection>
        )}

        {/* order_items：显示列勾选 */}
        {element.type === 'order_items' && (
          <PropSection title="显示列">
            <Checkbox
              label="单价"
              checked={element.show_price ?? true}
              onChange={(v) => update({ show_price: v })}
            />
            <Checkbox
              label="数量"
              checked={element.show_qty ?? true}
              onChange={(v) => update({ show_qty: v })}
            />
            <Checkbox
              label="小计"
              checked={element.show_subtotal ?? true}
              onChange={(v) => update({ show_subtotal: v })}
            />
          </PropSection>
        )}

        {/* total_summary：折扣、服务费 */}
        {element.type === 'total_summary' && (
          <PropSection title="显示项">
            <Checkbox
              label="优惠折扣"
              checked={element.show_discount ?? true}
              onChange={(v) => update({ show_discount: v })}
            />
            <Checkbox
              label="服务费"
              checked={element.show_service_fee ?? false}
              onChange={(v) => update({ show_service_fee: v })}
            />
          </PropSection>
        )}

        {/* qrcode：内容字段 */}
        {element.type === 'qrcode' && (
          <PropSection title="二维码内容">
            <RadioGroup
              value={element.content_field || 'order_id'}
              options={[
                { value: 'order_id', label: '订单ID' },
                { value: 'store_id', label: '门店ID' },
                { value: 'custom', label: '自定义' },
              ]}
              onChange={(v) => update({ content_field: v })}
            />
            {element.content_field === 'custom' && (
              <div style={{ marginTop: 8 }}>
                <TextInput
                  label="自定义内容"
                  value={element.content || ''}
                  placeholder="输入二维码内容..."
                  onChange={(v) => update({ content: v })}
                />
              </div>
            )}
          </PropSection>
        )}

        {/* custom_text：文字内容 + 变量提示 */}
        {element.type === 'custom_text' && (
          <>
            <PropSection title="文字内容">
              <TextareaInput
                value={element.content || ''}
                placeholder="输入文字内容，支持变量..."
                onChange={(v) => update({ content: v })}
              />
              <div style={{
                marginTop: 6,
                padding: '6px 8px',
                background: 'var(--bg-2, #1a2a33)',
                borderRadius: 4,
                fontSize: 10,
                color: 'var(--text-4, #666)',
                lineHeight: 1.7,
              }}>
                <div style={{ fontWeight: 600, marginBottom: 2, color: 'var(--text-3, #999)' }}>可用变量</div>
                {'{{store_name}} {{order_no}} {{cashier}} {{datetime}} {{table_no}}'.split(' ').map((v) => (
                  <div
                    key={v}
                    style={{ cursor: 'pointer', color: 'var(--brand, #FF6B35)' }}
                    onClick={() => update({ content: (element.content || '') + v })}
                  >
                    {v}
                  </div>
                ))}
              </div>
            </PropSection>
            <PropSection title="对齐方式">
              <AlignSelector
                value={element.align || 'center'}
                onChange={(v) => update({ align: v })}
              />
            </PropSection>
          </>
        )}

        {/* logo_text：文字内容 */}
        {element.type === 'logo_text' && (
          <>
            <PropSection title="口号文字">
              <TextareaInput
                value={element.content || ''}
                placeholder="输入品牌口号..."
                onChange={(v) => update({ content: v })}
              />
            </PropSection>
            <PropSection title="对齐方式">
              <AlignSelector
                value={element.align || 'center'}
                onChange={(v) => update({ align: v })}
              />
            </PropSection>
            <PropSection title="加粗">
              <Toggle
                value={element.bold ?? true}
                onChange={(v) => update({ bold: v })}
                label="粗体显示"
              />
            </PropSection>
          </>
        )}

        {/* blank_lines：空行数 */}
        {element.type === 'blank_lines' && (
          <PropSection title="空行数量">
            <NumberStepper
              value={element.count || 1}
              min={1}
              max={5}
              onChange={(v) => update({ count: v })}
            />
          </PropSection>
        )}

        {/* inverted_header：反色横幅 */}
        {element.type === 'inverted_header' && (
          <>
            <PropSection title="文字内容">
              <TextareaInput
                value={element.content || ''}
                placeholder="输入横幅文字，支持变量..."
                onChange={(v) => update({ content: v })}
              />
              <div style={{
                marginTop: 6,
                padding: '6px 8px',
                background: 'var(--bg-2, #1a2a33)',
                borderRadius: 4,
                fontSize: 10,
                color: 'var(--text-4, #666)',
                lineHeight: 1.7,
              }}>
                <div style={{ fontWeight: 600, marginBottom: 2, color: 'var(--text-3, #999)' }}>可用变量</div>
                {'{{store_name}} {{order_no}} {{datetime}}'.split(' ').map((v) => (
                  <div
                    key={v}
                    style={{ cursor: 'pointer', color: 'var(--brand, #FF6B35)' }}
                    onClick={() => update({ content: (element.content || '') + v })}
                  >
                    {v}
                  </div>
                ))}
              </div>
            </PropSection>
            <PropSection title="对齐方式">
              <AlignSelector
                value={element.align || 'center'}
                onChange={(v) => update({ align: v })}
              />
            </PropSection>
            <PropSection title="字体大小">
              <RadioGroup
                value={element.size || 'double_height'}
                options={[
                  { value: 'normal', label: '正常' },
                  { value: 'double_height', label: '高大' },
                  { value: 'double_both', label: '双倍' },
                ]}
                onChange={(v) => update({ size: v as TemplateElement['size'] })}
              />
            </PropSection>
            <PropSection title="内边距">
              <NumberStepper
                value={element.padding ?? 2}
                min={1}
                max={4}
                onChange={(v) => update({ padding: v })}
              />
            </PropSection>
          </>
        )}

        {/* styled_separator：创意分隔线 */}
        {element.type === 'styled_separator' && (
          <PropSection title="分隔线样式">
            <SeparatorStylePicker
              value={element.style || 'dash'}
              onChange={(v) => update({ style: v })}
            />
          </PropSection>
        )}

        {/* box_section：盒型边框区块 */}
        {element.type === 'box_section' && (
          <>
            <PropSection title="边框风格">
              <RadioGroup
                value={element.style || 'single'}
                options={[
                  { value: 'single', label: '┌─┐ 单线边框' },
                  { value: 'double', label: '╔═╗ 双线边框' },
                ]}
                onChange={(v) => update({ style: v })}
              />
            </PropSection>
            <PropSection title="内容文字（每行一条）">
              <textarea
                value={(element.lines ?? ['感谢光临']).join('\n')}
                rows={4}
                placeholder="每行一条文字..."
                onChange={(e) => update({ lines: e.target.value.split('\n') })}
                style={{
                  width: '100%',
                  padding: '6px 8px',
                  borderRadius: 5,
                  border: '1px solid var(--bg-2, #1a2a33)',
                  background: 'var(--bg-0, #0B1A20)',
                  color: 'var(--text-1, #fff)',
                  fontSize: 12,
                  outline: 'none',
                  resize: 'vertical',
                  boxSizing: 'border-box',
                  fontFamily: 'inherit',
                }}
              />
            </PropSection>
            <PropSection title="内容对齐">
              <AlignSelector
                value={element.align || 'center'}
                onChange={(v) => update({ align: v })}
              />
            </PropSection>
          </>
        )}

        {/* logo_image：Logo图片 */}
        {element.type === 'logo_image' && (
          <>
            <PropSection title="Logo图片">
              <LogoImageUploader
                value={element.image_base64 || null}
                onChange={(b64) => update({ image_base64: b64 ?? undefined })}
              />
            </PropSection>
            <PropSection title="打印宽度">
              <RadioGroup
                value={String(element.max_width_dots ?? 384)}
                options={[
                  { value: '384', label: '384点（80mm纸）' },
                  { value: '288', label: '288点（58mm纸）' },
                ]}
                onChange={(v) => update({ max_width_dots: Number(v) })}
              />
            </PropSection>
          </>
        )}

        {/* underlined_text：下划线文字 */}
        {element.type === 'underlined_text' && (
          <>
            <PropSection title="文字内容">
              <TextareaInput
                value={element.content || ''}
                placeholder="输入文字，支持 {{变量}}..."
                onChange={(v) => update({ content: v })}
              />
              <div style={{
                marginTop: 6,
                padding: '6px 8px',
                background: 'var(--bg-2, #1a2a33)',
                borderRadius: 4,
                fontSize: 10,
                color: 'var(--text-4, #666)',
                lineHeight: 1.7,
              }}>
                <div style={{ fontWeight: 600, marginBottom: 2, color: 'var(--text-3, #999)' }}>可用变量</div>
                {'{{store_name}} {{order_no}} {{cashier}} {{datetime}} {{table_no}}'.split(' ').map((v) => (
                  <div
                    key={v}
                    style={{ cursor: 'pointer', color: 'var(--brand, #FF6B35)' }}
                    onClick={() => update({ content: (element.content || '') + v })}
                  >
                    {v}
                  </div>
                ))}
              </div>
            </PropSection>
            <PropSection title="对齐方式">
              <AlignSelector
                value={element.align || 'left'}
                onChange={(v) => update({ align: v })}
              />
            </PropSection>
            <PropSection title="加粗">
              <Toggle
                value={element.bold ?? false}
                onChange={(v) => update({ bold: v })}
                label="粗体文字"
              />
            </PropSection>
          </>
        )}
      </div>
    </div>
  );
}

// ─── 辅助：判断是否文字类元素 ───

function isTextElement(type: string): boolean {
  return ['store_name', 'store_address', 'payment_method', 'order_info'].includes(type);
}

const ELEMENT_LABELS: Record<string, string> = {
  store_name: '店名',
  store_address: '地址',
  separator: '分隔线',
  order_info: '订单信息',
  order_items: '菜品明细',
  total_summary: '合计区',
  payment_method: '支付方式',
  qrcode: '二维码',
  barcode: '条形码',
  custom_text: '自定义文字',
  blank_lines: '空行',
  logo_text: '品牌口号',
  inverted_header: '反色横幅',
  styled_separator: '创意分隔线',
  box_section: '边框区块',
  logo_image: 'Logo图片',
  underlined_text: '下划线文字',
};

// ─── 子组件：属性分区 ───

function PropSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        color: 'var(--text-3, #999)',
        marginBottom: 8,
      }}>
        {title}
      </div>
      {children}
    </div>
  );
}

// ─── 子组件：对齐选择 ───

function AlignSelector({
  value,
  onChange,
}: {
  value: 'left' | 'center' | 'right';
  onChange: (v: 'left' | 'center' | 'right') => void;
}) {
  const options = [
    { value: 'left' as const, label: '左', icon: '⬅' },
    { value: 'center' as const, label: '中', icon: '↔' },
    { value: 'right' as const, label: '右', icon: '➡' },
  ];

  return (
    <div style={{ display: 'flex', gap: 6 }}>
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          style={{
            flex: 1,
            padding: '6px 0',
            borderRadius: 5,
            border: '1px solid',
            borderColor: value === opt.value ? 'var(--brand, #FF6B35)' : 'var(--bg-2, #1a2a33)',
            background: value === opt.value ? 'rgba(255,107,53,0.15)' : 'var(--bg-2, #1a2a33)',
            color: value === opt.value ? 'var(--brand, #FF6B35)' : 'var(--text-3, #999)',
            fontSize: 12,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {opt.icon} {opt.label}
        </button>
      ))}
    </div>
  );
}

// ─── 子组件：单选组 ───

function RadioGroup({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {options.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          style={{
            padding: '6px 10px',
            borderRadius: 5,
            border: '1px solid',
            borderColor: value === opt.value ? 'var(--brand, #FF6B35)' : 'var(--bg-2, #1a2a33)',
            background: value === opt.value ? 'rgba(255,107,53,0.15)' : 'var(--bg-2, #1a2a33)',
            color: value === opt.value ? 'var(--brand, #FF6B35)' : 'var(--text-2, #ccc)',
            fontSize: 12,
            cursor: 'pointer',
            textAlign: 'left',
            transition: 'all 0.15s',
          }}
        >
          {value === opt.value ? '● ' : '○ '}{opt.label}
        </button>
      ))}
    </div>
  );
}

// ─── 子组件：勾选框 ───

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div
      onClick={() => onChange(!checked)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '5px 0',
        cursor: 'pointer',
        userSelect: 'none',
      }}
    >
      <div style={{
        width: 14,
        height: 14,
        borderRadius: 3,
        border: `1.5px solid ${checked ? '#FF6B35' : 'var(--text-4, #666)'}`,
        background: checked ? '#FF6B35' : 'transparent',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        transition: 'all 0.15s',
      }}>
        {checked && <span style={{ color: '#fff', fontSize: 9, fontWeight: 700 }}>✓</span>}
      </div>
      <span style={{ fontSize: 12, color: 'var(--text-2, #ccc)' }}>{label}</span>
    </div>
  );
}

// ─── 子组件：开关 ───

function Toggle({
  value,
  onChange,
  label,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <div
      onClick={() => onChange(!value)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        cursor: 'pointer',
        userSelect: 'none',
      }}
    >
      <div style={{
        width: 32,
        height: 18,
        borderRadius: 9,
        background: value ? '#FF6B35' : 'var(--bg-2, #1a2a33)',
        position: 'relative',
        transition: 'background 0.2s',
        flexShrink: 0,
      }}>
        <div style={{
          position: 'absolute',
          top: 2,
          left: value ? 16 : 2,
          width: 14,
          height: 14,
          borderRadius: '50%',
          background: '#fff',
          transition: 'left 0.2s',
        }} />
      </div>
      <span style={{ fontSize: 12, color: 'var(--text-2, #ccc)' }}>{label}</span>
    </div>
  );
}

// ─── 子组件：文本输入 ───

function TextInput({
  label,
  value,
  placeholder,
  onChange,
}: {
  label?: string;
  value: string;
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      {label && (
        <div style={{ fontSize: 11, color: 'var(--text-3, #999)', marginBottom: 4 }}>{label}</div>
      )}
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: '100%',
          padding: '6px 8px',
          borderRadius: 5,
          border: '1px solid var(--bg-2, #1a2a33)',
          background: 'var(--bg-0, #0B1A20)',
          color: 'var(--text-1, #fff)',
          fontSize: 12,
          outline: 'none',
          boxSizing: 'border-box',
        }}
      />
    </div>
  );
}

// ─── 子组件：文本域 ───

function TextareaInput({
  value,
  placeholder,
  onChange,
}: {
  value: string;
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  return (
    <textarea
      value={value}
      placeholder={placeholder}
      rows={3}
      onChange={(e) => onChange(e.target.value)}
      style={{
        width: '100%',
        padding: '6px 8px',
        borderRadius: 5,
        border: '1px solid var(--bg-2, #1a2a33)',
        background: 'var(--bg-0, #0B1A20)',
        color: 'var(--text-1, #fff)',
        fontSize: 12,
        outline: 'none',
        resize: 'vertical',
        boxSizing: 'border-box',
        fontFamily: 'inherit',
      }}
    />
  );
}

// ─── 子组件：数字步进器 ───

function NumberStepper({
  value,
  min,
  max,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <button
        onClick={() => onChange(Math.max(min, value - 1))}
        disabled={value <= min}
        style={stepperBtnStyle(value <= min)}
      >
        −
      </button>
      <span style={{
        minWidth: 32,
        textAlign: 'center',
        fontSize: 14,
        fontWeight: 600,
        color: 'var(--text-1, #fff)',
      }}>
        {value}
      </span>
      <button
        onClick={() => onChange(Math.min(max, value + 1))}
        disabled={value >= max}
        style={stepperBtnStyle(value >= max)}
      >
        +
      </button>
      <span style={{ fontSize: 11, color: 'var(--text-4, #666)' }}>行</span>
    </div>
  );
}

function stepperBtnStyle(disabled: boolean): CSSProperties {
  return {
    width: 28,
    height: 28,
    borderRadius: 5,
    border: '1px solid var(--bg-2, #1a2a33)',
    background: disabled ? 'transparent' : 'var(--bg-2, #1a2a33)',
    color: disabled ? 'var(--text-4, #666)' : 'var(--text-1, #fff)',
    fontSize: 16,
    cursor: disabled ? 'not-allowed' : 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  };
}

// ─── 子组件：创意分隔线样式选择器 ───

const SEPARATOR_STYLES = [
  { key: 'dash',      preview: '-------------------------------' },
  { key: 'double',    preview: '═══════════════════════════' },
  { key: 'dots',      preview: '···············································' },
  { key: 'diamond',   preview: '◆ ◆ ◆ ◆ ◆ ◆ ◆ ◆' },
  { key: 'star',      preview: '★ ★ ★ ★ ★ ★ ★ ★' },
  { key: 'ornament',  preview: '✦──────────────────────✦' },
  { key: 'bracket',   preview: '【──────────────────────】' },
  { key: 'bold_dash', preview: '==============================' },
  { key: 'wave',      preview: '～～～～～～～～～～～～' },
  { key: 'dot_line',  preview: '·  ·  ·  ·  ·  ·  ·  ·' },
];

function SeparatorStylePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {SEPARATOR_STYLES.map((s) => (
        <button
          key={s.key}
          onClick={() => onChange(s.key)}
          style={{
            padding: '5px 8px',
            borderRadius: 5,
            border: '1px solid',
            borderColor: value === s.key ? 'var(--brand, #FF6B35)' : 'var(--bg-2, #1a2a33)',
            background: value === s.key ? 'rgba(255,107,53,0.15)' : 'var(--bg-2, #1a2a33)',
            color: value === s.key ? 'var(--brand, #FF6B35)' : 'var(--text-3, #999)',
            fontSize: 10,
            cursor: 'pointer',
            textAlign: 'left',
            fontFamily: '"Courier New", Courier, monospace',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            transition: 'all 0.15s',
          }}
          title={s.key}
        >
          {s.preview}
        </button>
      ))}
    </div>
  );
}

// ─── 子组件：Logo图片上传 ───

function LogoImageUploader({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (b64: string | null) => void;
}) {
  const handleFile = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      // 去掉 data:image/xxx;base64, 前缀
      const b64 = result.split(',')[1] ?? result;
      onChange(b64);
    };
    reader.readAsDataURL(file);
    // 清空input，允许重复上传同一文件
    e.target.value = '';
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {value && (
        <div style={{ textAlign: 'center' }}>
          <img
            src={`data:image/png;base64,${value}`}
            alt="logo preview"
            style={{
              maxWidth: '100%',
              maxHeight: 64,
              objectFit: 'contain',
              filter: 'grayscale(100%)',
              border: '1px solid var(--bg-2, #1a2a33)',
              borderRadius: 4,
              padding: 4,
            }}
          />
        </div>
      )}
      <label style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        padding: '7px 12px',
        borderRadius: 5,
        border: '1px dashed var(--bg-2, #1a2a33)',
        background: 'var(--bg-0, #0B1A20)',
        color: 'var(--text-3, #999)',
        fontSize: 12,
        cursor: 'pointer',
        transition: 'border-color 0.15s',
      }}>
        🖼 {value ? '重新上传' : '选择图片'}
        <input
          type="file"
          accept=".png,.jpg,.jpeg"
          style={{ display: 'none' }}
          onChange={handleFile}
        />
      </label>
      {value && (
        <button
          onClick={() => onChange(null)}
          style={{
            padding: '5px 10px',
            borderRadius: 5,
            border: '1px solid rgba(163,45,45,0.5)',
            background: 'rgba(163,45,45,0.15)',
            color: '#c66',
            fontSize: 12,
            cursor: 'pointer',
          }}
        >
          清除图片
        </button>
      )}
    </div>
  );
}
