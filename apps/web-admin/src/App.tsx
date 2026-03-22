import { isBrowser } from './bridge/TXBridge';

function App() {
  return (
    <div style={{ padding: 24, textAlign: 'center' }}>
      <h1>TunxiangOS Admin</h1>
      <p>V3.0 — 总部管理后台</p>
      <p>Environment: {isBrowser() ? 'Browser' : 'Unknown'}</p>
    </div>
  );
}

export default App;
