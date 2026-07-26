/** Frontend entry point — providers, router, and mount. */

import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { ThemeProvider } from '@/lib/theme';
import { AuditProvider } from '@/lib/store';
import './index.css';

const root = document.getElementById('root');
if (!root) {
  throw new Error('Missing #root element in index.html.');
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <AuditProvider>
          <App />
        </AuditProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
);
