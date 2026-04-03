/**
 * LiveSeafoodOrderSheet — 活鲜称重点单底部弹层
 *
 * 业务流程：
 *   1. 显示活鲜菜品信息（品种名/价格单位/鱼缸位置）
 *   2. 两种模式切换：立即称重（WebSocket实时显示）/ 手动输入（TXNumpad）
 *   3. 实时计算金额（重量 × 单价）
 *   4. 显示最小点单量提示（0.5斤起）
 *   5. 确认按钮 → POST /api/v1/menu/live-seafood/weigh
 *   6. 成功后通过 onConfirm 回调加入订单明细
 *
 * Store 触控规范：
 *   - 所有可点击元素 ≥ 48×48px
 *   - 确认按钮 72px 高（TXButton large 变体）
 *   - 最小字体 16px（严格）
 *   - 弹层从底部滑出（translateY 300ms）
 *   - 按钮按下 scale(0.97) + 200ms transition
 *   - 禁止 Select 下拉 / hover 反馈
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import ReactDOM from 'react-dom';
import { getMacMiniUrl } from '../bridge/TXBridge';

// ─── Design Tokens ───────────────────────────────────────────────────────────

const T = {
  primary:    'var(--tx-primary, #FF6B35)',
  primaryDark:'#E55A28',
  success:    'var(--tx-success, #0F6E56)',
  danger:     'var(--tx-danger, #A32D2D)',
  warning:    'var(--tx-warning, #BA7517)',
  text1:      'var(--tx-text-1, #2C2C2A)',
  text2:      'var(--tx-text-2, #5F5E5A)',
  bg1:        'var(--tx-bg-1, #FFFFFF)',
  bg2:        'var(--tx-bg-2, #F8F7F5)',
  border:     '#E8E6E1',
  radius:     '12px',
  tapMin:     48,
  tapRec:     56,
  tapLg:      72,
} as const;

// ─── 动画样式注入（一次性） ────────────────────────────────────────────────────

const KEYFRAMES_ID = 'tx-live-seafood-kf';
function ensureKeyframes(): void {
  if (document.getElementById(KEYFRAMES_ID)) return;
  const s = document.createElement('style');
  s.id = KEYFRAMES_ID;
  s.textContent = `
    @keyframes tx-sheet-in  { from { transform: translateY(100%); } to { transform: translateY(0); } }
    @keyframes tx-sheet-out { from { transform: translateY(0); }    to { transform: translateY(100%); } }
    @keyframes tx-weight-pulse { 0%,100%{opacity:1} 50%{opacity:0.7} }
  `;
  document.head.appendChild(s);
}

// ─── 辅助函数 ─────────────────────────────────────────────────────────────────

const fen2yuan = (fen: number): string => `¥${(fen / 100).toFixed(2)}`;

function weightUnitLabel(unit: string): string {
  const map: Record<string, string> = { jin: '斤', liang: '两', kg: 'kg', g: 'g' };
  return map[unit] ?? unit;
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface LiveSeafoodDish {
  id: string;
  name: string;
  pricingMethod: 'weight' | 'count';
  pricePerUnitFen: number;
  weightUnit: 'jin' | 'liang' | 'kg' | 'g';
  displayUnit: string;
  minOrderQty: number;
  tankZoneName?: string;
}

export interface LiveSeafoodOrderSheetProps {
  visible: boolean;
  dish: LiveSeafoodDish;
  storeId: string;
  orderId?: string;
  onConfirm: (weighRecordId: string, qty: number, amountFen: number) => void;
  onClose: () => void;
}

// ─── 内联TXButton ─────────────────────────────────────────────────────────────

type TXButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost';
interface TXButtonProps {
  variant?: TXButtonVariant;
  /** normal=56px, large=72px */
  large?: boolean;
  fullWidth?: boolean;
  disabled?: boolean;
  loading?: boolean;
  children: React.ReactNode;
  onPress: () => void;
  style?: React.CSSProperties;
}

