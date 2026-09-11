/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv, type Plugin } from 'vite';

/**
 * `/config.json` на дев-сервере: то же, что в собранном образе кладёт рядом со статикой
 * контур. Ключ берётся из `TRACKER_UI_TOKEN`; без переменной посредник отвечает `404` —
 * тот самый «ключа от установки нет», с которым работает установка на нескольких людей.
 *
 * Без посредника поведение локальной установки проверялось бы только в Docker,
 * а разработка шла бы по единственному оставшемуся пути — через экран входа.
 *
 * Имя переменной намеренно без приставки `VITE_`: такое значение Vite не подставит
 * в собранный код ни при какой ошибке, а секрету там делать нечего. Читает её сервер
 * разработки на машине, в образ она не попадает.
 */
function installConfig(token: string): Plugin {
  return {
    name: 'tracker-install-config',
    configureServer(server) {
      server.middlewares.use('/config.json', (_request, response) => {
        response.setHeader('Content-Type', 'application/json');
        response.setHeader('Cache-Control', 'no-store');
        if (token === '') {
          response.statusCode = 404;
          response.end('{}');
          return;
        }
        response.end(JSON.stringify({ token }));
      });
    },
  };
}

// Адрес бэкенда для прокси разработки. В собранном образе `/api` проксирует nginx,
// поэтому в коде приложения базового адреса нет: запросы всегда идут на свой источник,
// и токен не покидает заголовок.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  return {
    plugins: [react(), tailwindcss(), installConfig(env.TRACKER_UI_TOKEN ?? '')],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
        '@testing': fileURLToPath(new URL('./testing', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: env.VITE_API_URL || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      // В jsdom `fetch` — из Node, а он не умеет относительные адреса. Приложение ходит
      // на свой источник, поэтому тестам источник называется явно: тем же адресом,
      // на котором jsdom держит страницу.
      env: { VITE_API_BASE_URL: 'http://localhost:3000' },
      setupFiles: ['./testing/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}', 'testing/**/*.test.ts'],
      css: { modules: { classNameStrategy: 'non-scoped' } },
      restoreMocks: true,
    },
  };
});
