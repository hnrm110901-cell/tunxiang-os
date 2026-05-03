import React from 'react';
import ReactDOM from 'react-dom/client';
import '@tx/tokens/tokens.css';
import { injectTokens } from './design-system';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { LangProvider } from './i18n/LangContext';
// A1 安全修复：reportCrashToTelemetry 改从 api/tradeApi 导入（JWT-derived tenant_id，
// 不再读 localStorage 'tenant_id'）。ErrorBoundary.tsx 中的旧版函数已弃用。
import { reportCrashToTelemetry } from './api/tradeApi';
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
        <LangProvider>
          <App />
        </LangProvider>
        <ToastContainer />
      </ErrorBoundary>
    );
  }
  return (
    <>
      <LangProvider>
        <App />
      </LangProvider>
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
