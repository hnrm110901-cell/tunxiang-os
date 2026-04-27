import React from 'react';
import ReactDOM from 'react-dom/client';
import '@tx/tokens/tokens.css';
import '@tx/touch/styles/reset.css';
import '@tx/touch/styles/animations.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
