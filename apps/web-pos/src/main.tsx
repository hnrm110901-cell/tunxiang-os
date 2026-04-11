import React from 'react';
import ReactDOM from 'react-dom/client';
import '@tx/tokens/tokens.css';
import { injectTokens } from './design-system';
import App from './App';

// 注入 Design System CSS 变量（品牌色 #FF6B35，深色主题）
injectTokens();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
