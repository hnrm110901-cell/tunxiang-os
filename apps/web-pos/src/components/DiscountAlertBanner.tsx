/**
 * DiscountAlertBanner — 折扣守护预警横幅
 *
 * 固定在 POS 屏幕顶部（position: fixed），最新预警从顶部滑入。
 * 每次只显示最高优先级的一条；其余排队，当前条消失后自动展示下一条。
 *
 * 风险等级视觉规范（来自 Design Token）：
 *   critical → danger 红色背景 (#A32D2D) + 震动动画
 *   high     → warning 橙色背景 (#BA7517)
 *   medium   → 黄色背景 (#9A7D00，高对比变体)
 *
 * 触控规范（Store POS 终端）：
 *   - 最小字体 16px（实际最小 18px）
 *   - 「已知晓」按钮 ≥ 48×48px
 *   - 按钮按下有 scale(0.97) 反馈
 *   - 自动 15 秒后消失（每次新 alert 重置计时）
 */

import { useEffect, useRef, useState } from 'react';
import type { DiscountAlert } from '../hooks/usePOSAlerts';
import { formatPrice } from '@tx-ds/utils';

// ─── 常量 ───

const AUTO_DISMISS_MS = 15_000;

// ─── 工具函数 ───

/** @deprecated Use formatPrice from @tx-ds/utils */
/** 将分为元，保留整数 */
const fenToYuan = (fen: number): string =>
  (fen / 100).toFixed(0);

/** 超出阈值的百分点，取整 */
const excessPoints = (rate: number, threshold: number): string =>
  ((rate - threshold) * 100).toFixed(1);

/** 折扣率转百分比字符串 */
const toPercent = (rate: number): string =>
  (rate * 100).toFixed(1);

// ─── 样式配置 ───

interface LevelStyle {
  background: string;
  border: string;
  text: string;
  label: string;
  shake: boolean;
}

const LEVEL_STYLES: Record<string, LevelStyle> = {
  critical: {
    background: '#A32D2D',
    border: '#7A2020',
    text: '#FFFFFF',
    label: '严重违规',
    shake: true,
  },
  high: {
    background: '#BA7517',
    border: '#8A5510',
    text: '#FFFFFF',
    label: '高风险',
    shake: false,
  },
  medium: {
    background: '#9A7D00',
    border: '#7A6400',
    text: '#FFFFFF',
    label: '中风险',
    shake: false,
  },
};

const fallbackStyle: LevelStyle = {
  background: '#5F5E5A',
  border: '#4A4940',
  text: '#FFFFFF',
  label: '预警',
  shake: false,
};

// ─── CSS-in-JS 动画（keyframes 注入一次）───

const KEYFRAMES_ID = 'tx-discount-alert-keyframes';

function ensureKeyframes(): void {
  if (document.getElementById(KEYFRAMES_ID)) return;
  const style = document.createElement('style');
  style.id = KEYFRAMES_ID;
  style.textContent = `
    @keyframes tx-slide-in {
      from { transform: translateY(-100%); opacity: 0; }
      to   { transform: translateY(0);    opacity: 1; }
    }
    @keyframes tx-shake {
      0%,100% { transform: translateX(0); }
      15%     { transform: translateX(-6px); }
      30%     { transform: translateX(6px); }
      45%     { transform: translateX(-5px); }
      60%     { transform: translateX(5px); }
      75%     { transform: translateX(-3px); }
      90%     { transform: translateX(3px); }
    }
    @keyframes tx-pulse-bg {
      0%,100% { opacity: 1; }
      50%     { opacity: 0.85; }
    }
  `;
  document.head.appendChild(style);
}

// ─── Props ───

interface DiscountAlertBannerProps {
  alerts: DiscountAlert[];
  onDismiss: (alertId: string) => void;
}

// ─── 组件 ───