function TXButton({ variant = 'primary', large = false, fullWidth = false, disabled = false, loading = false, children, onPress, style }: TXButtonProps) {
  const [pressing, setPressing] = useState(false);

  const bgMap: Record<TXButtonVariant, string> = {
    primary:   T.primary,
    secondary: T.bg2,
    danger:    T.danger,
    ghost:     'transparent',
  };
  const colorMap: Record<TXButtonVariant, string> = {
    primary:   '#FFFFFF',
    secondary: T.text1,
    danger:    '#FFFFFF',
    ghost:     T.primary,
  };
  const borderMap: Record<TXButtonVariant, string> = {
    primary:   'none',
    secondary: `1.5px solid ${T.border}`,
    danger:    'none',
    ghost:     `1.5px solid ${T.primary}`,
  };

  return (
    <button
      type="button"
      disabled={disabled || loading}
      onPointerDown={() => setPressing(true)}
      onPointerUp={() => { setPressing(false); if (!disabled && !loading) onPress(); }}
      onPointerLeave={() => setPressing(false)}
      style={{
        height: large ? T.tapLg : T.tapRec,
        width: fullWidth ? '100%' : undefined,
        minWidth: T.tapMin,
        padding: '0 24px',
        background: disabled ? '#E8E6E1' : bgMap[variant],
        color: disabled ? T.text2 : colorMap[variant],
        border: disabled ? 'none' : borderMap[variant],
        borderRadius: T.radius,
        fontSize: 18,
        fontWeight: 600,
        fontFamily: 'inherit',
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        transform: pressing && !disabled ? 'scale(0.97)' : 'scale(1)',
        transition: 'transform 200ms ease, background 150ms ease',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        opacity: disabled ? 0.5 : 1,
        boxShadow: variant === 'primary' && !disabled ? '0 4px 12px rgba(255,107,53,0.3)' : undefined,
        ...style,
      }}
    >
      {loading ? '处理中...' : children}
    </button>
  );
}

// ─── 内联TXNumpad ─────────────────────────────────────────────────────────────

interface TXNumpadProps {
  value: string;
  onChange: (v: string) => void;
  onConfirm: (v: number) => void;
  allowDecimal?: boolean;
  maxValue?: number;
}

