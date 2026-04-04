/**
 * LoadingSpinner -- 路由懒加载 Suspense fallback
 * 暗色主题居中 Spin + 提示文字
 */
import { Spin } from 'antd';

export function LoadingSpinner() {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
        minHeight: 320,
        color: 'var(--text-3, #999)',
        gap: 16,
      }}
    >
      <Spin size="large" />
      <span style={{ fontSize: 14 }}>加载中...</span>
    </div>
  );
}
