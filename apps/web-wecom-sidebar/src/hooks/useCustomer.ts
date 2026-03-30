/**
 * useCustomer.ts — 通过企微 externalUserId 查询会员信息
 */
import { useState, useEffect } from 'react';
import { fetchCustomerByWecomId } from '../api/memberApi';
import type { CustomerProfile } from '../types';

export interface UseCustomerResult {
  customer: CustomerProfile | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useCustomer(externalUserId: string | null): UseCustomerResult {
  const [customer, setCustomer] = useState<CustomerProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!externalUserId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchCustomerByWecomId(externalUserId)
      .then((data) => {
        if (!cancelled) setCustomer(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          const msg = err instanceof Error ? err.message : '查询会员信息失败';
          setError(msg);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [externalUserId, tick]);

  const refetch = () => setTick((t) => t + 1);

  return { customer, loading, error, refetch };
}
