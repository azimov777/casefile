import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, motionSettled, readE2eToken } from './contour';

/*
 * Области в интерфейсе (TRK-557, TRK#16, ч. 4): человек заводит область на
 * экране проекта, ставит её задаче в карточке, и отбор `area` в списке задач
 * показывает эту задачу и не показывает задачу другой области. Задача без области
 * новой не бывает (`area_required`, TRK-677): область у неё можно сменить, но не снять.
 * Тем же условием `area` отбирает агент.
 *
 * Сценарий пишущий — заводит проект, задачи и области — и идёт в проекте «запись».
 * Ключ проекта несёт метку прогона: на той же базе повторный прогон заводит свой проект,
 * и чужие задачи в его выдачу не попадают.
 */

const token = readE2eToken();
const RUN = Date.now().toString(36).toUpperCase();
/** Ключ проекта прогона: буква и латиница с цифрами, не длиннее 16 знаков. */
const KEY = `D${RUN}`.slice(0, 16);
const AREA_TITLE = `Продвижение прогона ${RUN}`;
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
  /** Задача, которой человек поставит область. */
  chosen: string;
  /** Задача в области `base`: отбор по другой области её не показывает. */
  other: string;
  /** Задача для замеров доступности: ей область ставится запросом. */
  measured: string;
}

let ready: Promise<Seeded> | null = null;

let projectReady: Promise<void> | null = null;

/** Проект прогона — один раз на файл. Областей в нём пока нет: первую заводит человек. */
function seedProject(request: APIRequestContext): Promise<void> {
  projectReady ??= api(request, 'post', '/api/v1/projects', {
    key: KEY,
    title: `Области ${RUN}`,
  }).then(() => undefined);
  return projectReady;
}

/** Три задачи прогона в области `base` — один раз на файл, после проекта. */
async function seed(request: APIRequestContext): Promise<Seeded> {
  ready ??= seedOnce(request);
  return ready;
}

async function seedOnce(request: APIRequestContext): Promise<Seeded> {
  await seedProject(request);
  await api(
    request,
    'post',
    `/api/v1/projects/${KEY}/areas`,
    { key: 'base', title: `Основа ${RUN}`, description: 'Область задач сценария.' },
    [201, 409],
  );
  const task = async (title: string) =>
    (
      await api(request, 'post', '/api/v1/tasks', {
        project: KEY,
        area: `${KEY}/base`,
        title,
        description: 'Заведена сквозным тестом областей.',
      })
    ).key as string;
  return {
    chosen: await task(`Задача в области ${RUN}`),
    other: await task(`Задача другой области ${RUN}`),
    measured: await task(`Задача для замеров ${RUN}`),
  };
}

/** Ключи задач в таблице списка: моноширинные ячейки строк. */
function rowKey(page: Page, key: string) {
  return page.getByRole('table').getByText(key, { exact: true });
}

