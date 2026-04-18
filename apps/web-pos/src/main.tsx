import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ErrorBoundary, reportCrashToTelemetry } from './components/ErrorBoundary';
import { rootFallback, navigateToTables } from './components/RootFallback';
import { ToastContainer } from './components/ToastContainer';
import { isEnabled } from './config/featureFlags';

const boundaryEnabled = isEnabled('trade.pos.errorBoundary.enable');

const tree = boundaryEnabled ? (
  <ErrorBoundary
    onReport={reportCrashToTelemetry}
    onReset={navigateToTables}
    fallback={rootFallback}
  >
    <App />
    <ToastContainer />
  </ErrorBoundary>
) : (
  <>
    <App />
    <ToastContainer />
  </>
);

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{tree}</React.StrictMode>,
);
