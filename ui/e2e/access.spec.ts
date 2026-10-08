import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import {
  fontsReady,
  grantAccess,
  installWithoutKey,
  motionSettled,
  readAgentKey,
  readE2eToken,
  side,
  silenceJournal,
} from './contour';

/**
 * Экран «Доступы» (UI-106, TRK-473): доступы установки тремя разделами — «Подключения»,
 * «Ключи агентов», «Сеансы входа»; заведение агента, выпуск ключа с показом секрета один
 * раз, отзыв и отключение подключения.
 *
 * Сценарий **пишет** в установку контура: заводит участника (удалить его нельзя) и
 * выпускает токен, поэтому живёт в проекте «запись» и идёт после читающих. Установка
 * контура поднимается заново на каждый прогон (`global-teardown.ts` гасит её вместе с
 * томом), так что имя участника свободно.
 *
 * Ключ контура — `local-ui`, вход владельца без ввода: запись на экране открыта без всякого
 * ввода, это и есть путь человека на локальной установке (`UI-104#7`). Наборов токена нет
 * (TRK-471), и сценарии их не называют.
 */

// Буфер читается из самой страницы (`navigator.clipboard.readText`): контексту нужны оба права.
test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

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

/** Кнопка раскрытия истории отозванных доступов: число в подписи — данные контура. */
function historyToggle(page: Page) {
  return page.getByRole('button', { name: /^История: \d+ снят/ });
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

  const newAgentButton = page.getByRole('button', { name: 'Завести агента' });
  await newAgentButton.click();
  await expect(page.getByRole('dialog')).toBeVisible();
  // `Esc` закрывает окно и возвращает фокус на кнопку, которая его открыла: она
  // стоит `Dialog.Trigger`, и без этого Radix отправлял бы фокус на `body`
  // (`UI-175#11`, `UI-178`).
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(newAgentButton).toBeFocused();

  await newAgentButton.click();
  const agentDialog = page.getByRole('dialog');
  await agentDialog.getByLabel('Имя').fill(AGENT);
  await agentDialog.getByRole('button', { name: 'Завести', exact: true }).click();

  // Заведённый участник — ещё не подключённый агент: окно ведёт к выпуску токена.
  await expect(agentDialog.getByText(`Участник ${AGENT} заведён`)).toBeVisible();
  await agentDialog.getByRole('button', { name: 'Выпустить ему ключ' }).click();

  const issueDialog = page.getByRole('dialog');
  await expect(issueDialog.getByLabel('За кого говорит ключ')).toHaveValue(AGENT);
  // Выбора набора нет: у ключа один вид права.
  await expect(issueDialog.getByRole('radio')).toHaveCount(0);
  await issueDialog.getByLabel('Имя ключа').fill(TOKEN_NAME);
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

  // Claude Code и Codex входят по OAuth: в их фрагментах ключа нет, он — у клиентов без OAuth.
  const claude = secretDialog.getByRole('region', { name: 'Claude Code' }).locator('pre code');
  await expect(claude).toContainText('claude mcp login plugin:casefile:casefile');
  await expect(claude).not.toContainText(secret);

  const pickClient = (name: string) =>
    secretDialog
      .getByRole('navigation', { name: 'Клиент' })
      .getByRole('link', { name, exact: true })
      .click();

  await pickClient('Codex');
  const codex = secretDialog.getByRole('region', { name: 'Codex', exact: true });
  await expect(codex.locator('figure pre code').first()).toContainText('--ref plugin');
  await expect(codex).not.toContainText(secret);

  await pickClient('Любой клиент MCP');
  const any = secretDialog.getByRole('region', { name: 'Любой клиент MCP', exact: true });
  await expect(any.locator('pre code').last()).toContainText(`Authorization: Bearer ${secret}`);

  // Установка скила отдельно — только клиентам без плагина; копируется тем же нажатием, и
  // в скопированном секрета нет — скил общий (TRK-420).
  const skill = secretDialog.getByRole('region', { name: 'Установите скил' });
  await expect(skill).toBeVisible();
  await skill.getByRole('button', { name: 'Копировать: Установка скила в другого агента' }).click();
  await expect(
    skill.getByRole('button', { name: 'Скопировано: Установка скила в другого агента' }),
  ).toBeVisible();
  const copiedSkill = await page.evaluate(() => navigator.clipboard.readText());
  expect(copiedSkill).toBe('npx skills add azimov777/casefile#stable');
  expect(copiedSkill).not.toContain(secret);
  await pickClient('Claude Code');
  await expect(secretDialog.getByRole('region', { name: 'Установите скил' })).toHaveCount(0);

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
    data: { participant: { name: string } };
  };
  expect(session.data.participant.name).toBe(AGENT);

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
  // Экран дочитан, когда запись разрешена: сеанс приходит отдельным запросом, и «Завести
  // агента» до него стоит запрещённой, а потом переходом цвета встаёт в «разрешено». `axe`,
  // попавший в этот переход, меряет промежуточный цвет — контраст 4.29 вместо 4.5, которого
  // в покое нет (TRK-686#2).
  await expect(newAgentButton).toBeEnabled();

  // Экран в покое: доступность всего списка, тоже без единого нарушения.
  expect(await violations(page), 'экран «Доступы»').toEqual([]);

  // Отзыв спрашивает подтверждение и объясняет последствия.
  const row = page.getByRole('article', { name: `Доступ «${TOKEN_NAME}»` });
  const revokeButton = row.getByRole('button', { name: 'Отозвать' });
  await revokeButton.click();
  let confirm = page.getByRole('alertdialog');
  await expect(confirm).toContainText('вернуть его нельзя');
  // Своя кнопка на каждую строку (`UI-178`): `Esc` возвращает фокус ровно на неё, а
  // не на первую строку списка или `body`.
  await page.keyboard.press('Escape');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(revokeButton).toBeFocused();

  await revokeButton.click();
  confirm = page.getByRole('alertdialog');
  await confirm.getByRole('button', { name: 'Отозвать', exact: true }).click();

  // Отозванный уходит из действующих в историю, а история свёрнута (UI-131).
  const active = page.getByRole('region', { name: /^Ключи агентов/ });
  await expect(active.getByRole('article', { name: `Доступ «${TOKEN_NAME}»` })).toHaveCount(0);
  const toggle = historyToggle(page);
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(row).toHaveCount(0);
  expect(await page.locator('article[data-revoked="true"]').count()).toBe(0);

  // Раскрывается одним действием.
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');

  // Строка помечена отозванной, и кнопки отзыва у неё больше нет.
  await expect(row).toHaveAttribute('data-revoked', 'true');
  await expect(row.getByText('отозван')).toBeVisible();
  await expect(row.getByRole('button', { name: 'Отозвать' })).toHaveCount(0);

  // Действующие идут раньше отозванных: в порядке разметки ни один действующий не стоит
  // после первого отозванного, хотя выдача установки отдаёт их вперемешку по времени.
  const order = await page
    .getByRole('article', { name: /^Доступ «/ })
    .evaluateAll((items) => items.map((item) => item.getAttribute('data-revoked') === 'true'));
  expect(order.length).toBeGreaterThan(1);
  expect(order.indexOf(true)).toBeGreaterThan(0);
  expect(order.slice(order.indexOf(true)).every(Boolean)).toBe(true);

  // Запрос этим токеном отвечает отказом: доступ снят.
  const after = await request.get('/api/v1/bootstrap', {
    headers: { Authorization: `Bearer ${secret}` },
  });
  expect(after.status()).toBe(401);
  expect((await after.json()) as { error: { code: string } }).toMatchObject({
    error: { code: 'unauthorized' },
  });
});

