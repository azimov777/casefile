/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// Адрес бэкенда для прокси разработки. В собранном образе `/api` проксирует nginx,
// поэтому в коде приложения базового адреса нет: запросы всегда идут на свой источник,
// и токен не покидает заголовок.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');

  return {
    plugins: [react(), tailwindcss()],
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
