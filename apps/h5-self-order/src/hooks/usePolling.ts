import { useEffect, useRef } from 'react';

/**
 * 轮询 hook — 定时调用异步函数
 * @param fn - 异步函数
 * @param interval - 轮询间隔（ms）
 * @param enabled - 是否启用
 */
export function usePolling(
  fn: () => Promise<void>,
  interval: number,
  enabled = true,
) {
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;
    const tick = async () => {
      if (cancelled) return;
      await fnRef.current();
      if (!cancelled) {
        timerId = window.setTimeout(tick, interval);
      }
    };

    let timerId = window.setTimeout(tick, interval);
    return () => {
      cancelled = true;
      clearTimeout(timerId);
    };
  }, [interval, enabled]);
}
