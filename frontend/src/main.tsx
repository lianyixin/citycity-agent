import React from 'react';
import ReactDOM from 'react-dom/client';
import { LogtoProvider } from '@logto/react';
import App from './App';
import Callback from './Callback';
import { logtoConfig } from './auth';
import './styles.css';

function renderRoot() {
  const path = window.location.pathname;
  const root = ReactDOM.createRoot(document.getElementById('root')!);
  if (path === '/callback') {
    root.render(
      <React.StrictMode>
        <LogtoProvider config={logtoConfig}>
          <Callback />
        </LogtoProvider>
      </React.StrictMode>,
    );
    return;
  }
  root.render(
    <React.StrictMode>
      <LogtoProvider config={logtoConfig}>
        <App />
      </LogtoProvider>
    </React.StrictMode>,
  );
}

renderRoot();
