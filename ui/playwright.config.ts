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
    // Падение сквозного теста разбирают не по строчке ожидания, а по тому, что было
    // на экране. Трасса именно `retain-on-failure`, а не `on-first-retry`: повторов
    // у прогона нет, и на первом же падении разбирать было бы нечего.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    locale: 'ru-RU',
  },

  // Тема следует системе и переключателя не имеет, поэтому обе проверяются
  // отдельными прогонами одного и того же сценария.
  //
  // Сценарии, которые пишут в демо-установку (ответ на вопрос и живой поток), вынесены
  // в отдельный проект: после них вопрос закрыт, а в делах задач появились новые записи.
  // Зависимость от читающих проектов даёт им право идти последними — иначе читающие
  // видели бы уже изменённое демо, а прогон падал бы в зависимости от того, кто успел
  // первым.
  projects: [
    {
      name: 'светлая',
      testIgnore: /(answer|live|paging)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], colorScheme: 'light' },
    },
    {
      name: 'тёмная',
      testIgnore: /(answer|live|paging)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], colorScheme: 'dark' },
    },
    {
      name: 'запись',
      testMatch: /(answer|live|paging)\.spec\.ts/,
      // По одному пишущему сценарию за раз: они меняют одну и ту же демо-установку,
      // и параллельно каждый видел бы следы соседа.
      fullyParallel: false,
      workers: 1,
      dependencies: ['светлая', 'тёмная'],
      use: { ...devices['Desktop Chrome'], colorScheme: 'light' },
    },
  ],
});
