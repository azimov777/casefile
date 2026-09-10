import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@/shared/styles/index.css';
import { syncDocumentLanguage } from '@/shared/i18n';
import { App } from '@/app';
import { loadInstallToken } from '@/shared/api';

const container = document.getElementById('root');
if (container === null) throw new Error('Root element #root not found');

// Язык разметки и заголовок вкладки — до первого кадра, а не после первой отрисовки.
syncDocumentLanguage();

/*
 * Конфигурацию установки спрашивают до первой отрисовки: на локальной установке ключ
 * приходит оттуда, и приложение, начавшее рисовать раньше ответа, показало бы экран
 * входа тому, кому он не нужен. Ждать нечего — файл лежит на том же источнике, откуда
 * только что приехала сама эта страница.
 *
 * Отказ здесь невозможен по устройству: любой исход чтения — это «ключ есть» или
 * «ключа нет», и второе штатно ведёт на экран входа.
 *
 * Продолжением, а не `await` верхнего уровня: тот требует от цели сборки больше, чем
 * ей задано, и `vite build` отказался бы собирать.
 */
void loadInstallToken().then(() => {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
