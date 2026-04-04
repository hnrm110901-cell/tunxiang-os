/**
 * useApi / useMutation — 通用数据获取与写操作 Hook
 * - loading / data / error 状态
 * - 自动刷新（interval）
 * - 手动 refresh()
 * - Mock 降级（API 失败时返回 mockData）
 * - 缓存（相同 URL 在 cacheMs 内不重复请求）
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { apiRequest, ApiError, ApiRequestOptions } from '../api/client';

// ─── 简易缓存 ───

interface CacheEntry<T> {
  data: T;
  timestamp: number;
}

const cache = new Map<string, CacheEntry<unknown>>();
const DEFAULT_CACHE_MS = 5_000;

// ─── useApi ───

export interface UseApiOptions<T> extends ApiRequestOptions {
  /** 自动刷新间隔（毫秒），0 或不传则不自动刷新 */
  interval?: number;
  /** 缓存有效期（毫秒），默认 5000 */
  cacheMs?: number;
  /** Mock 降级数据，当 API 请求失败时返回此数据 */
  mockData?: T;
  /** 是否跳过初始请求（手动调用 refresh 触发） */
  skip?: boolean;
}

export interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  /** 是否正在使用 Mock 降级数据 */
  isMock: boolean;
  /** 手动刷新（忽略缓存） */
  refresh: () => Promise<void>;
}

export function useApi<T>(
  url: string | null,
  options?: UseApiOptions<T>,
): UseApiResult<T> {
  const {
    interval = 0,
    cacheMs = DEFAULT_CACHE_MS,
    mockData,
    skip = false,
    ...requestOptions
  } = options || {};

  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(!skip && !!url);
  const [error, setError] = useState<ApiError | null>(null);
  const [isMock, setIsMock] = useState(false);
  const mountedRef = useRef(true);

  const fetchData = useCallback(async (ignoreCache = false) => {
    if (!url) return;

    // 检查缓存
    if (!ignoreCache && cacheMs > 0) {
      const cached = cache.get(url) as CacheEntry<T> | undefined;
      if (cached && Date.now() - cached.timestamp < cacheMs) {
        setData(cached.data);
        setLoading(false);
        setError(null);
        setIsMock(false);
        return;
      }
    }

    setLoading(true);
    setError(null);

    try {
      const result = await apiRequest<T>(url, requestOptions);
      if (!mountedRef.current) return;

      setData(result);
      setIsMock(false);

      // 写入缓存
      if (cacheMs > 0) {
        cache.set(url, { data: result, timestamp: Date.now() });
      }
    } catch (err) {
      if (!mountedRef.current) return;

      const apiErr = err instanceof ApiError
        ? err
        : new ApiError(err instanceof Error ? err.message : '未知错误', 0);
      setError(apiErr);

      // Mock 降级
      if (mockData !== undefined) {
        setData(mockData);
        setIsMock(true);
      }
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, cacheMs]);

  const refresh = useCallback(async () => {
    await fetchData(true);
  }, [fetchData]);

  // 初始加载
  useEffect(() => {
    mountedRef.current = true;
    if (!skip && url) {
      fetchData();
    }
    return () => {
      mountedRef.current = false;
    };
  }, [url, skip, fetchData]);

  // 自动刷新
  useEffect(() => {
    if (!interval || interval <= 0 || !url || skip) return;

    const timer = setInterval(() => {
      fetchData(true);
    }, interval);

    return () => clearInterval(timer);
  }, [interval, url, skip, fetchData]);

  return { data, loading, error, isMock, refresh };
}

// ─── useMutation ───

export interface UseMutationOptions extends Omit<ApiRequestOptions, 'body'> {
  /** 成功后的回调 */
  onSuccess?: (data: unknown) => void;
  /** 失败后的回调 */
  onError?: (error: ApiError) => void;
}

export interface UseMutationResult<TData, TBody> {
  mutate: (body?: TBody) => Promise<TData | null>;
  data: TData | null;
  loading: boolean;
  error: ApiError | null;
  success: boolean;
  reset: () => void;
}

export function useMutation<TData = unknown, TBody = unknown>(
  url: string,
  method: 'POST' | 'PUT' | 'DELETE' | 'PATCH' = 'POST',
  options?: UseMutationOptions,
): UseMutationResult<TData, TBody> {
  const { onSuccess, onError, ...requestOptions } = options || {};

  const [data, setData] = useState<TData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const mutate = useCallback(async (body?: TBody): Promise<TData | null> => {
    setLoading(true);
    setError(null);
    setSuccess(false);

    try {
      const result = await apiRequest<TData>(url, {
        ...requestOptions,
        method,
        body,
      });
      if (!mountedRef.current) return null;

      setData(result);
      setSuccess(true);
      onSuccess?.(result);
      return result;
    } catch (err) {
      if (!mountedRef.current) return null;

      const apiErr = err instanceof ApiError
        ? err
        : new ApiError(err instanceof Error ? err.message : '未知错误', 0);
      setError(apiErr);
      onError?.(apiErr);
      return null;
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, method]);

  const reset = useCallback(() => {
    setData(null);
    setError(null);
    setSuccess(false);
    setLoading(false);
  }, []);

  return { mutate, data, loading, error, success, reset };
}
