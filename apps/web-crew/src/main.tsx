import React from 'react';
import ReactDOM from 'react-dom/client';
// Design Tokens（屯象OS统一CSS变量，主色 #FF6B35）
import '@tx/tokens/tokens.css';
// TXTouch 触控基础样式
import '@tx/touch/styles/reset.css';
import '@tx/touch/styles/animations.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
