/**
 * LoadingState.tsx — 骨架屏 + 错误状态
 */
import React from 'react';

// ─── 骨架屏 ───────────────────────────────────────────────────────
export function SkeletonCard(): React.ReactElement {
  return (
    <div className="p-4 animate-pulse">
      {/* 头像 + 姓名行 */}
      <div className="flex items-center gap-3 mb-4">
        <div className="w-14 h-14 rounded-full bg-tx-bg-3" />
        <div className="flex-1">
          <div className="h-4 bg-tx-bg-3 rounded-tx-sm w-24 mb-2" />
          <div className="h-3 bg-tx-bg-3 rounded-tx-sm w-16" />
        </div>
      </div>

      {/* 数据行 */}
      <div className="grid grid-cols-3 gap-3 mb-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="bg-tx-bg-2 rounded-tx-md p-3">
            <div className="h-3 bg-tx-bg-3 rounded w-full mb-2" />
            <div className="h-5 bg-tx-bg-3 rounded w-3/4" />
          </div>
        ))}
      </div>

      {/* 标签行 */}
      <div className="flex gap-2 mb-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-6 w-16 bg-tx-bg-3 rounded-full" />
        ))}
      </div>

      {/* 风险条 */}
      <div className="h-8 bg-tx-bg-3 rounded-tx-md w-full" />
    </div>
  );
}

// ─── 错误状态 ─────────────────────────────────────────────────────
interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps): React.ReactElement {
  return (
    <div className="flex flex-col items-center justify-center min-h-[200px] p-6 text-center">
      {/* 图标 */}
      <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mb-3">
        <svg
          className="w-6 h-6 text-tx-danger"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 9v4m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
          />
        </svg>
      </div>

      <p className="text-sm text-tx-text-2 mb-4">{message}</p>

      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-tx-primary text-white text-sm rounded-tx-md
                     active:scale-[0.97] transition-transform duration-200"
        >
          重试
        </button>
      )}
    </div>
  );
}

// ─── 未绑定状态（该客户暂无会员档案）────────────────────────────
export function NotFoundState(): React.ReactElement {
  return (
    <div className="flex flex-col items-center justify-center min-h-[200px] p-6 text-center">
      <div className="w-12 h-12 rounded-full bg-tx-bg-2 flex items-center justify-center mb-3">
        <svg
          className="w-6 h-6 text-tx-text-3"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"
          />
        </svg>
      </div>
      <p className="text-sm font-medium text-tx-text-1 mb-1">该客户暂无会员档案</p>
      <p className="text-xs text-tx-text-3">可邀请客户扫码注册成为会员</p>
    </div>
  );
}