test('подключение OAuth стоит в «Подключениях», «Отключить» убирает его из списка, а в выпуске нет людей', async ({
  page,
  request,
}) => {
  const CLIENT = 'Claude Code на прогоне';
  // Вход агента по OAuth идёт через его клиента; здесь строка собрана службой выпуска
  // (`grantAccess`): участник — заведённый агент, подключил человек `owner`.
  grantAccess({ human: 'owner', kind: 'oauth', agent: 'demo_agent', name: CLIENT });

  await silenceJournal(page);
  await page.goto('/access');
  await expect(page.getByRole('heading', { level: 1, name: 'Доступы' })).toBeVisible();

  // Три раздела по виду доступа; подключение — в первом, а не среди ключей.
  const connections = page.getByRole('region', { name: /^Подключения/ });
  const keys = page.getByRole('region', { name: /^Ключи агентов/ });
  const sessions = page.getByRole('region', { name: /^Сеансы входа/ });
  await expect(keys).toBeVisible();
  await expect(sessions).toBeVisible();

  const row = connections.getByRole('article', { name: `Доступ «${CLIENT}»` });
  await expect(row).toBeVisible();
  await expect(keys.getByRole('article', { name: `Доступ «${CLIENT}»` })).toHaveCount(0);
  await expect(row.getByText('demo_agent')).toBeVisible();
  await expect(row.getByText('кто подключил: owner')).toBeVisible();
  await expect(row.getByText('последний вызов')).toBeVisible();
  // Секрета подключения нет нигде на экране: человек его не видел и не увидит.
  await expect(page.getByRole('main')).not.toContainText(/trk_[A-Za-z0-9_-]{8,}/);

  // Ключ этого компьютера — среди сеансов входа и подписан «этот компьютер».
  const own = sessions.getByRole('article', { name: 'Доступ «local-ui»' });
  await expect(own.getByText('этот компьютер')).toBeVisible();
  await expect(own.getByText('ключ этого сеанса')).toBeVisible();
  // У ключей агентов есть колонка «кто выдал».
  await expect(keys.getByText(/^кто выдал: /).first()).toBeVisible();

  // Телефон: страница не прокручивается вбок.
  await page.setViewportSize({ width: 390, height: 844 });
  await fontsReady(page);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow, 'горизонтальная прокрутка на 390 px').toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 1280, height: 800 });

  expect(await violations(page), 'экран с подключением').toEqual([]);

  // В выпуске ключа людей нет: у участника `owner` род — человек, и в выборе его не будет.
  await page.getByRole('button', { name: 'Выпустить ключ' }).click();
  const whom = page.getByRole('dialog').getByLabel('За кого говорит ключ');
  await expect(whom.locator('option[value="demo_agent"]')).toHaveCount(1);
  await expect(whom.locator('option[value="owner"]')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toHaveCount(0);

  // «Отключить» спрашивает подтверждение и убирает подключение из раздела.
  const disconnect = row.getByRole('button', { name: 'Отключить' });
  await disconnect.click();
  const confirm = page.getByRole('alertdialog');
  await expect(confirm).toContainText('сразу');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(disconnect).toBeFocused();

  await disconnect.click();
  await page
    .getByRole('alertdialog')
    .getByRole('button', { name: 'Отключить', exact: true })
    .click();
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(row).toHaveCount(0);

  // Подключение ушло в историю: на сервере оно отозвано, а не удалено.
  await historyToggle(page).click();
  await expect(page.getByRole('article', { name: `Доступ «${CLIENT}»` })).toHaveAttribute(
    'data-revoked',
    'true',
  );
  const listed = await request.get('/api/v1/tokens?limit=200', {
    headers: { Authorization: `Bearer ${readE2eToken()}` },
  });
  const mine = (
    (await listed.json()) as {
      data: { name: string; kind: string; revoked_at: string | null }[];
    }
  ).data.find((token) => token.name === CLIENT);
  expect(mine?.kind).toBe('oauth');
  expect(mine?.revoked_at).not.toBeNull();
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

    const issueButton = page.getByRole('button', { name: 'Выпустить ключ' });
    await issueButton.click();
    await expect(page.getByRole('dialog')).toBeVisible();
    // `Esc` возвращает фокус на кнопку-триггер и в тёмной теме (`UI-178`).
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(issueButton).toBeFocused();

    await issueButton.click();
    const issueDialog = page.getByRole('dialog');
    // Общий агентский токен: у фрагментов появляется `X-Actor-Label`, и объяснение
    // метки — часть того, что меряется.
    await issueDialog
      .getByLabel('За кого говорит ключ')
      .selectOption({ label: 'Общий ключ, без участника' });
    await issueDialog.getByLabel('Имя ключа').fill(SHARED_TOKEN_NAME);
    await issueDialog.getByRole('button', { name: 'Выпустить', exact: true }).click();

    const secretDialog = page.getByRole('dialog');
    await expect(secretDialog.getByText('Скопируйте секрет сейчас')).toBeVisible();
    // Claude Code входит по OAuth: ни ключа, ни метки в его фрагменте нет; метка — на
    // вкладке клиента без OAuth, где ключ есть.
    await expect(secretDialog.getByRole('region', { name: 'Claude Code' })).not.toContainText(
      'X-Actor-Label',
    );
    await secretDialog
      .getByRole('navigation', { name: 'Клиент' })
      .getByRole('link', { name: 'Любой клиент MCP', exact: true })
      .click();
    await expect(
      secretDialog.getByRole('region', { name: 'Любой клиент MCP', exact: true }),
    ).toContainText('X-Actor-Label');
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
    // Отозванный уходит в свёрнутую историю; раскрытая, она меряется `axe` тоже.
    await expect(row).toHaveCount(0);
    await historyToggle(page).click();
    await expect(row).toHaveAttribute('data-revoked', 'true');
    expect(await violations(page), 'история отозванных в тёмной теме').toEqual([]);
  });
});

