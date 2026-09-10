import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/shared/styles/index.css';
import { syncDocumentLanguage } from '@/shared/i18n';
import { App } from '@/app';

const container = document.getElementById('root');
if (container === null) throw new Error('Root element #root not found');

// Язык разметки и заголовок вкладки — до первого кадра, а не после первой отрисовки.
syncDocumentLanguage();

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
