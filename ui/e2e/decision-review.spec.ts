import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { fontsReady, readAgentKey, readE2eToken } from './contour';

/*
 * Проверка решений человеком (TRK-755, TRK-758) на живом бэкенде.
 *
 * Сценарий пишущий — подтверждает и отклоняет решения DEMO, а в своём проекте исправляет и
 * отклоняет решение, которое заменило другое, — и потому идёт в проекте «запись»: читающие
 * сценарии должны успеть увидеть демо-данные, какими их оставил посев. Решения «не
 * подтверждены», только если их подшил агент, поэтому в своём проекте их пишет ключ
 * `demo_agent`, а не ключ установки (его подпись — человека, и такие решения подтверждены).
 */

const ownerToken = readE2eToken();
const RUN = Date.now().toString(36).toUpperCase();
const KEY = `RV${RUN}`.slice(0, 16);
const OLD = `Страница ленты — сто записей, прогон ${RUN}`;
const NEW = `Страница ленты — двести записей, прогон ${RUN}`;
const FIXED = `Страница ленты — сто пятьдесят записей, прогон ${RUN}`;

async function api(
  request: APIRequestContext,
  token: string,
  path: string,
  data: Record<string, unknown>,
  expected: number[] = [200, 201],
): Promise<Record<string, unknown>> {
  const response = await request.post(path, {
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect(expected, await response.text()).toContain(response.status());
  return ((await response.json()) as { data?: Record<string, unknown> }).data ?? {};
}

function row(scope: Page | Locator, ref: string): Locator {
  return scope.locator(`li[data-decision="${ref}"]`);
}

/** Раскрывает строку решения: тело и действия появляются под ней. */
async function expand(item: Locator): Promise<void> {
  await item.locator('button[aria-expanded]').click();
  await expect(item.getByRole('group', { name: /^Проверка решения/ })).toBeVisible();
}

test('DEMO: строка «Не подтверждено решений», отбор, «Подтвердить» и «Отклонить» с причиной', async ({
  page,
}) => {
  await page.goto('/projects/DEMO');
  const line = page.locator('[data-unconfirmed]');
  const count = Number(await line.getAttribute('data-unconfirmed'));
  expect(count).toBeGreaterThan(2);
  await expect(line).toContainText(`Не подтверждено решений: ${count}`);

  // Строка — ссылка на вкладку «Решения» с отбором «Не подтверждены», строк ровно столько.
  await line.getByRole('link').click();
  await expect(page).toHaveURL(/\/projects\/DEMO\?tab=decisions&show=unconfirmed$/);
  const list = page.getByRole('list', { name: 'Решения' });
  await expect(list.locator('li[data-decision]')).toHaveCount(count);

  // «Подтвердить» — сразу, без окна: решение уходит из отбора, после перезагрузки на одно меньше.
  const first = list.locator('li[data-decision]').first();
  const confirmedRef = (await first.getAttribute('data-decision')) ?? '';
  await expand(first);
  await first.getByRole('button', { name: /^Подтвердить решение/ }).click();
  await expect(row(page, confirmedRef)).toHaveCount(0);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('li[data-decision]')).toHaveCount(count - 1);
  await page.goto('/projects/DEMO');
  await expect(page.locator('[data-unconfirmed]')).toHaveAttribute(
    'data-unconfirmed',
    String(count - 1),
  );
  // Подтверждённое осталось действующим и читается «подтверждено».
  await page.goto('/projects/DEMO?tab=decisions');
  await expect(row(page, confirmedRef)).toContainText('подтверждено');
  await expect(row(page, confirmedRef)).not.toContainText('не подтверждено');

  // «Отклонить» с причиной: из «Действующих» уходит, в «Показать снятые» стоит с плашкой.
  await page.goto('/projects/DEMO?tab=decisions&show=unconfirmed');
  const target = page.locator('li[data-decision]').first();
  const rejectedRef = (await target.getAttribute('data-decision')) ?? '';
  expect(rejectedRef).not.toBe(confirmedRef);
  await expand(target);
  await target.getByRole('button', { name: /^Отклонить решение/ }).click();
  const dialog = page.getByRole('alertdialog');
  await dialog.getByLabel('Причина (необязательно)').fill('Не согласен: нужен замер');
  await dialog.getByRole('button', { name: 'Отклонить', exact: true }).click();
  await expect(dialog).toHaveCount(0);

  await page.goto('/projects/DEMO?tab=decisions');
  await expect(row(page, rejectedRef)).toHaveCount(0);
  await page.goto('/projects/DEMO?tab=decisions&show=removed');
  await expect(row(page, rejectedRef)).toHaveAttribute('data-status', 'rejected');
  await expect(row(page, rejectedRef)).toContainText('отклонено');
  await expect(row(page, rejectedRef).getByRole('group')).toHaveCount(0);

  // Запись о проверке лежит в деле владельца решения (проекта или области) и названа
  // фразой по фактам, а не английским заголовком.
  const [owner = ''] = rejectedRef.split('#');
  await page.goto(
    owner.includes('/')
      ? `/projects/${owner.replace('/', '/areas/')}?tab=case`
      : `/projects/${owner}?tab=case`,
  );
  await expect(
    page.getByRole('table').getByRole('button', { name: `Отклонено решение ${rejectedRef}` }),
  ).toBeVisible();
});

test('свой проект: «Исправить» создаёт подтверждённое решение, «Отклонить» говорит о прежнем', async ({
  page,
  request,
}) => {
  const agent = readAgentKey();
  await api(request, ownerToken, '/api/v1/projects', { key: KEY, title: 'Проверка решений' });
  const old = await api(request, agent, `/api/v1/projects/${KEY}/entries`, {
    type: 'decision',
    title: OLD,
    body: 'Сто записей умещаются в один кадр.',
  });
  const added = await api(request, agent, `/api/v1/projects/${KEY}/entries`, {
    type: 'decision',
    title: NEW,
    body: 'Двести записей читаются одним запросом.',
    supersedes: [old.no],
  });
  const oldRef = `${KEY}#${old.no as number}`;
  const newRef = `${KEY}#${added.no as number}`;

  await page.goto(`/projects/${KEY}?tab=decisions`);
  const item = row(page, newRef);
  await expect(item).toContainText('не подтверждено');
  await expand(item);

  // Окно «Отклонить»: прежнее решение, которое это заменило, действовать снова не станет.
  await item.getByRole('button', { name: /^Отклонить решение/ }).click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toContainText(
    `Решение ${oldRef}, которое это заменило, действовать снова не станет`,
  );
  await dialog.getByRole('button', { name: 'Отмена' }).click();
  await expect(dialog).toHaveCount(0);

  // «Исправить»: форма с текущими названием и телом, отправка заменяет решение новым.
  await item.getByRole('button', { name: /^Исправить решение/ }).click();
  const form = page.getByRole('dialog', { name: `Исправить решение ${newRef}` });
  await expect(form.getByLabel('Название')).toHaveValue(NEW);
  await expect(form.getByLabel('Текст решения')).toHaveValue(
    'Двести записей читаются одним запросом.',
  );
  await form.getByLabel('Название').fill(FIXED);
  await form.getByRole('button', { name: 'Заменить решением' }).click();
  await expect(form).toHaveCount(0);

  const fixed = page.locator('li[data-decision]', { hasText: FIXED });
  await expect(fixed).toHaveAttribute('data-review', 'confirmed');
  await expect(fixed).toContainText('подтверждено');
  const fixedRef = (await fixed.getAttribute('data-decision')) ?? '';

  // Прежнее — в «Показать снятые» с плашкой «заменено» и ссылкой на новое.
  await page.getByRole('link', { name: /^Показать снятые/ }).click();
  const replaced = row(page, newRef);
  await expect(replaced).toHaveAttribute('data-status', 'superseded');
  await expect(replaced).toContainText('заменено');
  await expect(replaced.getByRole('link', { name: fixedRef })).toBeVisible();
});

for (const colorScheme of ['light', 'dark'] as const) {
  test(`вкладка «Решения» DEMO на 390 px (${colorScheme}): без прокрутки вбок и нарушений доступности`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize({ width: 390, height: 844 });

    for (const path of [
      '/projects/DEMO?tab=decisions',
      '/projects/DEMO?tab=decisions&show=unconfirmed',
      '/projects/DEMO?tab=decisions&show=removed',
      '/projects/DEMO/areas/core',
    ]) {
      await page.goto(path);
      const first = page.locator('li[data-decision]').first();
      await expect(first).toBeVisible();
      await first.locator('button[aria-expanded]').click();
      await fontsReady(page);
      expect((await new AxeBuilder({ page }).analyze()).violations, path).toEqual([]);
      expect(
        await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
        path,
      ).toBeLessThanOrEqual(0);
    }
  });
}