function TXNumpad({ value, onChange, onConfirm, allowDecimal = true, maxValue }: TXNumpadProps) {
  const [pressKey, setPressKey] = useState<string | null>(null);

  const handleKey = (key: string) => {
    if (key === 'del') {
      onChange(value.slice(0, -1));
      return;
    }
    if (key === '.' && (!allowDecimal || value.includes('.'))) return;
    if (key === '.' && value === '') { onChange('0.'); return; }

    const next = value + key;
    // 最多小数点后2位
    const dotIdx = next.indexOf('.');
    if (dotIdx !== -1 && next.length - dotIdx > 3) return;

    const num = parseFloat(next);
    if (maxValue !== undefined && !isNaN(num) && num > maxValue) return;
    onChange(next);
  };

  const keys = ['7','8','9','4','5','6','1','2','3','.','0','del'];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
      {keys.map((k) => {
        const isConfirm = false;
        const isDel = k === 'del';
        return (
          <button
            key={k}
            type="button"
            onPointerDown={() => setPressKey(k)}
            onPointerUp={() => { setPressKey(null); handleKey(k); }}
            onPointerLeave={() => setPressKey(null)}
            style={{
              height: T.tapLg,
              border: `1.5px solid ${T.border}`,
              borderRadius: 8,
              background: pressKey === k ? T.bg2 : T.bg1,
              color: isDel ? T.danger : T.text1,
              fontSize: isDel ? 20 : 32,
              fontWeight: 600,
              fontFamily: 'inherit',
              cursor: 'pointer',
              transform: pressKey === k ? 'scale(0.97)' : 'scale(1)',
              transition: 'transform 200ms ease, background 150ms ease',
              userSelect: 'none',
              WebkitUserSelect: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            {isDel ? '⌫' : k}
          </button>
        );
      })}
    </div>
  );
}

// ─── 主组件 ───────────────────────────────────────────────────────────────────

export function LiveSeafoodOrderSheet({
  visible,
  dish,
  storeId,
  orderId,
  onConfirm,
  onClose,
}: LiveSeafoodOrderSheetProps) {
  ensureKeyframes();

  type Mode = 'scale' | 'manual';
  const [mode, setMode] = useState<Mode>('scale');
  const [weight, setWeight] = useState<number>(0);
  const [manualInput, setManualInput] = useState<string>('');
  const [wsStatus, setWsStatus] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [closing, setClosing] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // 当前有效重量
  const effectiveWeight = mode === 'manual'
    ? (manualInput === '' ? 0 : parseFloat(manualInput) || 0)
    : weight;

  // 金额（分）
  const amountFen = Math.round(effectiveWeight * dish.pricePerUnitFen);

  // 是否满足最小点单量
  const meetsMinQty = effectiveWeight >= dish.minOrderQty;

  // ── WebSocket 管理 ──────────────────────────────────────────────────────────

  const connectScale = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    const macHost = getMacMiniUrl().replace(/^https?:\/\//, '');
    const wsUrl = `ws://${macHost}/ws/scale`;
    setWsStatus('connecting');

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => setWsStatus('connected');
    ws.onmessage = (e: MessageEvent) => {
      try {
        const parsed: { weight: number } = JSON.parse(e.data as string);
        setWeight(parsed.weight);
      } catch {
        // 忽略无法解析的消息
      }
    };
    ws.onerror = () => setWsStatus('disconnected');
    ws.onclose = () => setWsStatus('disconnected');
  }, []);

  const disconnectScale = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setWsStatus('disconnected');
    setWeight(0);
  }, []);

  // 弹层显示时自动连接秤
  useEffect(() => {
    if (visible && mode === 'scale') {
      connectScale();
    } else {
      disconnectScale();
    }
    return () => disconnectScale();
  }, [visible, mode, connectScale, disconnectScale]);

  // 弹层关闭时重置状态
  useEffect(() => {
    if (!visible) {
      setManualInput('');
      setWeight(0);
      setMode('scale');
      setError(null);
      setSubmitting(false);
      setClosing(false);
    }
  }, [visible]);

  // ── 提交 ────────────────────────────────────────────────────────────────────

  const handleConfirm = async () => {
    if (!meetsMinQty || effectiveWeight <= 0 || submitting) return;
    setSubmitting(true);
    setError(null);

    try {
      const apiBase = getMacMiniUrl();
      const tenantId = import.meta.env.VITE_TENANT_ID as string || '';

      const resp = await fetch(`${apiBase}/api/v1/menu/live-seafood/weigh`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(tenantId ? { 'X-Tenant-ID': tenantId } : {}),
        },
        body: JSON.stringify({
          store_id:            storeId,
          dish_id:             dish.id,
          weighed_qty:         effectiveWeight,
          weight_unit:         dish.weightUnit,
          price_per_unit_fen:  dish.pricePerUnitFen,
          ...(orderId ? { order_id: orderId } : {}),
        }),
      });

      const json: { ok: boolean; data: { weigh_record_id: string }; error?: { message: string } } = await resp.json();

      if (!json.ok) {
        throw new Error(json.error?.message ?? '称重记录创建失败');
      }

      onConfirm(json.data.weigh_record_id, effectiveWeight, amountFen);
      handleClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '网络错误，请重试');
    } finally {
      setSubmitting(false);
    }
  };

  // ── 关闭动画 ─────────────────────────────────────────────────────────────────

  const handleClose = () => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 300);
  };

  if (!visible && !closing) return null;

  const unitLabel = weightUnitLabel(dish.weightUnit);

  // ── 渲染 ─────────────────────────────────────────────────────────────────────

  return ReactDOM.createPortal(
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'flex-end',
      }}
    >
      {/* 遮罩 */}
      <div
        role="presentation"
        onClick={handleClose}
        style={{
          position: 'absolute',
          inset: 0,
          background: 'rgba(44,44,42,0.55)',
          backdropFilter: 'blur(2px)',
          WebkitBackdropFilter: 'blur(2px)',
        }}
      />

      {/* 弹层主体 */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${dish.name} 称重点单`}
        style={{
          position: 'relative',
          background: T.bg1,
          borderRadius: '20px 20px 0 0',
          padding: '0 0 env(safe-area-inset-bottom, 16px)',
          boxShadow: '0 -8px 32px rgba(0,0,0,0.18)',
          maxHeight: '80vh',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
          animation: `${closing ? 'tx-sheet-out' : 'tx-sheet-in'} 300ms ease-out both`,
          fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
        }}
      >
        {/* 拖拽指示条 */}
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 12, paddingBottom: 4 }}>
          <div style={{ width: 40, height: 4, borderRadius: 2, background: T.border }} />
        </div>

        {/* 顶部信息区 */}
        <div style={{ padding: '12px 20px 16px', borderBottom: `1px solid ${T.border}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div style={{ fontSize: 22, fontWeight: 700, color: T.text1, lineHeight: 1.3 }}>
                {dish.name}
              </div>
              {dish.tankZoneName && (
                <div style={{ fontSize: 16, color: T.text2, marginTop: 4 }}>
                  鱼缸位置：{dish.tankZoneName}
                </div>
              )}
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: T.primary }}>
                ¥{(dish.pricePerUnitFen / 100).toFixed(0)}/{dish.displayUnit}
              </div>
              <div style={{ fontSize: 16, color: T.warning, marginTop: 2 }}>
                {dish.minOrderQty}{unitLabel}起
              </div>
            </div>
          </div>
        </div>

        {/* 滚动区域 */}
        <div style={{ flex: 1, overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>

          {/* 模式切换 */}
          <div style={{ display: 'flex', gap: 12, padding: '16px 20px' }}>
            {(['scale', 'manual'] as Mode[]).map((m) => {
              const labels: Record<Mode, string> = { scale: '⚖ 立即称重', manual: '✏ 手动输入' };
              const active = mode === m;
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  style={{
                    flex: 1,
                    height: T.tapRec,
                    border: active ? `2px solid ${T.primary}` : `1.5px solid ${T.border}`,
                    borderRadius: T.radius,
                    background: active ? 'rgba(255,107,53,0.08)' : T.bg1,
                    color: active ? T.primary : T.text2,
                    fontSize: 17,
                    fontWeight: active ? 700 : 400,
                    fontFamily: 'inherit',
                    cursor: 'pointer',
                    transition: 'all 200ms ease',
                    userSelect: 'none',
                    WebkitUserSelect: 'none',
                  }}
                >
                  {labels[m]}
                </button>
              );
            })}
          </div>

          {/* 称重模式 */}
          {mode === 'scale' && (
            <div style={{ padding: '0 20px 16px' }}>
              {/* 秤连接状态 */}
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                marginBottom: 16,
                padding: '10px 16px',
                borderRadius: 10,
                background: wsStatus === 'connected' ? 'rgba(15,110,86,0.08)' : 'rgba(186,117,23,0.08)',
                border: `1px solid ${wsStatus === 'connected' ? T.success : T.warning}`,
              }}>
                <div style={{
                  width: 10,
                  height: 10,
                  borderRadius: '50%',
                  background: wsStatus === 'connected' ? T.success : wsStatus === 'connecting' ? T.warning : '#B4B2A9',
                  animation: wsStatus === 'connecting' ? 'tx-weight-pulse 1s infinite' : undefined,
                }} />
                <span style={{ fontSize: 16, color: T.text2 }}>
                  {wsStatus === 'connected'   ? '电子秤已连接' :
                   wsStatus === 'connecting'  ? '正在连接电子秤...' :
                                               '电子秤未连接'}
                </span>
                {wsStatus === 'disconnected' && (
                  <button
                    type="button"
                    onClick={connectScale}
                    style={{
                      marginLeft: 'auto',
                      minHeight: T.tapMin,
                      minWidth: T.tapMin,
                      padding: '0 16px',
                      border: `1px solid ${T.primary}`,
                      borderRadius: 8,
                      background: 'transparent',
                      color: T.primary,
                      fontSize: 16,
                      fontFamily: 'inherit',
                      cursor: 'pointer',
                    }}
                  >
                    重连
                  </button>
                )}
              </div>

              {/* 重量显示 */}
              <div style={{
                textAlign: 'center',
                padding: '24px 0',
                borderRadius: T.radius,
                background: T.bg2,
                marginBottom: 8,
              }}>
                <div style={{
                  fontSize: 56,
                  fontWeight: 700,
                  color: weight > 0 ? T.text1 : '#B4B2A9',
                  lineHeight: 1.1,
                  fontVariantNumeric: 'tabular-nums',
                  animation: wsStatus === 'connected' && weight > 0 ? 'tx-weight-pulse 0.3s ease-out' : undefined,
                }}>
                  {weight > 0 ? weight.toFixed(2) : '0.00'}
                  <span style={{ fontSize: 24, fontWeight: 400, color: T.text2, marginLeft: 8 }}>
                    {unitLabel}
                  </span>
                </div>
                <div style={{ fontSize: 16, color: T.text2, marginTop: 8 }}>
                  {wsStatus === 'connected' ? '实时读数' : '请放置食材'}
                </div>
              </div>
            </div>
          )}

          {/* 手动输入模式 */}
          {mode === 'manual' && (
            <div style={{ padding: '0 20px 16px' }}>
              {/* 数值显示 */}
              <div style={{
                textAlign: 'center',
                padding: '16px 0 12px',
                borderRadius: T.radius,
                background: T.bg2,
                marginBottom: 16,
              }}>
                <div style={{
                  fontSize: 48,
                  fontWeight: 700,
                  color: manualInput ? T.text1 : '#B4B2A9',
                  lineHeight: 1.1,
                  fontVariantNumeric: 'tabular-nums',
                  minHeight: 60,
                }}>
                  {manualInput || '0'}
                  <span style={{ fontSize: 22, fontWeight: 400, color: T.text2, marginLeft: 8 }}>
                    {unitLabel}
                  </span>
                </div>
              </div>

              {/* 数字键盘 */}
              <TXNumpad
                value={manualInput}
                onChange={setManualInput}
                onConfirm={(v) => { setManualInput(String(v)); }}
                allowDecimal={true}
                maxValue={999}
              />
            </div>
          )}

          {/* 金额预览 */}
          <div style={{
            margin: '0 20px 16px',
            padding: '14px 20px',
            borderRadius: T.radius,
            background: effectiveWeight > 0 ? 'rgba(255,107,53,0.06)' : T.bg2,
            border: `1px solid ${effectiveWeight > 0 ? 'rgba(255,107,53,0.3)' : T.border}`,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}>
            <span style={{ fontSize: 18, color: T.text2 }}>
              {effectiveWeight > 0
                ? `${effectiveWeight.toFixed(2)}${unitLabel} × ¥${(dish.pricePerUnitFen / 100).toFixed(0)}/${unitLabel}`
                : '待称重'}
            </span>
            <span style={{ fontSize: 24, fontWeight: 700, color: effectiveWeight > 0 ? T.primary : '#B4B2A9' }}>
              {effectiveWeight > 0 ? fen2yuan(amountFen) : '¥0.00'}
            </span>
          </div>

          {/* 最小点单量提示 */}
          {effectiveWeight > 0 && !meetsMinQty && (
            <div style={{
              margin: '0 20px 12px',
              padding: '10px 16px',
              borderRadius: 10,
              background: 'rgba(163,45,45,0.08)',
              border: `1px solid ${T.danger}`,
              fontSize: 16,
              color: T.danger,
            }}>
              最低点单量 {dish.minOrderQty}{unitLabel}，当前 {effectiveWeight.toFixed(2)}{unitLabel}
            </div>
          )}

          {/* 错误提示 */}
          {error && (
            <div style={{
              margin: '0 20px 12px',
              padding: '10px 16px',
              borderRadius: 10,
              background: 'rgba(163,45,45,0.08)',
              border: `1px solid ${T.danger}`,
              fontSize: 16,
              color: T.danger,
            }}>
              {error}
            </div>
          )}
        </div>

        {/* 底部操作区 */}
        <div style={{
          padding: '16px 20px',
          borderTop: `1px solid ${T.border}`,
          display: 'flex',
          gap: 12,
        }}>
          <TXButton
            variant="ghost"
            onPress={handleClose}
            style={{ minWidth: 100 }}
          >
            取消
          </TXButton>
          <TXButton
            variant="primary"
            large={true}
            fullWidth={true}
            disabled={!meetsMinQty || effectiveWeight <= 0}
            loading={submitting}
            onPress={handleConfirm}
          >
            确认点单 {effectiveWeight > 0 && meetsMinQty ? fen2yuan(amountFen) : ''}
          </TXButton>
        </div>
      </div>
    </div>,
    document.body,
  );
}
