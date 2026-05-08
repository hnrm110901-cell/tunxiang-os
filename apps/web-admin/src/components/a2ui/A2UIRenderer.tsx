/**
 * A2UIRenderer — Google A2UI v0.8 JSON → React 渲染引擎
 *
 * 接受 Agent 返回的 A2UIDeclaration JSON，按白名单组件目录映射到 React 组件。
 *
 * 安全：只渲染白名单中的组件类型，拒绝未知类型（静默跳过 + console warn）。
 * 特性：
 *   - 嵌套递归渲染（children[]）
 *   - action 回调（按钮/列表项 → Agent action dispatch）
 *   - 错误降级（无效节点不阻断渲染）
 *   - 暗色主题适配
 */
import { type ReactNode } from 'react';
import { txColors } from '@tx/tokens';
import type {
  A2UINode, A2UIDeclaration, A2UIActionCallback, A2UIRenderContext,
  A2UIButtonProps, A2UICardProps, A2UIListProps, A2UIListItem,
  A2UITableProps, A2UIProgressProps, A2UIBadgeProps, A2UIChartProps,
  // Sprint 3 S3-01 新增 6 种
  A2UIFormProps, A2UIMapProps, A2UIHeatmapProps, A2UITimelineProps,
  A2UICascaderProps, A2UICascaderOption, A2UITabsProps,
} from './types';

// ─── Design Tokens ──────────────────────────────────────────────────────────────

const T = {
  bg: '#0B1A20',
  card: '#112B36',
  cardBorder: '#1A3A48',
  text: '#E0E0E0',
  text2: 'rgba(255,255,255,0.55)',
  text3: 'rgba(255,255,255,0.3)',
  accent: txColors.primary,
  success: '#10B981',
  warning: '#F59E0B',
  danger: '#EF4444',
  info: '#1890ff',
};

// ─── Props ──────────────────────────────────────────────────────────────────────

interface A2UIRendererProps {
  declaration: A2UIDeclaration | null;
  onAction?: A2UIActionCallback;
  context?: A2UIRenderContext;
  loading?: boolean;
  error?: string | null;
}

// ─── 子组件 ───────────────────────────────────────────────────────────────────────

function SeverityBar({ severity }: { severity?: string }) {
  const color =
    severity === 'critical' ? T.danger :
    severity === 'warning' ? T.warning :
    severity === 'info' ? T.info : 'transparent';
  if (!severity) return null;
  return <div style={{ width: 3, height: '100%', background: color, borderRadius: '3px 0 0 3px', position: 'absolute', left: 0, top: 0 }} />;
}

function A2UIBadge({ text, variant = 'info' }: A2UIBadgeProps) {
  const bg = { success: 'rgba(16,185,129,0.12)', warning: 'rgba(245,158,11,0.12)', danger: 'rgba(239,68,68,0.12)', info: 'rgba(24,144,255,0.12)' }[variant];
  const color = { success: T.success, warning: T.warning, danger: T.danger, info: T.info }[variant];
  return (
    <span style={{ padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: bg, color }}>
      {text}
    </span>
  );
}

function A2UIProgress({ value, max, label, color = 'accent' }: A2UIProgressProps) {
  const pct = Math.min((value / max) * 100, 100);
  const c = { success: T.success, warning: T.warning, danger: T.danger, accent: T.accent }[color];
  return (
    <div style={{ margin: '8px 0' }}>
      {label && <div style={{ fontSize: 12, color: T.text2, marginBottom: 4 }}>{label}</div>}
      <div style={{ height: 8, borderRadius: 4, background: '#1A3A48', overflow: 'hidden' }}>
        <div style={{ height: '100%', borderRadius: 4, width: `${pct}%`, background: c, transition: 'width 300ms ease' }} />
      </div>
      <div style={{ textAlign: 'right', fontSize: 11, color: T.text3, marginTop: 2 }}>
        {value}/{max}
      </div>
    </div>
  );
}

