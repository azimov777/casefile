import { expect, test, type APIRequestContext } from '@playwright/test';
import { readE2eToken } from './contour';

/*
 * Запись человека в знание области и ссылка на решение области (TRK-660, TRK#59).
 * Сценарий пишущий — заводит проект, область и задачу — и идёт в проекте «запись».
 * Ключ проекта несёт метку прогона: на той же базе повторный прогон заводит свой проект.
 */

const token = readE2eToken();
const RUN = Date.now().toString(36).toUpperCase();
const KEY = `K${RUN}`.slice(0, 16);
const ADDRESS = `${KEY}/know`;

async function api(
  request: APIRequestContext,
  method: 'post',
  path: string,
  data: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const response = await request[method](path, {
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect([200, 201], await response.text()).toContain(response.status());
  return ((await response.json()) as { data?: Record<string, unknown> }).data ?? {};
}

test('«Решение» на странице области записывает решение среди действующих; ссылка из задачи открывает запись области', async ({
  page,
  request,
}) => {
  await api(request, 'post', '/api/v1/projects', { key: KEY, title: `Знание ${RUN}` });
  await api(request, 'post', `/api/v1/projects/${KEY}/areas`, {
    key: 'know',
    title: 'Знание',
    description: 'Область сквозного теста знания.',
  });

  const title = `Правила пишем по вторникам, прогон ${RUN}`;
  await page.goto(`/projects/${KEY}/areas/know`);
  await expect(page.getByText('Решений у области пока нет.')).toBeVisible();

  await page.getByRole('button', { name: 'Решение', exact: true }).click();
  const form = page.getByRole('form', { name: `Запись в дело ${ADDRESS}` });
  await form.getByLabel('Решение', { exact: true }).fill(`${title}\nТак видно больше.`);
  await form.getByRole('button', { name: 'Подшить решение' }).click();
  await expect(
    page.getByRole('region', { name: `Решение в дело ${ADDRESS} подшито` }),
  ).toBeVisible();

  // Среди действующих: в списке со статусом «действует», число вкладки — единица.
  const row = page.locator('li[data-knowledge]', { hasText: title });
  await expect(row).toHaveAttribute('data-status', 'in_force');
  await expect(row.locator('[data-entry-state]')).toContainText('действует');
  await expect(
    page
      .getByRole('navigation', { name: 'Разделы области' })
      .getByRole('link', { name: /^Решения/ }),
  ).toHaveAccessibleName('Решения 1');
  const no = Number((await row.getByRole('link').first().textContent())?.split('#')[1]);
  expect(no).toBeGreaterThan(0);

  // Задача области ссылается на это решение: ссылка из шапки карточки ведёт на запись области.
  const task = await api(request, 'post', '/api/v1/tasks', {
    project: KEY,
    area: ADDRESS,
    title: `Задача по решению области ${RUN}`,
    description: 'Заведена сквозным тестом знания области.',
    decisions: [`${ADDRESS}#${no}`],
  });
  await page.goto(`/tasks/${task.key as string}`);
  await page
    .getByRole('link', { name: `${ADDRESS}#${no}`, exact: true })
    .first()
    .click();
  await expect(page).toHaveURL(new RegExp(`/projects/${KEY}/areas/know\\?entry=${no}$`));
  await expect(page.getByRole('button', { name: new RegExp(title) })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
});
