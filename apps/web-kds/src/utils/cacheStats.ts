/**
 * 全局 KDS 缓存诊断接口（开发期 / 运维 SSH 排障用）。
 * 挂载到 window.__kdsCache，生产环境不暴露逻辑细节，只暴露 stats/clear。
 */
import { getStats, clear, getAll, type CacheStats, type KdsCachedOrder } from '../db/kdsOrdersDB';

interface KdsCacheDiagnostics {
  getStats: () => Promise<CacheStats>;
  getAll: () => Promise<KdsCachedOrder[]>;
  clear: () => Promise<void>;
}

declare global {
  interface Window {
    __kdsCache?: KdsCacheDiagnostics;
  }
}

export function installCacheDiagnostics(): void {
  if (typeof window === 'undefined') return;
  window.__kdsCache = {
    getStats,
    getAll,
    clear,
  };
}