function A2UIChart({ chartType, title, data, height = 120 }: A2UIChartProps) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div style={{ padding: '8px 0' }}>
      {title && <div style={{ fontSize: 13, fontWeight: 600, color: T.text, marginBottom: 8 }}>{title}</div>}
      {chartType === 'number' ? (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          {data.map((d, i) => (
            <div key={i} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 28, fontWeight: 900, color: d.color || T.accent }}>{d.value}</div>
              <div style={{ fontSize: 11, color: T.text2, marginTop: 2 }}>{d.label}</div>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 4, height }}>
          {data.map((d, i) => (
            <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end' }}>
              <div style={{ fontSize: 10, color: T.text2, marginBottom: 2 }}>{d.value}</div>
              <div style={{
                width: '100%', maxWidth: 40,
                height: `${(d.value / max) * 100}%`,
                background: d.color || T.accent,
                borderRadius: '4px 4px 0 0',
                transition: 'height 300ms ease',
              }} />
              <div style={{ fontSize: 10, color: T.text3, marginTop: 4, textAlign: 'center' }}>{d.label}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function A2UITable({ columns, rows }: A2UITableProps) {
  return (
    <div style={{ overflowX: 'auto', borderRadius: 8, border: `1px solid ${T.cardBorder}` }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ background: '#0D2430' }}>
            {columns.map((col) => (
              <th key={col.key} style={{ padding: '6px 10px', color: T.text2, fontWeight: 600, textAlign: col.align || 'left' }}>
                {col.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ borderTop: `1px solid ${T.cardBorder}` }}>
              {columns.map((col) => (
                <td key={col.key} style={{ padding: '6px 10px', color: T.text, textAlign: col.align || 'left' }}>
                  {String(row[col.key] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── 核心渲染函数 ──────────────────────────────────────────────────────────────

/** 递归渲染 A2UI 节点树 */
function renderNode(
  node: A2UINode,
  onAction?: A2UIActionCallback,
  ctx?: A2UIRenderContext,
): ReactNode {
  const { type, id, props, children } = node;

  switch (type) {
    // ── Card ──
    case 'card': {
      const cp = props as unknown as A2UICardProps;
      return (
        <div key={id} style={{
          position: 'relative',
          background: T.card,
          border: `1px solid ${cp.severity === 'critical' ? 'rgba(239,68,68,0.3)' : cp.severity === 'warning' ? 'rgba(245,158,11,0.3)' : T.cardBorder}`,
          borderRadius: 10,
          padding: '12px 16px',
          marginBottom: 10,
        }}>
          <SeverityBar severity={cp.severity} />
          {cp.title && <div style={{ fontSize: 15, fontWeight: 700, color: T.text, marginBottom: cp.subtitle ? 2 : 8 }}>{cp.title}</div>}
          {cp.subtitle && <div style={{ fontSize: 12, color: T.text2, marginBottom: 8 }}>{cp.subtitle}</div>}
          {children?.map((child) => renderNode(child, onAction, ctx))}
        </div>
      );
    }

    // ── Text ──
    case 'text': {
      const variant = (props.variant as string) || 'body';
      const size = variant === 'heading' ? 18 : variant === 'subheading' ? 14 : variant === 'caption' ? 11 : 13;
      const weight = variant === 'heading' ? 700 : variant === 'subheading' ? 600 : 400;
      return (
        <div key={id} style={{
          fontSize: size, fontWeight: weight,
          color: props.color ? String(props.color) : T.text,
          marginBottom: 4, lineHeight: 1.6,
          textAlign: (props.align as 'left' | 'center' | 'right') || 'left',
        }}>
          {String(props.content ?? '')}
        </div>
      );
    }

    // ── Button ──
    case 'button': {
      const bp = props as unknown as A2UIButtonProps;
      const variantColors = {
        primary: { bg: T.accent, color: '#fff' },
        secondary: { bg: '#1A3A48', color: T.text },
        danger: { bg: T.danger, color: '#fff' },
        ghost: { bg: 'transparent', color: T.text2 },
      };
      const vc = variantColors[bp.variant || 'primary'];
      return (
        <button
          key={id}
          disabled={bp.disabled}
          onClick={() => onAction?.(id, bp.action || 'click', bp.actionPayload)}
          style={{
            padding: '8px 16px', minHeight: 44,
            background: bp.disabled ? '#444' : vc.bg,
            color: bp.disabled ? '#888' : vc.color,
            border: bp.variant === 'ghost' ? '1px solid rgba(255,255,255,0.1)' : 'none',
            borderRadius: 8, cursor: bp.disabled ? 'not-allowed' : 'pointer',
            fontSize: 14, fontWeight: 600,
            display: 'inline-flex', alignItems: 'center', gap: 6,
            userSelect: 'none', touchAction: 'manipulation',
            opacity: bp.disabled ? 0.5 : 1,
          }}
        >
          {(bp.icon && typeof bp.icon === 'string') && <span>{bp.icon}</span>}
          {bp.label}
        </button>
      );
    }

    // ── Badge ──
    case 'badge': {
      return <A2UIBadge key={id} {...(props as unknown as A2UIBadgeProps)} />;
    }

    // ── Progress ──
    case 'progress': {
      return <A2UIProgress key={id} {...(props as unknown as A2UIProgressProps)} />;
    }

    // ── Divider ──
    case 'divider': {
      return (
        <div key={id} style={{
          height: 1, background: T.cardBorder,
          margin: '10px 0',
        }} />
      );
    }

    // ── Spinner ──
    case 'spinner': {
      return (
        <div key={id} style={{ display: 'flex', justifyContent: 'center', padding: 20 }}>
          <div style={{
            width: 24, height: 24,
            border: '3px solid rgba(255,107,53,0.15)',
            borderTopColor: T.accent,
            borderRadius: '50%',
            animation: 'a2ui-spin 0.6s linear infinite',
          }} />
        </div>
      );
    }

    // ── List ──
    case 'list': {
      const lp = props as unknown as A2UIListProps;
      return (
        <div key={id} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {lp.items.map((item: A2UIListItem) => (
            <div
              key={item.id}
              onClick={() => item.actionId && onAction?.(item.id, 'select', { itemId: item.id })}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '8px 12px', borderRadius: 8,
                background: item.actionId ? 'rgba(255,107,53,0.06)' : 'transparent',
                cursor: item.actionId ? 'pointer' : 'default',
                transition: 'background 100ms',
              }}
            >
              {item.leadingIcon && <span style={{ fontSize: 16 }}>{item.leadingIcon}</span>}
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{item.title}</div>
                {item.subtitle && <div style={{ fontSize: 11, color: T.text2, marginTop: 1 }}>{item.subtitle}</div>}
              </div>
              {item.trailingText && <span style={{ fontSize: 12, color: T.text2 }}>{item.trailingText}</span>}
            </div>
          ))}
        </div>
      );
    }

    // ── Section ──
    case 'section': {
      return (
        <div key={id} style={{ margin: '8px 0' }}>
          {Boolean(props.title) && (
            <div style={{ fontSize: 12, fontWeight: 700, color: T.text2, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
              {String(props.title)}
            </div>
          )}
          {children?.map((child) => renderNode(child, onAction, ctx))}
        </div>
      );
    }

    // ── Actions (button group) ──
    case 'actions': {
      const buttons = (props.buttons as A2UIButtonProps[]) || [];
      return (
        <div key={id} style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
          {buttons.map((btn, i) => (
            <button
              key={`${id}-btn-${i}`}
              disabled={btn.disabled}
              onClick={() => onAction?.(id, btn.action || 'click', btn.actionPayload)}
              style={{
                padding: '8px 16px', minHeight: 44,
                background: btn.variant === 'danger' ? T.danger :
                           btn.variant === 'ghost' ? 'transparent' : T.accent,
                color: btn.variant === 'ghost' ? T.text2 : '#fff',
                border: btn.variant === 'ghost' ? '1px solid rgba(255,255,255,0.1)' : 'none',
                borderRadius: 8, cursor: btn.disabled ? 'not-allowed' : 'pointer',
                fontSize: 14, fontWeight: 600,
                userSelect: 'none', touchAction: 'manipulation',
              }}
            >
              {btn.label}
            </button>
          ))}
        </div>
      );
    }

    // ── Table ──
    case 'table': {
      return <A2UITable key={id} {...(props as unknown as A2UITableProps)} />;
    }

    // ── Chart ──
    case 'chart': {
      return <A2UIChart key={id} {...(props as unknown as A2UIChartProps)} />;
    }

    // ── Input ──
    case 'input': {
      return (
        <input
          key={id}
          type={(props.type as string) || 'text'}
          placeholder={(props.placeholder as string) || ''}
          defaultValue={(props.defaultValue as string) || ''}
          disabled={!!props.disabled}
          style={{
            width: '100%', height: 44,
            padding: '0 12px',
            background: '#1A3A48', border: `1px solid ${T.cardBorder}`,
            borderRadius: 8, color: T.text, fontSize: 14, outline: 'none',
          }}
        />
      );
    }

    // ── Image ──
    case 'image': {
      const imgSrc = String(props.src || '');
      if (!imgSrc) return null;
      return (
        <img
          key={id}
          src={imgSrc}
          alt={String(props.alt || '')}
          style={{ maxWidth: '100%', borderRadius: 8, ...(props.style as Record<string, unknown> || {}) }}
        />
      );
    }

    // ──────────── Sprint 3 S3-01: 6 新组件 ────────────

    // ── Form ──
    case 'form': {
      const fp = props as unknown as A2UIFormProps;
      return <A2UIForm key={id} id={id} formProps={fp} onAction={onAction} />;
    }

    // ── Map ──
    case 'map': {
      const mp = props as unknown as A2UIMapProps;
      return <A2UIMap key={id} id={id} mapProps={mp} onAction={onAction} />;
    }

    // ── Heatmap ──
    case 'heatmap': {
      const hp = props as unknown as A2UIHeatmapProps;
      return <A2UIHeatmap key={id} {...hp} />;
    }

    // ── Timeline ──
    case 'timeline': {
      const tp = props as unknown as A2UITimelineProps;
      return <A2UITimeline key={id} {...tp} ctx={ctx} />;
    }

    // ── Cascader ──
    case 'cascader': {
      const cp = props as unknown as A2UICascaderProps;
      return <A2UICascader key={id} id={id} cascaderProps={cp} onAction={onAction} />;
    }

    // ── Tabs ──
    case 'tabs': {
      const tabsP = props as unknown as A2UITabsProps;
      return <A2UITabs key={id} id={id} tabsProps={tabsP} childrenNodes={children} onAction={onAction} ctx={ctx} />;
    }

    default: {
      console.warn(`[A2UI] Unknown component type: ${type}, node: ${id}`);
      return null;
    }
  }
}

// ─── Sprint 3 S3-01: 6 新组件实现 ─────────────────────────────────────────────

/** Form — Agent 引导填表（白名单 fields 类型，无 raw HTML） */
function A2UIForm({
  id, formProps, onAction,
}: { id: string; formProps: A2UIFormProps; onAction?: A2UIActionCallback }) {
  // 不持久化 form state — Agent submit 时通过 actionPayload 整体传出
  // 这里只读 + 提交时拿当前 DOM value
  const formId = `a2ui-form-${id}`;
  const submit = () => {
    const formEl = document.getElementById(formId) as HTMLFormElement | null;
    if (!formEl || !formProps.submitAction) return;
    const formData = new FormData(formEl);
    const payload: Record<string, unknown> = {};
    for (const field of formProps.fields) {
      payload[field.key] = formData.get(field.key);
    }
    onAction?.(id, formProps.submitAction, payload);
  };
  return (
    <form id={formId} onSubmit={(e) => { e.preventDefault(); submit(); }} style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 12 }}>
      {formProps.fields.map((field) => (
        <label key={field.key} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <span style={{ fontSize: 13, color: T.text2, fontWeight: 600 }}>
            {field.label}{field.required && <span style={{ color: T.danger }}> *</span>}
          </span>
          {field.type === 'select' ? (
            <select name={field.key} required={field.required}
              style={{ height: 44, padding: '0 12px', borderRadius: 8, background: '#1A3A48', border: `1px solid ${T.cardBorder}`, color: T.text, fontSize: 14 }}>
              {(field.options ?? []).map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          ) : field.type === 'textarea' ? (
            <textarea name={field.key} required={field.required} placeholder={field.placeholder}
              rows={3}
              style={{ padding: 10, borderRadius: 8, background: '#1A3A48', border: `1px solid ${T.cardBorder}`, color: T.text, fontSize: 14, resize: 'vertical' }} />
          ) : (
            <input
              type={field.type}
              name={field.key}
              required={field.required}
              placeholder={field.placeholder}
              min={field.min}
              max={field.max}
              style={{ height: 44, padding: '0 12px', borderRadius: 8, background: '#1A3A48', border: `1px solid ${T.cardBorder}`, color: T.text, fontSize: 14 }}
            />
          )}
        </label>
      ))}
      <button type="submit"
        style={{ marginTop: 8, padding: '10px 16px', minHeight: 48, background: T.accent, color: '#fff', border: 'none', borderRadius: 8, fontSize: 15, fontWeight: 700, cursor: 'pointer' }}>
        {formProps.submitLabel ?? '提交'}
      </button>
    </form>
  );
}

/** Map — 标注点地图（无 raw URL；坐标 0-100 百分比） */
function A2UIMap({
  id, mapProps, onAction,
}: { id: string; mapProps: A2UIMapProps; onAction?: A2UIActionCallback }) {
  const w = mapProps.width ?? 320;
  const h = mapProps.height ?? 240;
  const colorMap: Record<string, string> = {
    success: T.success, warning: T.warning, danger: T.danger, info: T.info,
  };
  return (
    <div style={{ position: 'relative', width: w, height: h, background: 'linear-gradient(135deg, #1A3A48, #0F2530)', borderRadius: 10, border: `1px solid ${T.cardBorder}`, overflow: 'hidden' }}>
      {mapProps.markers.map((m) => (
        <button
          key={m.id}
          type="button"
          onClick={() => m.actionId && onAction?.(id, 'select', { markerId: m.id })}
          aria-label={m.label}
          style={{
            position: 'absolute',
            left: `${Math.max(0, Math.min(100, m.x))}%`,
            top: `${Math.max(0, Math.min(100, m.y))}%`,
            transform: 'translate(-50%, -50%)',
            minWidth: 48, minHeight: 48,
            borderRadius: '50%', border: '2px solid rgba(255,255,255,0.6)',
            background: m.color ? colorMap[m.color] : T.accent,
            color: '#fff', fontSize: 12, fontWeight: 700,
            cursor: m.actionId ? 'pointer' : 'default',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 4, lineHeight: 1.1,
          }}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}

/** Heatmap — 二维矩阵热力图（值 clamp 到 0-1） */
function A2UIHeatmap(props: A2UIHeatmapProps) {
  const low = props.gradient?.low ?? 'rgba(15, 110, 86, 0.15)';
  const high = props.gradient?.high ?? T.accent;
  const cellW = 40;
  const cellH = 28;

  function clamp01(v: number): number {
    return Math.max(0, Math.min(1, v));
  }

  function lerp(t: number): string {
    // 简化为 alpha 渐变：低=透明 / 高=不透明 accent
    return `color-mix(in oklab, ${low} ${(1 - t) * 100}%, ${high} ${t * 100}%)`;
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      {props.title && <div style={{ fontSize: 13, fontWeight: 700, color: T.text, marginBottom: 8 }}>{props.title}</div>}
      <table style={{ borderCollapse: 'separate', borderSpacing: 2 }}>
        <thead>
          <tr>
            <th style={{ width: 80 }} />
            {props.colLabels.map((c) => (
              <th key={c} style={{ width: cellW, fontSize: 11, color: T.text2, fontWeight: 500, padding: 2 }}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {props.data.map((row, i) => (
            <tr key={props.rowLabels[i] ?? i}>
              <td style={{ fontSize: 12, color: T.text2, padding: '4px 8px', textAlign: 'right' }}>
                {props.rowLabels[i] ?? `行 ${i + 1}`}
              </td>
              {row.map((value, j) => {
                const v = clamp01(value);
                return (
                  <td key={j} style={{ width: cellW, height: cellH, background: lerp(v), color: v > 0.6 ? '#fff' : T.text2, fontSize: 11, textAlign: 'center', borderRadius: 4 }}>
                    {Math.round(v * 100)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Timeline — 订单时间线（severity 圆点 + ISO 时间） */
function A2UITimeline({ items, limit, ctx }: A2UITimelineProps & { ctx?: A2UIRenderContext }) {
  const showItems = limit ? items.slice(0, limit) : items;
  const sevColor: Record<string, string> = {
    success: T.success, warning: T.warning, danger: T.danger, info: T.info,
  };
  const fmt = ctx?.formatTime ?? ((iso: string) => iso.slice(11, 16));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', position: 'relative', paddingLeft: 24 }}>
      <div style={{ position: 'absolute', left: 8, top: 8, bottom: 8, width: 1, background: T.cardBorder }} />
      {showItems.map((item) => (
        <div key={item.id} style={{ position: 'relative', paddingBottom: 14 }}>
          <div style={{
            position: 'absolute', left: -19, top: 4,
            width: 11, height: 11, borderRadius: '50%',
            background: sevColor[item.severity ?? 'info'] ?? T.info,
            border: `2px solid ${T.bg}`,
          }} />
          <div style={{ fontSize: 11, color: T.text3, marginBottom: 2 }}>{fmt(item.timestamp)}</div>
          <div style={{ fontSize: 13, color: T.text, fontWeight: 600 }}>{item.title}</div>
          {item.description && <div style={{ fontSize: 12, color: T.text2, marginTop: 2 }}>{item.description}</div>}
        </div>
      ))}
    </div>
  );
}

/** Cascader — 多级菜单（深度上限 5，防递归攻击） */
function A2UICascader({
  id, cascaderProps, onAction,
}: { id: string; cascaderProps: A2UICascaderProps; onAction?: A2UIActionCallback }) {
  const MAX_DEPTH = 5;

  function renderColumn(options: A2UICascaderOption[], path: string[], depth: number): ReactNode {
    if (depth >= MAX_DEPTH) {
      console.warn(`[A2UI] Cascader 深度超限 ${MAX_DEPTH}，截断渲染`);
      return null;
    }
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 140, padding: 6, borderRight: `1px solid ${T.cardBorder}` }}>
        {options.map((opt) => {
          const newPath = [...path, opt.value];
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => cascaderProps.changeAction && onAction?.(id, cascaderProps.changeAction, { values: newPath })}
              style={{
                textAlign: 'left', padding: '8px 10px', minHeight: 40,
                background: 'transparent', border: 'none',
                borderRadius: 6, cursor: 'pointer',
                color: T.text, fontSize: 13,
              }}
            >
              {opt.label}
              {opt.children && opt.children.length > 0 && <span style={{ float: 'right', color: T.text3 }}>›</span>}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', overflowX: 'auto', background: T.card, borderRadius: 8, border: `1px solid ${T.cardBorder}` }}>
      {renderColumn(cascaderProps.options, [], 0)}
    </div>
  );
}

/** Tabs — 多视图切换（数量上限 12） */
function A2UITabs({
  id, tabsProps, childrenNodes, onAction, ctx,
}: { id: string; tabsProps: A2UITabsProps; childrenNodes?: A2UINode[]; onAction?: A2UIActionCallback; ctx?: A2UIRenderContext }) {
  const MAX_TABS = 12;
  const tabs = tabsProps.tabs.slice(0, MAX_TABS);
  if (tabs.length < tabsProps.tabs.length) {
    console.warn(`[A2UI] Tabs 数量超限 ${MAX_TABS}，已截断 ${tabsProps.tabs.length - MAX_TABS} 个`);
  }
  const activeKey = tabsProps.activeKey ?? tabs[0]?.key;
  const activeTab = tabs.find((t) => t.key === activeKey);
  const activeContent = activeTab && childrenNodes?.find((n) => n.id === activeTab.contentId);

  return (
    <div>
      <div style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${T.cardBorder}`, padding: 4 }}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            disabled={tab.disabled}
            onClick={() => tabsProps.changeAction && onAction?.(id, tabsProps.changeAction, { key: tab.key })}
            aria-selected={tab.key === activeKey}
            role="tab"
            style={{
              padding: '0 16px', minHeight: 48, minWidth: 48,
              background: tab.key === activeKey ? T.accent : 'transparent',
              color: tab.key === activeKey ? '#fff' : T.text2,
              border: 'none', borderRadius: '6px 6px 0 0',
              fontSize: 14, fontWeight: 600,
              cursor: tab.disabled ? 'not-allowed' : 'pointer',
              opacity: tab.disabled ? 0.4 : 1,
              display: 'flex', alignItems: 'center', gap: 6,
            }}
          >
            {tab.label}
            {tab.badge && tab.badge > 0 && (
              <span style={{ background: T.danger, color: '#fff', borderRadius: 8, padding: '0 6px', fontSize: 11, minWidth: 16, height: 16, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}>
                {tab.badge >= 10 ? '9+' : tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>
      <div style={{ padding: 12 }} role="tabpanel">
        {activeContent ? renderNode(activeContent, onAction, ctx) : (
          <div style={{ color: T.text3, fontSize: 13, padding: 16, textAlign: 'center' }}>无内容</div>
        )}
      </div>
    </div>
  );
}

// ─── 顶层渲染器组件 ──────────────────────────────────────────────────────────────

export function A2UIRenderer({ declaration, onAction, context, loading, error }: A2UIRendererProps) {
  // 动画 keyframe
  const styleEl = (
    <style>{`@keyframes a2ui-spin { to { transform: rotate(360deg); } }`}</style>
  );

  if (loading) {
    return (
      <div style={{ padding: 24, textAlign: 'center' }}>
        {styleEl}
        <div style={{
          width: 28, height: 28, margin: '0 auto 12px',
          border: '3px solid rgba(255,107,53,0.15)',
          borderTopColor: T.accent, borderRadius: '50%',
          animation: 'a2ui-spin 0.6s linear infinite',
        }} />
        <div style={{ fontSize: 13, color: T.text2 }}>Agent 正在生成界面...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{
        padding: 16, borderRadius: 10,
        background: 'rgba(239,68,68,0.08)',
        border: '1px solid rgba(239,68,68,0.2)',
        color: T.danger, fontSize: 13,
      }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>A2UI 渲染失败</div>
        <div>{error}</div>
      </div>
    );
  }

  if (!declaration?.surface) {
    return null;
  }

  return (
    <div style={{ fontFamily: 'Noto Sans SC, sans-serif' }}>
      {styleEl}
      {renderNode(declaration.surface, onAction, context)}
    </div>
  );
}

// ─── 工具：快速创建 A2UI 声明 ────────────────────────────────────────────────────

/** 从 Agent 返回结果中提取/构造 A2UI 声明 */
export function parseA2UIFromAgent(data: Record<string, unknown> | unknown): A2UIDeclaration | null {
  if (!data || typeof data !== 'object') return null;
  const d = data as Record<string, unknown>;

  // 如果 Agent 直接返回了 surface，直接使用
  if (d.surface && typeof d.surface === 'object') {
    return {
      version: (d.version as string) || '0.8',
      surface: d.surface as A2UINode,
      metadata: d.metadata as A2UIDeclaration['metadata'],
    };
  }

  // 如果 Agent 返回的是业务数据，自动包装成 Card
  const alerts = d.alerts as unknown[] | undefined;
  const alert = d.alert || alerts?.[0] || d.recommendation || d.result || null;
  if (alert && typeof alert === 'object') {
    const a = alert as Record<string, unknown>;
    const severity = (a.severity as string) === 'critical' ? 'critical' :
                     (a.severity as string) === 'warning' ? 'warning' : 'info';
    return {
      version: '0.8',
      surface: {
        id: 'agent-card',
        type: 'card',
        props: {
          title: (a.title as string) || 'Agent 返回',
          severity,
        },
        children: [
          {
            id: 'agent-msg',
            type: 'text',
            props: { content: (a.message as string) || (a.reasoning as string) || JSON.stringify(a, null, 2) },
          },
        ],
      },
      metadata: {
        agentId: (a.agent_id as string),
        confidence: (a.confidence as number),
        reasoning: (a.reasoning as string),
      },
    };
  }

  return null;
}
