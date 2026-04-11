import { useCallback, useRef } from 'react';

type SwipeDirection = 'left' | 'right' | 'up' | 'down' | null;

export interface SwipeHandlers {
  onTouchStart: (e: React.TouchEvent) => void;
  onTouchMove: (e: React.TouchEvent) => void;
  onTouchEnd: (e: React.TouchEvent) => void;
}

export interface UseSwipeOptions {
  /** 触发方向判定的最小滑动距离（px），默认 30 */
  threshold?: number;
  /** 滑动结束回调 */
  onSwipeEnd?: (direction: SwipeDirection, deltaX: number, deltaY: number) => void;
}

/**
 * 滑动检测 Hook
 * 使用 ref 追踪滑动状态，不触发组件重渲染，在 onSwipeEnd 时返回结果。
 */
export function useSwipe(options: UseSwipeOptions = {}): SwipeHandlers {
  const { threshold = 30, onSwipeEnd } = options;

  const startRef = useRef<{ x: number; y: number } | null>(null);
  const deltaRef = useRef<{ deltaX: number; deltaY: number; direction: SwipeDirection }>({
    deltaX: 0,
    deltaY: 0,
    direction: null,
  });

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0];
    if (!touch) return;
    startRef.current = { x: touch.clientX, y: touch.clientY };
    deltaRef.current = { deltaX: 0, deltaY: 0, direction: null };
  }, []);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    if (!startRef.current) return;
    const touch = e.touches[0];
    if (!touch) return;
    const dx = touch.clientX - startRef.current.x;
    const dy = touch.clientY - startRef.current.y;

    let direction: SwipeDirection = null;
    if (Math.abs(dx) >= threshold || Math.abs(dy) >= threshold) {
      direction = Math.abs(dx) >= Math.abs(dy)
        ? dx > 0 ? 'right' : 'left'
        : dy > 0 ? 'down' : 'up';
    }

    // ref 写入不触发重渲染
    deltaRef.current = { deltaX: dx, deltaY: dy, direction };
  }, [threshold]);

  const onTouchEnd = useCallback((_e: React.TouchEvent) => {
    if (!startRef.current) return;
    const { deltaX, deltaY, direction } = deltaRef.current;
    startRef.current = null;
    deltaRef.current = { deltaX: 0, deltaY: 0, direction: null };
    onSwipeEnd?.(direction, deltaX, deltaY);
  }, [onSwipeEnd]);

  return { onTouchStart, onTouchMove, onTouchEnd };
}
