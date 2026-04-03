/**
 * App.tsx — 企微侧边栏 H5 主入口
 *
 * 流程：
 *   1. useWecom()  — 初始化企微 JS-SDK，获取 externalUserId
 *   2. useCustomer() — 通过 externalUserId 查询会员档案
 *   3. 渲染 CustomerProfile（或加载/错误状态）
 */
import React from 'react';
import { useWecom } from './hooks/useWecom';
import { useCustomer } from './hooks/useCustomer';
import { CustomerProfile } from './components/CustomerProfile';
import {
  SkeletonCard,
  ErrorState,
  NotFoundState,
} from './components/LoadingState';

export default function App(): React.ReactElement {
  const {
    externalUserId,
    error: wecomError,
    loading: wecomLoading,
  } = useWecom();

  const {
    customer,
    loading: customerLoading,
    error: customerError,
    refetch,
  } = useCustomer(externalUserId);

  const isLoading = wecomLoading || customerLoading;
  const error = wecomError ?? customerError;

  return (
    <div className="min-h-screen bg-tx-bg-2 font-sans">
      {/* 顶部品牌栏 */}
      <header className="sticky top-0 z-10 bg-tx-navy px-4 py-2.5 flex items-center gap-2">
        <span className="text-tx-primary font-bold text-base">屯象OS</span>
        <span className="text-white/60 text-sm">· 客户洞察</span>
      </header>

      {/* 内容区 */}
      <main className="max-w-sidebar mx-auto p-3">
        {isLoading && <SkeletonCard />}

        {!isLoading && error && (
          <ErrorState
            message={error}
            onRetry={externalUserId ? refetch : undefined}
          />
        )}

        {!isLoading && !error && !customer && <NotFoundState />}

        {!isLoading && !error && customer && (
          <CustomerProfile customer={customer} onRefresh={refetch} />
        )}
      </main>
    </div>
  );
}
