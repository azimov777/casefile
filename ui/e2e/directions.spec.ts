import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, motionSettled, readE2eToken } from './contour';

/*
 * Направления в интерфейсе (TRK-557, TRK#16, ч. 4): человек заводит направление на
 * экране проекта, ставит его задаче в карточке, и отбор `direction` в списке задач
 * показывает эту задачу и не показывает задачу без направления; «без направления» —
 * наоборот. Тем же условием `direction` отбирает агент.
 *
 * Сценарий пишущий — заводит проект, задачи и направления — и идёт в проекте «запись».
 * Ключ проекта несёт метку прогона: на той же базе повторный прогон заводит свой проект,
 * и чужие задачи в его выдачу не попадают.
 */

const token = readE2eToken();
const RUN = Date.now().toString(36).toUpperCase();
/** Ключ проекта прогона: буква и латиница с цифрами, не длиннее 16 знаков. */
const KEY = `D${RUN}`.slice(0, 16);
const DIRECTION_TITLE = `Продвижение прогона ${RUN}`;
const ADDRESS = `${KEY}/promo`;

async function api(
  request: APIRequestContext,
  method: 'post' | 'patch' | 'put',
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
  /** Задача, которой человек поставит направление. */
  chosen: string;
  /** Задача без направления: отбор по направлению её не показывает. */
  other: string;
  /** Задача для замеров доступности: ей направление ставится запросом. */
  measured: string;
}

let ready: Promise<Seeded> | null = null;

/** Проект прогона и три его задачи — один раз на файл. */
function seed(request: APIRequestContext): Promise<Seeded> {
  ready ??= seedOnce(request);
  return ready;
}

async function seedOnce(request: APIRequestContext): Promise<Seeded> {
  await api(request, 'post', '/api/v1/projects', { key: KEY, title: `Направления ${RUN}` });
  const task = async (title: string) =>
    (
      await api(request, 'post', '/api/v1/tasks', {
        project: KEY,
        title,
        description: 'Заведена сквозным тестом направлений.',
      })
    ).key as string;
  return {
    chosen: await task(`Задача в направлении ${RUN}`),
    other: await task(`Задача без направления ${RUN}`),
    measured: await task(`Задача для замеров ${RUN}`),
  };
}

/** Ключи задач в таблице списка: моноширинные ячейки строк. */
function rowKey(page: Page, key: string) {
  return page.getByRole('table').getByText(key, { exact: true });
}