test('ключ агента с экрана входа: список виден, выпуск закрыт с причиной, запросов записи нет', async ({
  page,
}) => {
  const writes: string[] = [];
  page.on('request', (sent) => {
    if (sent.url().includes('/api/') && sent.method() !== 'GET') writes.push(sent.url());
  });

  await silenceJournal(page);
  await installWithoutKey(page);
  await page.goto('/login');
  await page.getByLabel('Токен участника').fill(readAgentKey());
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).toHaveURL(/\/tasks$/);

  await openFromNavigation(page);

  // Список доступов открыт и такому ключу: чтение токенов не требует учётной записи.
  await expect(page.getByRole('article', { name: /Доступ «/ }).first()).toBeVisible();

  const newAgent = page.getByRole('button', { name: 'Завести агента' });
  const issue = page.getByRole('button', { name: 'Выпустить ключ' });
  await expect(newAgent).toBeDisabled();
  await expect(issue).toBeDisabled();
  // Причина сказана там же, и запрещённые кнопки ссылаются на неё.
  const explanation = page.getByText('Выпуск закрыт: этот сеанс работает ключом агента');
  await expect(explanation).toBeVisible();
  const explanationId = await explanation.getAttribute('id');
  await expect(newAgent).toHaveAttribute('aria-describedby', explanationId ?? '');
  await expect(issue).toHaveAttribute('aria-describedby', explanationId ?? '');

  expect(await violations(page), 'экран с ключом агента').toEqual([]);

  // Ни одного запроса записи: отказ `403` проверкой прав не служит.
  expect(writes).toEqual([]);
});
