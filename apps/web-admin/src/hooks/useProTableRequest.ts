import { useCallback } from 'react';
import type { ParamsType } from '@ant-design/pro-components';

interface UseProTableRequestOptions<T> {
  apiFn: (params: { page: number; size: number; [key: string]: unknown }) => Promise<{ items: T[]; total: number }>;
  tenantId: string;
}

/**
 * useProTableRequest — 统一封装 ProTable 的 request 回调
 *
 * 使用方式：
 *   const request = useProTableRequest({ apiFn: api.dish.list, tenantId });
 *   <ProTable request={request} ... />
 *
 * 自动将 ProTable 的 { current, pageSize, ...filters } 转换为
 * 屯象OS API 约定的 { page, size, ...filters } 格式。
 */
export function useProTableRequest<T>({ apiFn, tenantId }: UseProTableRequestOptions<T>) {
  return useCallback(
    async (params: ParamsType) => {
      const { current = 1, pageSize = 20, ...filters } = params;
      const res = await apiFn({
        page: current,
        size: pageSize,
        ...filters,
        tenantId,
      });
      return {
        data: res.items,
        total: res.total,
        success: true,
      };
    },
    [apiFn, tenantId]
  );
}
