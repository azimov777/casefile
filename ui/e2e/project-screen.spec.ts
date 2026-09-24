import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext } from '@playwright/test';
import { fontsReady, readE2eToken, side } from './contour';

/*
 * Экран проекта на чтение (UI-174): вход из панели, карточка, атрибуты с историей,
 * опись дела проекта с телом по клику и ссылка `TRK#7` из записи задачи.
 *
 * Сценарий пишущий — заводит проект `TRK`, его атрибуты и записи, задачу в нём — и
 * потому идёт в проекте «запись», после читающих, которые считают проекты панели.
 * Имена атрибутов и заголовки несут метку прогона: на той же базе повторный прогон
 * застаёт прежние, а история атрибута обязана состоять ровно из своих записей.
 */

const token = readE2eToken();
const RUN = Date.now().toString(36);
const REPO = `repo-${RUN}`;
const DECISION = `Главная ветка — main, прогон ${RUN}`;
const DESCRIPTION = 'Бэкенд трекера: REST для человека и MCP для агентов.';

async function api(
  request: APIRequestContext,
  method: 'post' | 'put' | 'patch',
  path: string,
  data: Record<string, unknown>,
  expected: number[] = [200, 201],
): Promise<Record<string, unknown>> {
  const response = await request[method](path, {
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect(expected, await response.text()).toContain(response.status());
  return ((await response.json()) as { data?: Record<string, unknown> }).data ?? {};
}

interface Seeded {
  /** Номер решения в деле проекта: на него ссылается запись задачи. */
  decisionNo: number;
  taskKey: string;
}

let ready: Promise<Seeded> | null = null;

/**
 * Проект `TRK` с описанием, атрибутом, заведённым и изменённым, решением и задачей —
 * один раз на файл: повторная правка атрибута тем же значением записи не подшивает, а
 * история обязана быть ровно из двух записей.
 */
function seed(request: APIRequestContext): Promise<Seeded> {
  ready ??= seedOnce(request);
  return ready;
}

async function seedOnce(request: APIRequestContext): Promise<Seeded> {
  await api(request, 'post', '/api/v1/projects', { key: 'TRK', title: 'Бэкенд' }, [201, 409]);
  await api(request, 'patch', '/api/v1/projects/TRK', { description: DESCRIPTION });
  await api(request, 'put', `/api/v1/projects/TRK/attributes/${REPO}`, {
    value: 'github.com/old/casefile',
  });
  await api(request, 'put', `/api/v1/projects/TRK/attributes/${REPO}`, {
    value: 'github.com/azimov777/casefile',
    reason: 'Репозиторий переехал в организацию',
  });
  const decision = await api(request, 'post', '/api/v1/projects/TRK/entries', {
    type: 'decision',
    title: DECISION,
    body: 'Вторая долгоживущая ветка расходится с `main` молча.',
  });
  const decisionNo = decision.no as number;

  const task = await api(request, 'post', '/api/v1/tasks', {
    project: 'TRK',
    title: `Задача со ссылкой на дело проекта, прогон ${RUN}`,
    description: 'Заведена сквозным тестом экрана проекта.',
  });
  const taskKey = task.key as string;
  await api(request, 'post', `/api/v1/tasks/${taskKey}/entries`, {
    type: 'note',
    title: `Ссылка на решение проекта, прогон ${RUN}`,
    body: `Опираюсь на решение TRK#${decisionNo}.`,
  });
  return { decisionNo, taskKey };
}

test('экран проекта: вход из панели, карточка, опись с телом, ссылка TRK#N, история атрибута', async ({
  page,
  request,
}) => {
  const { decisionNo, taskKey } = await seed(request);

  // Из панели — одним движением: знак рядом со строкой проекта.
  await page.goto('/tasks?project=TRK');
  await side(page).getByRole('link', { name: 'О проекте TRK' }).click();
  await expect(page).toHaveURL(/\/projects\/TRK$/);

  const title = page.getByRole('heading', { level: 1 });
  await expect(title).toContainText('TRK');
  await expect(title).toContainText('Бэкенд');
  await expect(page.getByText(DESCRIPTION)).toBeVisible();
  await expect(side(page).getByRole('link', { name: /^TRK/ })).toHaveAttribute(
    'aria-current',
    'page',
  );

  const attributes = page.getByRole('region', { name: 'Атрибуты' });
  await expect(attributes.getByRole('button', { name: REPO })).toBeVisible();
  await expect(attributes.getByText('github.com/azimov777/casefile')).toBeVisible();

  // Опись дела: клик по записи показывает тело и пишет номер в адрес.
  const decisionButton = page.getByRole('table').getByRole('button', { name: DECISION });
  await decisionButton.click();
  await expect(decisionButton).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByText('расходится с')).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`[?&]entry=${decisionNo}(&|$)`));

  // Ссылка `TRK#N` в записи задачи ведёт на запись проекта, раскрытую.
  await page.goto(`/tasks/${taskKey}`);
  await page.getByRole('button', { name: `Ссылка на решение проекта, прогон ${RUN}` }).click();
  await page.getByRole('link', { name: `TRK#${decisionNo}`, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/TRK\\?entry=${decisionNo}$`));
  await expect(page.getByRole('table').getByRole('button', { name: DECISION })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await expect(page.getByText('расходится с')).toBeVisible();

  // История атрибута: заведение и правка — прежнее и новое значение и причина.
  await page.getByRole('region', { name: 'Атрибуты' }).getByRole('button', { name: REPO }).click();
  const history = page.getByRole('region', { name: `История атрибута ${REPO}` });
  await expect(history.getByRole('article')).toHaveCount(2);
  const change = history.locator('article[data-type="attribute_changed"]');
  await expect(change.locator('[data-side="was"]')).toContainText('github.com/old/casefile');
  await expect(change.locator('[data-side="now"]')).toContainText('github.com/azimov777/casefile');
  await expect(change).toContainText('Репозиторий переехал в организацию');
  await expect(page).toHaveURL(new RegExp(`[?&]attribute=${REPO}(&|$)`));
});

for (const colorScheme of ['light', 'dark'] as const) {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test(`доступность экрана проекта: ${colorScheme}, ${viewport.width}px`, async ({
      page,
      request,
    }) => {
      const { decisionNo } = await seed(request);
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize(viewport);

      // Всё раскрыто сразу — адрес держит и историю атрибута, и тело записи.
      await page.goto(`/projects/TRK?attribute=${REPO}&entry=${decisionNo}`);
      await expect(
        page.getByRole('region', { name: `История атрибута ${REPO}` }).getByRole('article'),
      ).toHaveCount(2);
      await expect(page.getByText('расходится с')).toBeVisible();
      await fontsReady(page);

      const report = await new AxeBuilder({ page }).analyze();
      expect(report.violations).toEqual([]);

      // Горизонтальной прокрутки нет ни на какой ширине, на телефоне — особенно.
      const over = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(over).toBeLessThanOrEqual(0);
    });
  }
}