export function DiscountAlertBanner({
  alerts,
  onDismiss,
}: DiscountAlertBannerProps) {
  ensureKeyframes();

  // 当前展示的 alert（取队列第一条）
  const current = alerts[0] ?? null;

  // 控制横幅是否可见（用于滑出动画）
  const [visible, setVisible] = useState(false);
  // 追踪按钮按压状态（触控反馈）
  const [pressing, setPressing] = useState(false);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevAlertIdRef = useRef<string | null>(null);

  // 每次 current 变化时重置可见状态和自动消失计时器
  useEffect(() => {
    if (!current) {
      setVisible(false);
      return;
    }

    // 新 alert 进来：立即显示
    if (current.alert_id !== prevAlertIdRef.current) {
      prevAlertIdRef.current = current.alert_id;
      setVisible(true);

      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        handleDismiss(current.alert_id);
      }, AUTO_DISMISS_MS);
    }

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [current?.alert_id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!current || !visible) return null;

  const levelStyle = LEVEL_STYLES[current.risk_level] ?? fallbackStyle;
  const excess = parseFloat(excessPoints(current.discount_rate, current.threshold));

  function handleDismiss(alertId: string): void {
    setVisible(false);
    // 给滑出动画留时间（250ms）后再真正从列表移除
    setTimeout(() => onDismiss(alertId), 250);
  }

  return (
    <div
      role="alert"
      aria-live="assertive"
      aria-atomic="true"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        background: levelStyle.background,
        borderBottom: `3px solid ${levelStyle.border}`,
        color: levelStyle.text,
        padding: '0 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
        minHeight: 64,
        boxShadow: '0 4px 12px rgba(0,0,0,0.25)',
        animation: current.risk_level === 'critical'
          ? 'tx-slide-in 280ms ease-out, tx-shake 600ms ease-in-out 280ms, tx-pulse-bg 1.5s ease-in-out 880ms infinite'
          : 'tx-slide-in 280ms ease-out',
        transition: 'transform 250ms ease-in, opacity 250ms ease-in',
        fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", "Microsoft YaHei", sans-serif',
      }}
    >
      {/* ── 左侧：风险标签 ── */}
      <div
        style={{
          background: 'rgba(0,0,0,0.25)',
          borderRadius: 8,
          padding: '4px 10px',
          fontSize: 16,
          fontWeight: 700,
          letterSpacing: '0.03em',
          whiteSpace: 'nowrap',
          flexShrink: 0,
        }}
      >
        {levelStyle.label}
      </div>

      {/* ── 中间：预警详情 ── */}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
        }}
      >
        {/* 主信息行 */}
        <div
          style={{
            fontSize: 18,
            fontWeight: 600,
            lineHeight: 1.4,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          <span style={{ opacity: 0.9 }}>【折扣守护】</span>
          &nbsp;
          <strong>{current.employee_name}</strong>
          &nbsp;打折&nbsp;
          <strong>{toPercent(current.discount_rate)}%</strong>
          {excess > 0 && (
            <span
              style={{
                marginLeft: 8,
                background: 'rgba(255,255,255,0.2)',
                borderRadius: 6,
                padding: '1px 6px',
                fontSize: 16,
              }}
            >
              超出阈值 {excess.toFixed(1)} 个百分点
            </span>
          )}
        </div>

        {/* 次信息行 */}
        <div
          style={{
            fontSize: 16,
            opacity: 0.85,
            lineHeight: 1.3,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          订单 {current.order_id}
          &nbsp;·&nbsp;
          折扣金额 ¥{fenToYuan(current.amount_fen)} 元
          {current.message && (
            <span>&nbsp;·&nbsp;{current.message}</span>
          )}
        </div>
      </div>

      {/* ── 右侧：已知晓按钮 ── */}
      <button
        type="button"
        aria-label="已知晓，关闭此预警"
        onPointerDown={() => setPressing(true)}
        onPointerUp={() => {
          setPressing(false);
          handleDismiss(current.alert_id);
        }}
        onPointerLeave={() => setPressing(false)}
        style={{
          flexShrink: 0,
          minWidth: 80,
          minHeight: 48,
          padding: '0 20px',
          background: 'rgba(255,255,255,0.18)',
          border: '1.5px solid rgba(255,255,255,0.5)',
          borderRadius: 12,
          color: '#FFFFFF',
          fontSize: 18,
          fontWeight: 600,
          cursor: 'pointer',
          // 触控按压反馈
          transform: pressing ? 'scale(0.97)' : 'scale(1)',
          transition: 'transform 200ms ease, background 150ms ease',
          // 防止触控设备文字选中
          userSelect: 'none',
          WebkitUserSelect: 'none',
          fontFamily: 'inherit',
        }}
      >
        已知晓
      </button>
    </div>
  );
}
