import { useCallback, useRef } from 'react';

interface LongPressHandlers {
  onMouseDown: (e: React.MouseEvent) => void;
  onMouseUp: (e: React.MouseEvent) => void;
  onMouseLeave: (e: React.MouseEvent) => void;
  onTouchStart: (e: React.TouchEvent) => void;
  onTouchEnd: (e: React.TouchEvent) => void;
  onTouchMove: (e: React.TouchEvent) => void;
}

/**
 * 长按检测 Hook
 * 同时支持 mouse 和 touch 事件，移动时取消长按
 * @param callback 长按触发的回调
 * @param threshold 触发阈值（ms），默认 500ms
 */
export function useLongPress(callback: () => void, threshold = 500): LongPressHandlers {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const triggeredRef = useRef(false);
  const startPosRef = useRef<{ x: number; y: number } | null>(null);

  const start = useCallback((x: number, y: number) => {
    triggeredRef.current = false;
    startPosRef.current = { x, y };
    timerRef.current = setTimeout(() => {
      triggeredRef.current = true;
      callback();
    }, threshold);
  }, [callback, threshold]);

  const cancel = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    startPosRef.current = null;
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    start(e.clientX, e.clientY);
  }, [start]);

  const onMouseUp = useCallback((_e: React.MouseEvent) => {
    cancel();
  }, [cancel]);

  const onMouseLeave = useCallback((_e: React.MouseEvent) => {
    cancel();
  }, [cancel]);

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0];
    if (touch) {
      start(touch.clientX, touch.clientY);
    }
  }, [start]);

  const onTouchEnd = useCallback((_e: React.TouchEvent) => {
    cancel();
  }, [cancel]);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (!startPosRef.current) return;
    const touch = e.touches[0];
    if (!touch) return;
    const dx = Math.abs(touch.clientX - startPosRef.current.x);
    const dy = Math.abs(touch.clientY - startPosRef.current.y);
    // 移动超过8px即取消长按
    if (dx > 8 || dy > 8) {
      cancel();
    }
  }, [cancel]);

  return {
    onMouseDown,
    onMouseUp,
    onMouseLeave,
    onTouchStart,
    onTouchEnd,
    onTouchMove,
  };
}
