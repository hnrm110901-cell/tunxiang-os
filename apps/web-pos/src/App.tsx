import { isAndroidPOS, isIPad, isBrowser } from './bridge/TXBridge';

function App() {
  const env = isAndroidPOS() ? 'Android POS' : isIPad() ? 'iPad' : 'Browser';

  return (
    <div style={{ padding: 24, textAlign: 'center' }}>
      <h1>TunxiangOS POS</h1>
      <p>V3.0 — AI-Native Restaurant Chain Operating System</p>
      <p>Environment: {env}</p>
    </div>
  );
}

export default App;
