import { expect, test } from '@playwright/test';
import { side } from './contour';

/**
 * Единственный сценарий, который меняет состояние знакомства владельца установки
 * (`TRK-361`, `TRK-360#17`): свежий контур заводит его учётную запись со знакомством
 * `pending` (`app/db/migrations/versions/20260928_1200_onboarding_state.py`), и после
 * «Пропустить» это состояние меняется навсегда. Поэтому файл — в проекте «запись»
 * (`playwright.config.ts`): один сценарий, после читающих, без соседа, который увидел
 * бы уже пройденное «Начало» вместо свежего.
 *
 * Содержимое экрана (четыре раздела по порядку `TRK-360#14`, фразы «Завести задачи» и
 * «Выполнить задачи» с текстом о новой сессии между ними) проверяется здесь же, на
 * первом и единственном заходе, где `/` действительно открывает «Начало» на этом
 * контуре: у читающих сценариев (`start.spec.ts`) той же гарантии нет, поэтому они
 * открывают `/start` напрямую и в решение `/` не заглядывают.
 */
const SECTION_HEADINGS = [
  'Зачем это',
  'Откуда берутся задачи',
  'Что сказать агенту',
  'Что делать самому',
];

test('«Начало» на свежем контуре объясняет способ работы и уступает место списку задач после «Пропустить»', async ({
  page,
}) => {
  await page.goto('/');

  await expect(page).toHaveURL(/\/start$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Начало' })).toBeVisible();

  // Четыре раздела по порядку решения TRK-360#14 — это главное, что человек должен
  // понять с первого взгляда.
  expect(await page.locator('main h2').allTextContents()).toEqual(SECTION_HEADINGS);

  // Фразы «Завести задачи» и «Выполнить задачи», а между ними — про новую сессию
  // агента. Фразы «Знакомство» здесь нет: учебный проект `START` не засеян (TRK-370).
  await expect(page.getByRole('heading', { name: 'Знакомство' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Завести задачи' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Выполнить задачи' })).toBeVisible();

  const tellAgentText = (await page.locator('main').innerText()).replace(/\s+/g, ' ');
  const fileAt = tellAgentText.indexOf('Завести задачи');
  const sessionAt = tellAgentText.indexOf('новой сессии агента');
  const executeAt = tellAgentText.indexOf('Выполнить задачи');
  expect(fileAt).toBeGreaterThan(-1);
  expect(sessionAt).toBeGreaterThan(fileAt);
  expect(executeAt).toBeGreaterThan(sessionAt);

  await page.getByRole('button', { name: 'Пропустить' }).click();
  await expect(page).toHaveURL(/\/tasks$/);

  // Держится после перезагрузки: состояние живёт на сервере, не в браузере.
  await page.reload();
  await expect(page).toHaveURL(/\/tasks$/);
  await page.goto('/');
  await expect(page).toHaveURL(/\/tasks$/);

  // «Начало» остаётся достижимым пунктом панели, сколько бы раз его ни пропустили.
  await side(page).getByRole('link', { name: 'Начало' }).click();
  await expect(page).toHaveURL(/\/start$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Начало' })).toBeVisible();
});
