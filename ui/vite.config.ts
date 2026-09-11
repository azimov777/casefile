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
      // Две ловушки промежуточного слоя Vite, обе про порядок навешивания (UI-107).
      //
      // 1) Возвращённая функция — не побочный эффект самого хука: Vite вызывает такие
      // функции уже после того, как навесил собственные внутренние промежуточные
      // обработчики, в том числе проверку Host (`server.allowedHosts`). Прежде здесь стоял
      // вызов `server.middlewares.use` прямо в теле хука, и тогда обработчик вставал в
      // цепочку РАНЬШЕ проверки Host — дев-сервер отдавал ключ установки любому заголовку
      // Host, хотя сам Vite её уже умеет. Возврат функции чинит порядок, не трогая сам
      // список разрешённых хостов: петля и `*.localhost` разрешены умолчанием Vite, дальше
      // добавлять нечего.
      //
      // 2) Пост-хук встаёт и позже `htmlFallbackMiddleware` — запасного пути
      // одностраничного приложения, который переписывает `req.url` в `/index.html`, если
      // заголовок `Accept` не сузил запрос до `application/json` (пусто, `*/*` и
      // `text/html` — все переписываются: это и есть браузерный `fetch` без явного
      // `Accept`). Обработчик, подключённый через `server.middlewares.use('/config.json',
      // ...)`, сверяет именно переписанный `req.url` и на обычный запрос браузера уже не
      // срабатывает — дев-сервер вместо ключа отдавал разметку `index.html`. `req.originalUrl`
      // запасной путь не трогает: connect выставляет его раз, при разборе запроса, до
      // любых middleware, — поэтому путь берём из него, а сам обработчик остаётся не
      // привязан к `server.middlewares.use(path, ...)` и решает сам, свой ли это запрос.
      return () => {
        server.middlewares.use((request, response, next) => {
          const path = (request.originalUrl ?? request.url ?? '').split('?')[0];
          if (path !== '/config.json') {
            next();
            return;
          }
          response.setHeader('Content-Type', 'application/json');
          response.setHeader('Cache-Control', 'no-store');
          if (token === '') {
            response.statusCode = 404;
            response.end('{}');
            return;
          }
          response.end(JSON.stringify({ token }));
        });
      };
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
