import { defineConfig, devices } from '@playwright/test';

/**
 * Конфиг записи демонстрационного GIF (TRK-82), отдельный от `playwright.config.ts`.
 *
 * `pnpm e2e` запускает `playwright test` без `-c` и подхватывает только файл с
 * умолчательным именем — этот сюда не попадает, обычный прогон он не трогает.
 *
 * Бэкенд для записи — не контур `docker-compose.yml` этого репозитория (тот поднимает
 * `globalSetup` из `e2e/`), а отдельная изолированная установка на своих портах и со
 * своим проектом Compose (`COMPOSE_PROJECT_NAME=trk82`), поднятая и наполненная вручную
 * до записи. Поэтому здесь нет `globalSetup`/`globalTeardown` — `e2e-demo/README.md`
 * называет команды, которыми контур поднимается и гасится.
 */
export default defineConfig({
  testDir: './e2e-demo',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.DEMO_UI_URL ?? 'http://localhost:8082',
    viewport: { width: 1280, height: 800 },
    locale: 'en-US',
    colorScheme: 'light',
    video: {
      mode: 'on',
      size: { width: 1280, height: 800 },
    },
  },
  projects: [{ name: 'demo-recording', use: { ...devices['Desktop Chrome'] } }],
});