test('направление заводится на экране проекта, ставится задаче, отбор в списке по нему', async ({
  page,
  request,
}) => {
  const { chosen, other } = await seed(request);

  // 1. Завести направление на экране проекта, вкладка «Направления».
  await page.goto(`/projects/${KEY}?tab=directions`);
  const section = page.getByRole('region', { name: 'Направления', exact: true });
  await expect(section.getByText('Направлений у проекта пока нет.')).toBeVisible();
  await section.getByRole('button', { name: 'Новое направление' }).click();
  const create = page.getByRole('dialog', { name: `Новое направление в ${KEY}` });
  await create.getByLabel('Ключ').fill('promo');
  await create.getByLabel('Название').fill(DIRECTION_TITLE);
  await create.getByLabel('Описание').fill('Каталоги, публикации и день запуска.');
  await create.getByRole('button', { name: 'Завести направление' }).click();

  // Заведённое открывается своей страницей, и проект называет его в разделе.
  await expect(page).toHaveURL(new RegExp(`/projects/${KEY}/directions/promo$`));
  await expect(page.getByRole('heading', { level: 1 })).toContainText(ADDRESS);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(DIRECTION_TITLE);
  await page.goto(`/projects/${KEY}?tab=directions`);
  await expect(section.getByText(ADDRESS, { exact: true })).toBeVisible();
  // «Обзор» называет его тоже: название ссылкой на страницу и адрес.
  await page.goto(`/projects/${KEY}`);
  const overview = page.locator(`li[data-overview-direction="${ADDRESS}"]`);
  await expect(overview.getByRole('link', { name: new RegExp(DIRECTION_TITLE) })).toHaveAttribute(
    'href',
    `/projects/${KEY}/directions/promo`,
  );

  // 2. Поставить его задаче в карточке — там же, где приоритет.
  await page.goto(`/tasks/${chosen}`);
  await page.getByRole('button', { name: `Изменить направление ${chosen}` }).click();
  const change = page.getByRole('dialog', { name: `Направление ${chosen}` });
  await expect(change.getByRole('radio', { name: /Без направления/ })).toBeChecked();
  await change.getByRole('radio', { name: new RegExp(DIRECTION_TITLE) }).check();
  await change.getByRole('button', { name: 'Сохранить' }).click();
  await expect(change).toBeHidden();

  // Название — рядом с проектом ссылкой на страницу направления, адрес — в полосе.
  const where = page.getByRole('link', { name: new RegExp(DIRECTION_TITLE) });
  await expect(where).toHaveAttribute('href', `/projects/${KEY}/directions/promo`);
  await expect(page.getByText(ADDRESS, { exact: true })).toBeVisible();

  // Бэкенд держит то же самое: поле задачи — адрес направления.
  const card = await request.get(`/api/v1/tasks/${chosen}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const pkg = (await card.json()) as { data: { task: { direction: { address: string } | null } } };
  expect(pkg.data.task.direction?.address).toBe(ADDRESS);

  // 3. Отбор в списке задач: по направлению — эта задача есть, задачи без направления нет.
  await page.goto(`/tasks?project=${KEY}`);
  await expect(rowKey(page, chosen)).toBeVisible();
  await expect(rowKey(page, other)).toBeVisible();

  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  const field = page.getByLabel('Направление', { exact: true });
  await field.selectOption(ADDRESS);
  await expect(page).toHaveURL(new RegExp(`[?&]direction=${encodeURIComponent(ADDRESS)}(&|$)`));
  await expect(rowKey(page, chosen)).toBeVisible();
  await expect(rowKey(page, other)).toHaveCount(0);
  await expect(page.getByText(`направление ${ADDRESS}`)).toBeVisible();

  // «Без направления» — наоборот: та же выдача условием `direction: empty()`.
  await field.selectOption('empty()');
  await expect(page).toHaveURL(/[?&]direction=empty%28%29(&|$)/);
  await expect(rowKey(page, other)).toBeVisible();
  await expect(rowKey(page, chosen)).toHaveCount(0);

  // Отбор держится в адресе: перезагрузка и пересланная ссылка показывают то же.
  await page.goto(`/tasks?project=${KEY}&direction=${encodeURIComponent(ADDRESS)}`);
  await expect(rowKey(page, chosen)).toBeVisible();
  await expect(rowKey(page, other)).toHaveCount(0);
});

for (const colorScheme of ['light', 'dark'] as const) {
  test(`доступность направлений: ${colorScheme}, 390px`, async ({ page, request }) => {
    const { measured } = await seed(request);
    // Своё направление замеров: сценарий выше мог не пройти, а этот от него не зависит.
    await api(
      request,
      'post',
      `/api/v1/projects/${KEY}/directions`,
      { key: 'measure', title: `Замеры ${RUN}`, description: 'Направление для замеров.' },
      [201, 409],
    );
    await api(request, 'patch', `/api/v1/tasks/${measured}`, { direction: `${KEY}/measure` });
    // Атрибут — чтобы замер видел и строку атрибута; то же значение повторно ничего не меняет.
    await api(request, 'put', `/api/v1/projects/${KEY}/directions/measure/attributes/channel`, {
      value: 'reddit',
    });
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize({ width: 390, height: 844 });

    const pages = [
      {
        path: `/projects/${KEY}?tab=directions`,
        ready: page.getByRole('region', { name: 'Направления', exact: true }),
      },
      {
        path: `/projects/${KEY}/directions/measure`,
        ready: page.getByRole('region', { name: 'Дело направления' }),
      },
      { path: `/tasks/${measured}`, ready: page.getByText(`${KEY}/measure`, { exact: true }) },
    ];
    for (const { path, ready: shown } of pages) {
      await page.goto(path);
      await expect(shown).toBeVisible();
      await fontsReady(page);
      expect((await new AxeBuilder({ page }).analyze()).violations, path).toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
        path,
      ).toBeLessThanOrEqual(0);
    }

    // Окно выбора направления в карточке — тоже без нарушений.
    await page.getByRole('button', { name: `Изменить направление ${measured}` }).click();
    const dialog = page.getByRole('dialog', { name: `Направление ${measured}` });
    await expect(dialog.getByRole('radio', { name: new RegExp(`Замеры ${RUN}`) })).toBeChecked();
    // Окно выезжает с переходом: замер контраста посреди него мерил бы смешанные цвета.
    await motionSettled(dialog);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  });
}
