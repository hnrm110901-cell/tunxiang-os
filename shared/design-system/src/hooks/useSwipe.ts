/**
 * useSwipe — 通用触控滑动检测 Hook
 *
 * 支持左滑/右滑手势检测，适用于 KDS 工单卡片的"左滑完成"等场景。
 * 同时支持触控和鼠标（桌面演示用）。
 *
 * 用法：
 *   const { swipeHandlers, swipeOffset, isSwiping } = useSwipe({
 *     onSwipeLeft: () => handleComplete(ticketId),
 *     threshold: 72,
 *   });
 *   return <div {...swipeHandlers} style={{ transform: `translateX(${swipeOffset}px)` }}>...</div>
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export interface UseSwipeOptions {
  onSwipeLeft?: () => void;
  onSwipeRight?: () => void;
  /** 触发阈值，默认 72px */
  threshold?: number;
  /** 最大滑动距离，默认 120px */
  maxOffset?: number;
}

export interface UseSwipeReturn {
  swipeHandlers: {
    onTouchStart: (e: React.TouchEvent) => void;
    onTouchMove: (e: React.TouchEvent) => void;
    onTouchEnd: (e: React.TouchEvent) => void;
    onMouseDown: (e: React.MouseEvent) => void;
  };
  swipeOffset: number;
  isSwiping: boolean;
  reset: () => void;
}

export function useSwipe({
  onSwipeLeft,
  onSwipeRight,
  threshold = 72,
  maxOffset = 120,
}: UseSwipeOptions): UseSwipeReturn {
  const startXRef = useRef<number | null>(null);
  const startYRef = useRef<number | null>(null);
  const isDraggingRef = useRef(false);
  const isMouseRef = useRef(false);
  const mouseMoveRef = useRef<((ev: MouseEvent) => void) | null>(null);
  const mouseUpRef = useRef<((ev: MouseEvent) => void) | null>(null);

  const [swipeOffset, setSwipeOffset] = useState(0);
  const [isSwiping, setIsSwiping] = useState(false);

  const reset = useCallback(() => {
    setSwipeOffset(0);
    setIsSwiping(false);
    startXRef.current = null;
    startYRef.current = null;
    isDraggingRef.current = false;
  }, []);

  const handleStart = useCallback((clientX: number, clientY: number) => {
    startXRef.current = clientX;
    startYRef.current = clientY;
    isDraggingRef.current = false;
  }, []);

  const handleMove = useCallback((clientX: number, clientY: number) => {
    if (startXRef.current === null || startYRef.current === null) return;

    const dx = clientX - startXRef.current;
    const dy = clientY - startYRef.current;

    // 如果纵向移动更多，视为滚动，不处理滑动
    if (!isDraggingRef.current && Math.abs(dy) > Math.abs(dx)) {
      return;
    }

    isDraggingRef.current = true;
    setIsSwiping(true);

    // 限制最大偏移：如果提供了 onSwipeRight 则允许双向，否则只允许左滑
    const clamped = onSwipeRight
      ? Math.max(-maxOffset, Math.min(maxOffset, dx))
      : Math.max(-maxOffset, Math.min(0, dx));
    setSwipeOffset(clamped);
  }, [maxOffset, onSwipeRight]);

  const handleEnd = useCallback((clientX: number) => {
    if (startXRef.current === null) return;
    const dx = clientX - startXRef.current;

    if (dx < -threshold && onSwipeLeft) {
      onSwipeLeft();
    } else if (dx > threshold && onSwipeRight) {
      onSwipeRight();
    }

    // 回弹
    setSwipeOffset(0);
    setIsSwiping(false);
    startXRef.current = null;
    startYRef.current = null;
    isDraggingRef.current = false;
  }, [threshold, onSwipeLeft, onSwipeRight]);

  // Touch events
  const onTouchStart = useCallback((e: React.TouchEvent) => {
    const t = e.touches[0];
    handleStart(t.clientX, t.clientY);
  }, [handleStart]);

  const onTouchMove = useCallback((e: React.TouchEvent) => {
    const t = e.touches[0];
    handleMove(t.clientX, t.clientY);
  }, [handleMove]);

  const onTouchEnd = useCallback((e: React.TouchEvent) => {
    const t = e.changedTouches[0];
    handleEnd(t.clientX);
  }, [handleEnd]);

  // Mouse events（桌面演示用）
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    isMouseRef.current = true;
    handleStart(e.clientX, e.clientY);

    const onMouseMove = (ev: MouseEvent) => {
      handleMove(ev.clientX, ev.clientY);
    };
    const onMouseUp = (ev: MouseEvent) => {
      isMouseRef.current = false;
      handleEnd(ev.clientX);
      mouseMoveRef.current = null;
      mouseUpRef.current = null;
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };
    mouseMoveRef.current = onMouseMove;
    mouseUpRef.current = onMouseUp;
    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }, [handleStart, handleMove, handleEnd]);

  // Cleanup: remove window mouse listeners on unmount
  useEffect(() => {
    return () => {
      if (mouseMoveRef.current) {
        window.removeEventListener('mousemove', mouseMoveRef.current);
      }
      if (mouseUpRef.current) {
        window.removeEventListener('mouseup', mouseUpRef.current);
      }
    };
  }, []);

  return {
    swipeHandlers: { onTouchStart, onTouchMove, onTouchEnd, onMouseDown },
    swipeOffset,
    isSwiping,
    reset,
  };
}