test('область заводится на экране проекта, ставится задаче, отбор в списке по ней', async ({
  page,
  request,
}) => {
  await seedProject(request);

  // 1. Завести область на экране проекта, вкладка «Области».
  await page.goto(`/projects/${KEY}?tab=areas`);
  const section = page.getByRole('region', { name: 'Области', exact: true });
  await expect(section.getByText('Областей у проекта пока нет.')).toBeVisible();
  await section.getByRole('button', { name: 'Новая область' }).click();
  const create = page.getByRole('dialog', { name: `Новая область в ${KEY}` });
  await create.getByLabel('Ключ').fill('promo');
  await create.getByLabel('Название').fill(AREA_TITLE);
  await create.getByLabel('Описание').fill('Каталоги, публикации и день запуска.');
  await create.getByRole('button', { name: 'Завести область' }).click();

  // Заведённая открывается своей страницей, и проект называет её в разделе.
  await expect(page).toHaveURL(new RegExp(`/projects/${KEY}/areas/promo$`));
  await expect(page.getByRole('heading', { level: 1 })).toContainText(ADDRESS);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(AREA_TITLE);
  await page.goto(`/projects/${KEY}?tab=areas`);
  await expect(section.getByText(ADDRESS, { exact: true })).toBeVisible();
  // «Обзор» называет его тоже: название ссылкой на страницу и адрес.
  await page.goto(`/projects/${KEY}`);
  const overview = page.locator(`li[data-overview-area="${ADDRESS}"]`);
  await expect(overview.getByRole('link', { name: new RegExp(AREA_TITLE) })).toHaveAttribute(
    'href',
    `/projects/${KEY}/areas/promo`,
  );

  // 2. Сменить область задачи на неё в карточке — там же, где приоритет. Задачи прогона
  // заводятся только теперь: в проекте без областей задача не заводится.
  const { chosen, other } = await seed(request);
  await page.goto(`/tasks/${chosen}`);
  await page.getByRole('button', { name: `Изменить область ${chosen}` }).click();
  const change = page.getByRole('dialog', { name: `Область ${chosen}` });
  // Область у задачи есть, и снять её нельзя: пункта «без области» в окне нет.
  await expect(change.getByRole('radio', { name: new RegExp(`Основа ${RUN}`) })).toBeChecked();
  await expect(change.getByRole('radio', { name: /Без области/ })).toHaveCount(0);
  await change.getByRole('radio', { name: new RegExp(AREA_TITLE) }).check();
  await change.getByRole('button', { name: 'Сохранить' }).click();
  await expect(change).toBeHidden();

  // Название — рядом с проектом ссылкой на страницу области, адрес — в полосе.
  const where = page.getByRole('link', { name: new RegExp(AREA_TITLE) });
  await expect(where).toHaveAttribute('href', `/projects/${KEY}/areas/promo`);
  await expect(page.getByText(ADDRESS, { exact: true })).toBeVisible();

  // Бэкенд держит то же самое: поле задачи — адрес области.
  const card = await request.get(`/api/v1/tasks/${chosen}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const pkg = (await card.json()) as { data: { task: { area: { address: string } | null } } };
  expect(pkg.data.task.area?.address).toBe(ADDRESS);

  // 3. Отбор в списке задач: по области — эта задача есть, задачи другой области нет.
  await page.goto(`/tasks?project=${KEY}`);
  await expect(rowKey(page, chosen)).toBeVisible();
  await expect(rowKey(page, other)).toBeVisible();

  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  const field = page.getByLabel('Область', { exact: true });
  await field.selectOption(ADDRESS);
  await expect(page).toHaveURL(new RegExp(`[?&]area=${encodeURIComponent(ADDRESS)}(&|$)`));
  await expect(rowKey(page, chosen)).toBeVisible();
  await expect(rowKey(page, other)).toHaveCount(0);
  await expect(page.getByText(`область ${ADDRESS}`)).toBeVisible();

  // Другая область — наоборот.
  await field.selectOption(`${KEY}/base`);
  await expect(rowKey(page, other)).toBeVisible();
  await expect(rowKey(page, chosen)).toHaveCount(0);

  // Отбор держится в адресе: перезагрузка и пересланная ссылка показывают то же.
  await page.goto(`/tasks?project=${KEY}&area=${encodeURIComponent(ADDRESS)}`);
  await expect(rowKey(page, chosen)).toBeVisible();
  await expect(rowKey(page, other)).toHaveCount(0);
});

for (const colorScheme of ['light', 'dark'] as const) {
  test(`доступность областей: ${colorScheme}, 390px`, async ({ page, request }) => {
    const { measured } = await seed(request);
    // Своя область замеров: сценарий выше мог не пройти, а этот от него не зависит.
    await api(
      request,
      'post',
      `/api/v1/projects/${KEY}/areas`,
      { key: 'measure', title: `Замеры ${RUN}`, description: 'Область для замеров.' },
      [201, 409],
    );
    await api(request, 'patch', `/api/v1/tasks/${measured}`, { area: `${KEY}/measure` });
    // Атрибут — чтобы замер видел и строку атрибута; то же значение повторно ничего не меняет.
    await api(request, 'put', `/api/v1/projects/${KEY}/areas/measure/attributes/channel`, {
      value: 'reddit',
    });
    await page.emulateMedia({ colorScheme });
    await page.setViewportSize({ width: 390, height: 844 });

    const pages = [
      {
        path: `/projects/${KEY}?tab=areas`,
        ready: page.getByRole('region', { name: 'Области', exact: true }),
      },
      {
        path: `/projects/${KEY}/areas/measure`,
        ready: page.getByRole('region', { name: 'Решения области' }),
      },
      {
        path: `/projects/${KEY}/areas/measure?tab=case`,
        ready: page.getByRole('region', { name: 'Дело области' }),
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

    // Окно выбора области в карточке — тоже без нарушений.
    await page.getByRole('button', { name: `Изменить область ${measured}` }).click();
    const dialog = page.getByRole('dialog', { name: `Область ${measured}` });
    await expect(dialog.getByRole('radio', { name: new RegExp(`Замеры ${RUN}`) })).toBeChecked();
    // Окно выезжает с переходом: замер контраста посреди него мерил бы смешанные цвета.
    await motionSettled(dialog);
    expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  });
}

test('атрибут области: «Изменить» и «Снять» — в открытой истории, с причиной', async ({
  page,
  request,
}) => {
  await seed(request);
  await api(
    request,
    'post',
    `/api/v1/projects/${KEY}/areas`,
    { key: 'history', title: `История ${RUN}`, description: 'Область для правки атрибута.' },
    [201, 409],
  );
  await api(request, 'put', `/api/v1/projects/${KEY}/areas/history/attributes/channel`, {
    value: 'reddit',
  });
  await page.goto(`/projects/${KEY}/areas/history?tab=attributes`);
  const attributes = page.getByRole('region', { name: 'Атрибуты' });
  await expect(attributes.getByText('reddit')).toBeVisible();

  // В закрытом списке кнопок правки нет.
  await expect(attributes.getByRole('button', { name: 'Изменить атрибут channel' })).toHaveCount(0);
  await expect(attributes.getByRole('button', { name: 'Снять атрибут channel' })).toHaveCount(0);

  await attributes.getByRole('button', { name: '▸ channel', exact: true }).click();
  const history = page.getByRole('region', { name: 'История атрибута channel' });
  await history.getByRole('button', { name: 'Изменить атрибут channel' }).click();
  const edit = page.getByRole('dialog', { name: 'Атрибут channel' });
  await edit.getByLabel('Значение').fill('hacker news');
  await edit.getByLabel('Причина').fill(`Другая площадка ${RUN}`);
  await edit.getByRole('button', { name: 'Сохранить' }).click();
  await expect(edit).toBeHidden();
  // Значение стоит в строке и в карточке истории: берём строку, она первая.
  await expect(attributes.getByText('hacker news').first()).toBeVisible();

  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await fontsReady(page);
    expect((await new AxeBuilder({ page }).analyze()).violations, `${width}px`).toEqual([]);
  }

  await history.getByRole('button', { name: 'Снять атрибут channel' }).click();
  const remove = page.getByRole('alertdialog', { name: 'Снять атрибут channel?' });
  await remove.getByLabel('Причина').fill(`Площадка не нужна ${RUN}`);
  await remove.getByRole('button', { name: 'Снять атрибут' }).click();
  await expect(remove).toBeHidden();
  await expect(attributes.locator('li[data-attribute="channel"]')).toHaveCount(0);
});
