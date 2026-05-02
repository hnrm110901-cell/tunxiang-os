/**
 * useTimeout — 安全的 setTimeout hook
 *
 * 在组件挂载时启动一个定时器，延迟 delay ms 后执行回调 fn。
 * 组件卸载时自动清除定时器，防止在已卸载的组件上执行 setState。
 *
 * 用法：
 *   useTimeout(() => { doSomething(); }, 3000);
 *
 * 如果 delay 为 null，定时器不会启动（适用于条件超时场景）。
 */

import { useEffect, useRef } from 'react';

export function useTimeout(fn: () => void, delay: number | null): void {
  const savedFn = useRef(fn);

  useEffect(() => {
    savedFn.current = fn;
  }, [fn]);

  useEffect(() => {
    if (delay === null) return;

    const id = setTimeout(() => savedFn.current(), delay);
    return () => clearTimeout(id);
  }, [delay]);
}

export default useTimeout;
