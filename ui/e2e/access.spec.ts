import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import {
  fontsReady,
  installWithoutKey,
  motionSettled,
  readTaskToken,
  side,
  silenceJournal,
} from './contour';

/**
 * Экран «Доступы» (UI-106): список токенов установки, заведение агента, выпуск с
 * показом секрета один раз и отзыв.
 *
 * Сценарий **пишет** в установку контура: заводит участника (удалить его нельзя) и
 * выпускает токен, поэтому живёт в проекте «запись» и идёт после читающих. Установка
 * контура поднимается заново на каждый прогон (`global-teardown.ts` гасит её вместе с
 * томом), так что имя участника свободно.
 *
 * Ключ контура — набора `main` (TRK-69), и запись на экране открыта без всякого ввода:
 * это и есть путь человека на локальной установке (`UI-104#7`).
 */

const AGENT = 'e2e_agent';
const TOKEN_NAME = 'e2e_agent на прогоне';
/** Общий агентский токен: им меряется тёмная тема и вид фрагментов с меткой. */
const SHARED_TOKEN_NAME = 'общий на прогоне';

/** Переход на экран из боковой панели — так, как его находит человек. */
async function openFromNavigation(page: Page): Promise<void> {
  await side(page).getByRole('link', { name: 'Доступы' }).click();
  await expect(page).toHaveURL(/\/access$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Доступы' })).toBeVisible();
  await expect(side(page).getByRole('link', { name: 'Доступы' })).toHaveAttribute(
    'aria-current',
    'page',
  );
}

/**
 * Полный список нарушений доступности, снятый **в покое**: без порога серьёзности и
 * после того, как доехали шрифты и переходы цвета.
 *
 * Ждать перехода обязательно: указатель после закрытия окна остаётся там, где была его
 * кнопка, и на перезагруженной странице под ним оказывается соседняя — та едет из
 * запрета в наведение переходом цвета, а `axe`, попавший в этот кадр, меряет
 * промежуточный цвет и находит нарушение, которого в покое нет (`UI-59#4`,
 * `docs/notes/testing.md`).
 */
async function violations(page: Page): Promise<string[]> {
  await fontsReady(page);
  await motionSettled(page.locator('body'));

  const found = await new AxeBuilder({ page }).analyze();
  return found.violations.map(
    (violation) =>
      `${violation.id} (${violation.impact}): ${violation.nodes.map((node) => node.target).join(' ')}`,
  );
}

test('ключ установки: агент заведён, токен выпущен, секрет показан один раз и отозван', async ({
  page,
  request,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks');
  await openFromNavigation(page);

  // Ключ, которым работает сам интерфейс, отмечен в списке — и отмечен ровно один.
  await expect(page.getByText('ключ этого сеанса')).toHaveCount(1);

  await page.getByRole('button', { name: 'Завести агента' }).click();
  const agentDialog = page.getByRole('dialog');
  await agentDialog.getByLabel('Имя').fill(AGENT);
  await agentDialog.getByRole('button', { name: 'Завести', exact: true }).click();

  // Заведённый участник — ещё не подключённый агент: окно ведёт к выпуску токена.
  await expect(agentDialog.getByText(`Участник ${AGENT} заведён`)).toBeVisible();
  await agentDialog.getByRole('button', { name: 'Выпустить ему токен' }).click();

  const issueDialog = page.getByRole('dialog');
  await expect(issueDialog.getByLabel('За кого говорит токен')).toHaveValue(AGENT);
  // Умолчание набора — `task`, и его никто не выбирал.
  await expect(issueDialog.getByRole('radio', { name: /^task/ })).toBeChecked();
  await issueDialog.getByLabel('Имя токена').fill(TOKEN_NAME);
  await issueDialog.getByRole('button', { name: 'Выпустить', exact: true }).click();

  // Секрет показан один раз — и сразу во фрагментах подключения.
  const secretDialog = page.getByRole('dialog');
  await expect(secretDialog.getByText('Скопируйте секрет сейчас')).toBeVisible();
  const shown = await secretDialog
    .getByRole('figure', { name: 'Секрет токена, показан один раз' })
    .locator('pre code')
    .textContent();
  const secret = (shown ?? '').trim();
  expect(secret).toMatch(/^trk_[A-Za-z0-9_-]{8,}$/);

  const claude = secretDialog.getByRole('region', { name: 'Claude Code' }).locator('pre code');
  await expect(claude).toContainText(`Authorization: Bearer ${secret}`);

  // Доступность окна секрета: сверяется полный список нарушений, а не порог тяжести.
  // Тема здесь одна — та, что у проекта; вторую меряет сценарий ниже своим контекстом,
  // а не сменой темы посреди жизни страницы (`docs/notes/testing.md`).
  expect(await violations(page), 'окно секрета').toEqual([]);

  // Секрет настоящий: им ходят, и участник за ним — только что заведённый.
  const asAgent = await request.get('/api/v1/bootstrap', {
    headers: { Authorization: `Bearer ${secret}` },
  });
  expect(asAgent.status()).toBe(200);
  const session = (await asAgent.json()) as {
    data: { participant: { name: string }; token: { scope: string } };
  };
  expect(session.data.participant.name).toBe(AGENT);
  expect(session.data.token.scope).toBe('task');

  await secretDialog.getByRole('button', { name: 'Секрет сохранён' }).click();

  // Окно закрыто — секрета нет ни на экране, ни в хранилищах вкладки.
  await expect(page.getByRole('dialog')).toHaveCount(0);
  expect(await page.content()).not.toContain(secret);
  const stored = await page.evaluate(() =>
    JSON.stringify({ local: { ...window.localStorage }, session: { ...window.sessionStorage } }),
  );
  expect(stored).not.toContain(secret);

  // Перезагрузка второго показа не даёт: секрет не хранится нигде.
  await page.reload();
  await expect(page.getByRole('article', { name: `Доступ «${TOKEN_NAME}»` })).toBeVisible();
  expect(await page.content()).not.toContain(secret);

  // Экран в покое: доступность всего списка, тоже без единого нарушения.
  expect(await violations(page), 'экран «Доступы»').toEqual([]);

  // Отзыв спрашивает подтверждение и объясняет последствия.
  const row = page.getByRole('article', { name: `Доступ «${TOKEN_NAME}»` });
  await row.getByRole('button', { name: 'Отозвать' }).click();
  const confirm = page.getByRole('alertdialog');
  await expect(confirm).toContainText('вернуть его нельзя');
  await confirm.getByRole('button', { name: 'Отозвать', exact: true }).click();

  // Строка помечена отозванной, и кнопки отзыва у неё больше нет.
  await expect(row).toHaveAttribute('data-revoked', 'true');
  await expect(row.getByText('отозван')).toBeVisible();
  await expect(row.getByRole('button', { name: 'Отозвать' })).toHaveCount(0);

  // Запрос этим токеном отвечает отказом: доступ снят.
  const after = await request.get('/api/v1/bootstrap', {
    headers: { Authorization: `Bearer ${secret}` },
  });
  expect(after.status()).toBe(401);
  expect((await after.json()) as { error: { code: string } }).toMatchObject({
    error: { code: 'unauthorized' },
  });
});

test.describe('тёмная тема', () => {
  /*
   * Тема задаётся контекстом, а не `emulateMedia` посреди страницы: замер `axe`,
   * снятый сразу после смены, ловит кадр между темами — цвет текста уже новый, а фон
   * ещё прежний, и правило контраста находит несуществующее нарушение
   * (`docs/notes/testing.md`, «Замер `axe` сразу после смены темы»).
   *
   * Проект «запись» идёт в светлой теме, поэтому тёмную объявляет сам сценарий.
   */
  test.use({ colorScheme: 'dark' });

  test('окно секрета общего токена и экран доступов не дают нарушений `axe`', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/access');
    await expect(page.getByRole('heading', { level: 1, name: 'Доступы' })).toBeVisible();

    await page.getByRole('button', { name: 'Выпустить токен' }).click();
    const issueDialog = page.getByRole('dialog');
    // Общий агентский токен: у фрагментов появляется `X-Actor-Label`, и объяснение
    // метки — часть того, что меряется.
    await issueDialog
      .getByLabel('За кого говорит токен')
      .selectOption({ label: 'Общий агентский токен, без участника' });
    await issueDialog.getByLabel('Имя токена').fill(SHARED_TOKEN_NAME);
    await issueDialog.getByRole('button', { name: 'Выпустить', exact: true }).click();

    const secretDialog = page.getByRole('dialog');
    await expect(secretDialog.getByText('Скопируйте секрет сейчас')).toBeVisible();
    await expect(secretDialog.getByRole('region', { name: 'Claude Code' })).toContainText(
      'X-Actor-Label',
    );
    expect(await violations(page), 'окно секрета в тёмной теме').toEqual([]);

    await secretDialog.getByRole('button', { name: 'Секрет сохранён' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    expect(await violations(page), 'экран «Доступы» в тёмной теме').toEqual([]);

    // За собой прибирает сам сценарий: выпущенный доступ отзывается там же, где выпущен.
    const row = page.getByRole('article', { name: `Доступ «${SHARED_TOKEN_NAME}»` });
    await row.getByRole('button', { name: 'Отозвать' }).click();
    await page
      .getByRole('alertdialog')
      .getByRole('button', { name: 'Отозвать', exact: true })
      .click();
    await expect(row).toHaveAttribute('data-revoked', 'true');
  });
});

test('ключ набора `task` с экрана входа: список виден, запись недоступна с причиной', async ({
  page,
}) => {
  const writes: string[] = [];
  page.on('request', (sent) => {
    if (sent.url().includes('/api/') && sent.method() !== 'GET') writes.push(sent.url());
  });

  await silenceJournal(page);
  await installWithoutKey(page);
  await page.goto('/login');
  await page.getByLabel('Токен участника').fill(readTaskToken());
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/tasks$/);

  await openFromNavigation(page);

  // Список доступов открыт и такому ключу: чтение токенов не требует `main`.
  await expect(page.getByRole('article', { name: /Доступ «/ }).first()).toBeVisible();

  const newAgent = page.getByRole('button', { name: 'Завести агента' });
  const issue = page.getByRole('button', { name: 'Выпустить токен' });
  await expect(newAgent).toBeDisabled();
  await expect(issue).toBeDisabled();
  // Причина сказана там же, и запрещённые кнопки ссылаются на неё.
  const explanation = page.getByText('Запись закрыта: этот сеанс работает ключом набора task');
  await expect(explanation).toBeVisible();
  const explanationId = await explanation.getAttribute('id');
  await expect(newAgent).toHaveAttribute('aria-describedby', explanationId ?? '');
  await expect(issue).toHaveAttribute('aria-describedby', explanationId ?? '');
  await expect(page.getByRole('button', { name: 'Отозвать' })).toHaveCount(0);

  expect(await violations(page), 'экран с ключом `task`').toEqual([]);

  // Ни одного запроса записи: отказ `403` проверкой прав не служит.
  expect(writes).toEqual([]);
});
