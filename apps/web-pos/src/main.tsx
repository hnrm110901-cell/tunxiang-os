import React from 'react';
import ReactDOM from 'react-dom/client';
import '@tx/tokens/tokens.css';
import { injectTokens } from './design-system';
import App from './App';
import { ErrorBoundary, reportCrashToTelemetry } from './components/ErrorBoundary';
import { rootFallback, navigateToTables } from './components/RootFallback';
import { ToastContainer } from './components/ToastContainer';
import { isEnabled, initFeatureFlags, subscribe } from './config/featureFlags';

// Sprint A1 P1-4：启动时异步拉取远程 flag，不阻塞首屏渲染。
// 失败（网络/404/超时）静默回退到 DEFAULTS。
initFeatureFlags().catch(() => {
  // fetchFlagsFromRemote 内部已 log 警告，这里兜底防 unhandled rejection
});

function Root(): JSX.Element {
  // 订阅远程下发后的 flag 变化，触发 Root 重渲染以反映最新 boundary 状态
  const [, setVersion] = React.useState(0);
  React.useEffect(() => subscribe(() => setVersion((v) => v + 1)), []);

  const boundaryEnabled = isEnabled('trade.pos.errorBoundary.enable');

  if (boundaryEnabled) {
    return (
      <ErrorBoundary
        onReport={reportCrashToTelemetry}
        onReset={navigateToTables}
        fallback={rootFallback}
      >
        <App />
        <ToastContainer />
      </ErrorBoundary>
    );
  }
  return (
    <>
      <App />
      <ToastContainer />
    </>
  );
}

// 注入 Design System CSS 变量（品牌色 #FF6B35，深色主题）
injectTokens();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
);
