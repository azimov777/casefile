import { defineConfig, devices } from '@playwright/test';

const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${process.env.UI_PORT ?? '8080'}`;

/**
 * Сквозные тесты идут против настоящего бэкенда с демо-данными, поднятого
 * `docker-compose.yml` этого репозитория. Контур поднимает и гасит сам прогон:
 * задача, которая работает только «руками на моей машине», не считается выполненной.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: process.env.CI !== undefined,
  workers: process.env.CI !== undefined ? 1 : undefined,
  reporter: process.env.CI !== undefined ? 'list' : [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,

  globalSetup: './e2e/global-setup.ts',
  globalTeardown: './e2e/global-teardown.ts',

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    locale: 'ru-RU',
  },

  // Тема следует системе и переключателя не имеет, поэтому обе проверяются
  // отдельными прогонами одного и того же сценария.
  //
  // Сценарий ответа на вопрос вынесен в отдельный проект: он единственный, кто пишет
  // в демо-установку, и после него вопрос закрыт. Зависимость от читающих проектов
  // даёт ему право идти последним — иначе те увидели бы уже отвеченный вопрос,
  // а прогон падал бы в зависимости от того, кто успел первым.
  projects: [
    {
      name: 'светлая',
      testIgnore: /answer\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], colorScheme: 'light' },
    },
    {
      name: 'тёмная',
      testIgnore: /answer\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], colorScheme: 'dark' },
    },
    {
      name: 'ответ',
      testMatch: /answer\.spec\.ts/,
      dependencies: ['светлая', 'тёмная'],
      use: { ...devices['Desktop Chrome'], colorScheme: 'light' },
    },
  ],
});
