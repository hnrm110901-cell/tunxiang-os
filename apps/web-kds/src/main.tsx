import React from 'react';
import ReactDOM from 'react-dom/client';
import '../../packages/tx-tokens/src/tokens.css';
import '../../packages/tx-touch/src/styles/reset.css';
import '../../packages/tx-touch/src/styles/animations.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
