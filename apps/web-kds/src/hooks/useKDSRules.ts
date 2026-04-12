/**
 * useKDSRules — 加载并缓存门店KDS多维标识规则配置
 *
 * - 优先从 localStorage 读取缓存（5分钟内有效）
 * - 挂载时从 /api/v1/kds-rules/{storeId} 异步拉取最新配置
 * - 拉取失败时降级为默认值，不影响看板渲染
 */
import { useState, useEffect } from 'react';
import {
  fetchKDSRules,
  DEFAULT_KDS_RULES,
  type KDSRuleConfig,
} from '../api/kdsRulesApi';

const CACHE_KEY_PREFIX = 'kds_rules_';
const CACHE_TTL_MS = 5 * 60 * 1000; // 5分钟

interface CacheEntry {
  rules: KDSRuleConfig;
  cachedAt: number;
}

function readCache(storeId: string): KDSRuleConfig | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY_PREFIX + storeId);
    if (!raw) return null;
    const entry: CacheEntry = JSON.parse(raw);
    if (Date.now() - entry.cachedAt > CACHE_TTL_MS) return null;
    return entry.rules;
  } catch {
    return null;
  }
}

function writeCache(storeId: string, rules: KDSRuleConfig): void {
  try {
    const entry: CacheEntry = { rules, cachedAt: Date.now() };
    localStorage.setItem(CACHE_KEY_PREFIX + storeId, JSON.stringify(entry));
  } catch {
    // localStorage 写入失败时静默忽略
  }
}

export interface UseKDSRulesResult {
  rules: KDSRuleConfig;
  loading: boolean;
  refresh: () => void;
}

export function useKDSRules(storeId: string | null | undefined): UseKDSRulesResult {
  const [rules, setRules] = useState<KDSRuleConfig>(() => {
    if (!storeId) return DEFAULT_KDS_RULES;
    return readCache(storeId) ?? DEFAULT_KDS_RULES;
  });
  const [loading, setLoading] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    if (!storeId) return;

    let cancelled = false;
    setLoading(true);

    fetchKDSRules(storeId)
      .then((fetched) => {
        if (cancelled) return;
        setRules(fetched);
        writeCache(storeId, fetched);
      })
      .catch(() => {
        // 拉取失败：继续使用缓存或默认值，无需报错
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [storeId, refreshTick]);

  const refresh = () => setRefreshTick((t: number) => t + 1);

  return { rules, loading, refresh };
}
