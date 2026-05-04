/**
 * useTouchFeedback — 触控按压反馈动画 Hook
 *
 * pointerDown → scale(0.97) + opacity(0.85)
 * pointerUp / Leave / Cancel → scale(1) + opacity(1)
 * CSS transition: 150ms ease
 *
 * 参考: DiscountAlertBanner.tsx 已有的 scale(0.97) 模式
 *
 * 使用:
 *   const { style: tf, handlers } = useTouchFeedback();
 *   <button style={{ ...existingStyle, ...tf }} {...handlers} onClick={...}>
 */
import { useState, useCallback } from 'react';

interface TouchFeedbackOptions {
  scale?: number;
  opacity?: number;
  durationMs?: number;
}

interface TouchFeedbackReturn {
  style: React.CSSProperties;
  handlers: {
    onPointerDown: (e: React.PointerEvent) => void;
    onPointerUp: (e: React.PointerEvent) => void;
    onPointerLeave: (e: React.PointerEvent) => void;
    onPointerCancel: (e: React.PointerEvent) => void;
  };
}

export function useTouchFeedback(options?: TouchFeedbackOptions): TouchFeedbackReturn {
  const [pressed, setPressed] = useState(false);
  const {
    scale = 0.97,
    opacity = 0.85,
    durationMs = 150,
  } = options ?? {};

  const style: React.CSSProperties = {
    transform: pressed ? `scale(${scale})` : 'scale(1)',
    opacity: pressed ? opacity : 1,
    transition: `transform ${durationMs}ms ease, opacity ${durationMs}ms ease`,
    userSelect: 'none',
    WebkitUserSelect: 'none',
    touchAction: 'manipulation',
  };

  const handlers = {
    onPointerDown: useCallback(() => setPressed(true), []),
    onPointerUp: useCallback(() => setPressed(false), []),
    onPointerLeave: useCallback(() => setPressed(false), []),
    onPointerCancel: useCallback(() => setPressed(false), []),
  };

  return { style, handlers };
}
