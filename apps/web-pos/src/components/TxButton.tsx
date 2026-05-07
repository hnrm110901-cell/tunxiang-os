/**
 * TxButton — POS 触控按钮组件
 *
 * 内置 touch feedback（scale(0.97) 按压动效），
 * 确保最小触控区域 ≥44px，暗色主题一致。
 *
 * 用法:
 *   <TxButton onClick={handleClick}>按钮文字</TxButton>
 *   <TxButton variant="primary" disabled={true}>禁用</TxButton>
 *   <TxButton variant="danger" block>确认反结</TxButton>
 *
 * variant: primary | secondary | danger | ghost | success | warning
 * size:    sm(40px) | md(48px) | lg(56px) | xl(72px)
 */
import type { ReactNode, CSSProperties } from 'react';
import { useTouchFeedback } from '../hooks/useTouchFeedback';
import { txColors } from '@tx/tokens';

// ─── Types ──────────────────────────────────────────────────────────────────────

type TxVariant = 'primary' | 'secondary' | 'danger' | 'ghost' | 'success' | 'warning';
type TxSize = 'sm' | 'md' | 'lg' | 'xl';

interface TxButtonProps {
  children: ReactNode;
  onClick?: () => void;
  variant?: TxVariant;
  size?: TxSize;
  disabled?: boolean;
  block?: boolean;
  style?: CSSProperties;
  type?: 'button' | 'submit';
  title?: string;
}

// ─── Style maps ─────────────────────────────────────────────────────────────────

const VARIANT_BG: Record<TxVariant, string> = {
  primary: txColors.primary,
  secondary: '#1A3A48',
  danger: txColors.danger,
  ghost: 'transparent',
  success: txColors.success,
  warning: txColors.warning,
};

const VARIANT_COLOR: Record<TxVariant, string> = {
  primary: '#fff',
  secondary: '#E0E0E0',
  danger: '#fff',
  ghost: 'rgba(255,255,255,0.55)',
  success: '#fff',
  warning: '#fff',
};

const VARIANT_BORDER: Record<TxVariant, string> = {
  primary: 'none',
  secondary: 'none',
  danger: 'none',
  ghost: '1px solid rgba(255,255,255,0.1)',
  success: 'none',
  warning: 'none',
};

const SIZE_HEIGHT: Record<TxSize, number> = {
  sm: 40,
  md: 48,
  lg: 56,
  xl: 72,
};

const SIZE_FONT: Record<TxSize, number> = {
  sm: 13,
  md: 16,
  lg: 18,
  xl: 20,
};

const SIZE_PAD: Record<TxSize, number> = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
};

// ─── Component ──────────────────────────────────────────────────────────────────

export function TxButton({
  children,
  onClick,
  variant = 'primary',
  size = 'md',
  disabled = false,
  block = false,
  style,
  type = 'button',
  title,
}: TxButtonProps) {
  const tf = useTouchFeedback();
  const h = SIZE_HEIGHT[size];

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      {...tf.handlers}
      style={{
        padding: `${SIZE_PAD[size]}px ${size === 'xl' ? 20 : 16}px`,
        minHeight: h,
        width: block ? '100%' : undefined,
        background: disabled ? '#444' : VARIANT_BG[variant],
        color: disabled ? '#888' : VARIANT_COLOR[variant],
        border: VARIANT_BORDER[variant],
        borderRadius: variant === 'ghost' ? 6 : 10,
        cursor: disabled ? 'not-allowed' : 'pointer',
        fontSize: SIZE_FONT[size],
        fontWeight: variant === 'ghost' ? 500 : variant === 'primary' ? 700 : 600,
        fontFamily: 'inherit',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 6,
        opacity: disabled ? 0.5 : 1,
        ...tf.style,
        ...style,
      }}
    >
      {children}
    </button>
  );
}
