import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken, shellReady } from './contour';

/**
 * Механизм пояснений экрана: скрытие по одному и все разом, возврат с экрана «Начало»
 * (решение владельца `TRK-360#16`, состояние на сервере — `TRK-360#17`, механизм —
 * `TRK-362`). Единственное пояснение на этом контуре стоит на Входящей.
 *
 * Владелец контура открывается со скрытыми пояснениями (`hints.hidden_all: true`,
 * `global-setup.ts`): читающие и почти все пишущие сценарии написаны до пояснений и
 * меряют геометрию и снимки без них. Этот сценарий сам включает пояснения в начале и
 * возвращает `hidden_all: true` в конце — иначе он оставил бы соседним пишущим
 * сценариям экран с лишним блоком. Поэтому файл идёт в проекте «запись», после
 * читающих, и меняет учётную запись владельца — как `start-onboarding.spec.ts`.
 */

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

/** Учётная запись владельца: тем же ключом, которым ходит основной экземпляр интерфейса. */
async function ownerAccountId(request: APIRequestContext): Promise<string> {
  const response = await request.get('/api/v1/bootstrap', { headers: auth() });
  expect(response.ok()).toBe(true);
  const body = (await response.json()) as { data: { account: { id: string } | null } };
  const accountId = body.data.account?.id;
  if (accountId === undefined) throw new Error('у владельца контура нет учётной записи');
  return accountId;
}

async function setHints(
  request: APIRequestContext,
  accountId: string,
  hints: { hidden_all?: boolean; hidden?: string[] },
): Promise<void> {
  const response = await request.patch(`/api/v1/accounts/${accountId}/onboarding`, {
    headers: auth(),
    data: { hints },
  });
  expect(response.ok()).toBe(true);
}

const EXPLANATION_TEXT = /Сюда приходят обсуждения, в которых агент ждёт вашего ответа/;

test('«Показать пояснения снова» возвращает пояснение, закрытие и перезагрузка его снова прячут, и это не хранится в браузере', async ({
  page,
  browser,
  request,
}) => {
  const accountId = await ownerAccountId(request);

  try {
    // Начало: контур поднят со скрытыми пояснениями — «Показать пояснения снова» их
    // возвращает.
    await page.goto('/start');
    await page.getByRole('button', { name: 'Показать пояснения снова' }).click();
    // Действие ставит пустое состояние и на самом экране «Начало» больше не видно.
    await expect(page.getByRole('button', { name: 'Показать пояснения снова' })).toHaveCount(0);

    // Входящая: пояснение видно первым блоком содержимого, ничего больше не нажимая.
    await page.goto('/questions');
    const main = page.getByRole('main');
    await expect(main.getByText(EXPLANATION_TEXT)).toBeVisible();

    // Закрытие одного пояснения убирает его с экрана сразу.
    await main.getByRole('button', { name: 'Закрыть пояснение' }).click();
    await expect(main.getByText(EXPLANATION_TEXT)).toHaveCount(0);

    // Состояние живёт на сервере, а не в браузере: переживает перезагрузку страницы.
    await page.reload();
    await shellReady(page);
    await expect(page.getByRole('main').getByText(EXPLANATION_TEXT)).toHaveCount(0);

    // И новый браузерный контекст той же учётной записи видит то же самое — ключ и
    // состояние скрытия не лежат в localStorage/sessionStorage вкладки.
    const context = await browser.newContext();
    try {
      const freshPage = await context.newPage();
      await freshPage.goto('/questions');
      await shellReady(freshPage);
      await expect(freshPage.getByRole('main').getByText(EXPLANATION_TEXT)).toHaveCount(0);
    } finally {
      await context.close();
    }
  } finally {
    // Контур возвращается в состояние, которое ждут соседние пишущие сценарии
    // (constraints задачи TRK-362).
    await setHints(request, accountId, { hidden_all: true, hidden: [] });
  }
});
