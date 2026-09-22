import { defineConfig, devices } from '@playwright/test';

// Порт тот же, что у контура сквозных тестов в `docker-compose.yml`, и по той же
// причине не 8080: его держит постоянный контур интерфейса. Два умолчания обязаны
// двигаться вместе — адрес, разошедшийся с публикацией, дал бы прогон в пустоту.
const BASE_URL = process.env.E2E_BASE_URL ?? `http://localhost:${process.env.UI_PORT ?? '8081'}`;

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
    /*
     * Полосы прокрутки прогон видит так же, как человек (UI-116). Playwright без окна
     * запускает Chromium с `--hide-scrollbars`, и полоса там нулевой ширины — какой
     * бы она ни была в жизни (замер UI-116#29: с флагом 0, без него 8). Пока полосу
     * рисовала система, снимать флаг было нельзя: на macOS с умолчанием «Automatically
     * based on input device» она то оверлейная (0), то классическая (15) — по тому,
     * мышью или трекпадом пользовались на машине последними, а не по коду
     * (находка UI-116#8), и всякий замер геометрии стал бы недетерминированным.
     * Своя полоса это снимает: её толщина задана стилями и одинакова в любом прогоне.
     */
    launchOptions: { ignoreDefaultArgs: ['--hide-scrollbars'] },
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
      testIgnore:
        /(access|answer|board-column|case-readable|case-latest|live|live-board|live-list|paging|layout|task-list-screen|remark|people|parents-long|language|language-formats|english)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], colorScheme: 'light' },
    },
    {
      name: 'тёмная',
      testIgnore:
        /(access|answer|board-column|case-readable|case-latest|live|live-board|live-list|paging|layout|task-list-screen|remark|people|parents-long|language|language-formats|english)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], colorScheme: 'dark' },
    },
    {
      /*
       * Английский интерфейс проверяется прогоном, а не тем, что кто-то один раз
       * переключил язык (UI-80).
       *
       * Язык задан `locale` контекста, потому что так его получает и человек: при
       * чистом хранилище определитель берёт язык браузера. Параметра `?lang=` у
       * интерфейса нет — ни для человека, ни ради удобства теста (UI-76).
       *
       * Сценариев здесь три, и это осознанная граница. `language` и `language-formats`
       * проверяют сам язык — порядок выбора, `lang` у документа, форматы времени
       * и чисел; в светлой и тёмной они гонялись дважды, хотя темы не касаются, и
       * потому переехали сюда целиком. `english` — дымовой прогон главных экранов.
       *
       * Остальных сценариев здесь нет намеренно: они ищут элементы по подписям, а
       * проверяют поведение, геометрию и тему, а не язык. Перенесённые сюда, они
       * удвоили бы и время прогона, и число мест, где подпись написана дважды —
       * в словаре и в ожидании теста.
       */
      name: 'английская',
      testMatch: /(language|language-formats|english)\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], colorScheme: 'light', locale: 'en-US' },
    },
    {
      name: 'запись',
      testMatch:
        /(access|answer|board-column|case-readable|case-latest|live|live-board|live-list|paging|layout|task-list-screen|remark|people|parents-long)\.spec\.ts/,
      // По одному пишущему сценарию за раз: они меняют одну и ту же демо-установку,
      // и параллельно каждый видел бы следы соседа.
      fullyParallel: false,
      workers: 1,
      // Английский проект читающий, и он тоже обязан увидеть демо-данные до правок.
      dependencies: ['светлая', 'тёмная', 'английская'],
      use: { ...devices['Desktop Chrome'], colorScheme: 'light' },
    },
  ],
});
