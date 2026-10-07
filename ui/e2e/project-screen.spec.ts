import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, side } from './contour';

/*
 * Экран проекта на чтение (UI-174; вкладки — TRK-618, решение TRK#46): вход из панели,
 * шапка, вкладки «Обзор», «Решения», «Атрибуты», «Направления», «Дело» в адресе `?tab=`,
 * атрибуты с историей, опись дела проекта с телом по клику и ссылка `TRK#7` из записи
 * задачи, которая открывает «Дело» сама. «Назад» браузера ходит по вкладкам; на каждой
 * вкладке — `axe` и отсутствие прокрутки вбок на двух ширинах, у страницы направления тоже.
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
/**
 * Кнопка раскрытия истории атрибута: её имя — знак состояния псевдоэлементом и имя
 * атрибута. Подстрокой `REPO` искать нельзя: с UI-175 у строки есть «Изменить атрибут
 * REPO» и «Снять атрибут REPO».
 */
const REPO_TOGGLE = new RegExp(`^[▸▾] ${REPO}$`);
const DESCRIPTION = 'Бэкенд трекера: REST для человека и MCP для агентов.';
/** Направление проекта `TRK` для замеров его страницы на тех же ширинах. */
const DIRECTION = 'TRK/screen';

/** Полоса вкладок экрана проекта или страницы направления. */
function tabs(page: Page, name = 'Разделы проекта'): Locator {
  return page.getByRole('navigation', { name });
}

/** Вкладка по началу подписи: число после неё зависит от прежних прогонов на той же базе. */
function tab(page: Page, label: string, strip = 'Разделы проекта'): Locator {
  return tabs(page, strip).getByRole('link', { name: new RegExp(`^${label}`) });
}

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
  // Направление — чтобы «Обзор» и вкладка «Направления» замерялись не пустыми, а его
  // страница — с атрибутом и записью в деле.
  await api(
    request,
    'post',
    '/api/v1/projects/TRK/directions',
    { key: 'screen', title: 'Экран проекта', description: 'Направление сквозного теста экрана.' },
    [201, 409],
  );
  await api(
    request,
    'put',
    `/api/v1/projects/${DIRECTION.replace('/', '/directions/')}/attributes/channel`,
    {
      value: 'reddit',
    },
  );
  return { decisionNo, taskKey };
}

test('экран проекта: вход из панели, шапка, вкладки, опись с телом, ссылка TRK#N, история атрибута', async ({
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
  // Без параметра открыт «Обзор»: свежее в деле, без атрибутов и описи.
  await expect(tab(page, 'Обзор')).toHaveAttribute('aria-current', 'true');
  await expect(page.getByRole('region', { name: 'Последнее в деле' })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Атрибуты' })).toHaveCount(0);

  // «Атрибуты» — вкладкой: значение на месте.
  await tab(page, 'Атрибуты').click();
  await expect(page).toHaveURL(/\/projects\/TRK\?tab=attributes$/);
  const attributes = page.getByRole('region', { name: 'Атрибуты' });
  await expect(attributes.getByRole('button', { name: REPO_TOGGLE })).toBeVisible();
  await expect(attributes.getByText('github.com/azimov777/casefile')).toBeVisible();

  // Опись дела — вкладкой «Дело»: клик по записи показывает тело и пишет номер в адрес.
  await tab(page, 'Дело').click();
  await expect(page).toHaveURL(/\/projects\/TRK\?tab=case$/);
  const decisionButton = page.getByRole('table').getByRole('button', { name: DECISION });
  await decisionButton.click();
  await expect(decisionButton).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByText('расходится с')).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`[?&]entry=${decisionNo}(&|$)`));

  // (а) Ссылка `TRK#N` в записи задачи ведёт на запись проекта: «Дело» открыто само,
  // запись раскрыта — адрес вкладки не называет.
  await page.goto(`/tasks/${taskKey}`);
  await page.getByRole('button', { name: `Ссылка на решение проекта, прогон ${RUN}` }).click();
  await page.getByRole('link', { name: `TRK#${decisionNo}`, exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/TRK\\?entry=${decisionNo}$`));
  await expect(tab(page, 'Дело')).toHaveAttribute('aria-current', 'true');
  await expect(page.getByRole('table').getByRole('button', { name: DECISION })).toHaveAttribute(
    'aria-expanded',
    'true',
  );
  await expect(page.getByText('расходится с')).toBeVisible();

  // История атрибута: заведение и правка — прежнее и новое значение и причина.
  await tab(page, 'Атрибуты').click();
  await page
    .getByRole('region', { name: 'Атрибуты' })
    .getByRole('button', { name: REPO_TOGGLE })
    .click();
  const history = page.getByRole('region', { name: `История атрибута ${REPO}` });
  await expect(history.getByRole('article')).toHaveCount(2);
  const change = history.locator('article[data-type="attribute_changed"]');
  await expect(change.locator('[data-side="was"]')).toContainText('github.com/old/casefile');
  await expect(change.locator('[data-side="now"]')).toContainText('github.com/azimov777/casefile');
  await expect(change).toContainText('Репозиторий переехал в организацию');
  await expect(page).toHaveURL(new RegExp(`[?&]attribute=${REPO}(&|$)`));
});

test('«Назад» браузера после смены вкладки возвращает прежнюю вкладку, раскрытие записи истории не пишет', async ({
  page,
  request,
}) => {
  const { decisionNo } = await seed(request);

  await page.goto('/projects/TRK');
  await expect(tab(page, 'Обзор')).toHaveAttribute('aria-current', 'true');

  await tab(page, 'Решения').click();
  await expect(page).toHaveURL(/\/projects\/TRK\?tab=decisions$/);
  await expect(page.getByRole('region', { name: 'Решения', exact: true })).toBeVisible();

  await tab(page, 'Дело').click();
  await expect(page).toHaveURL(/\/projects\/TRK\?tab=case$/);
  // Раскрытие записи — `replace`: «Назад» после него ведёт не к свёрнутой описи, а на
  // прежнюю вкладку.
  await page.getByRole('table').getByRole('button', { name: DECISION }).click();
  await expect(page).toHaveURL(new RegExp(`\\?tab=case&entry=${decisionNo}$`));

  await page.goBack();
  await expect(page).toHaveURL(/\/projects\/TRK\?tab=decisions$/);
  await expect(tab(page, 'Решения')).toHaveAttribute('aria-current', 'true');
  await expect(page.getByRole('region', { name: 'Решения', exact: true })).toBeVisible();

  await page.goBack();
  await expect(page).toHaveURL(/\/projects\/TRK$/);
  await expect(tab(page, 'Обзор')).toHaveAttribute('aria-current', 'true');
  await expect(page.getByRole('region', { name: 'Последнее в деле' })).toBeVisible();

  await page.goForward();
  await expect(page).toHaveURL(/\/projects\/TRK\?tab=decisions$/);
  await expect(tab(page, 'Решения')).toHaveAttribute('aria-current', 'true');
});

/** Вкладки экрана проекта и страницы направления: адрес и то, что на ней дорисовано. */
function screens(page: Page, decisionNo: number): { name: string; path: string; ready: Locator }[] {
  return [
    {
      name: 'Обзор',
      path: '/projects/TRK',
      ready: page.getByRole('region', { name: 'Последнее в деле' }).getByRole('listitem').first(),
    },
    {
      name: 'Решения',
      path: '/projects/TRK?tab=decisions',
      ready: page.getByRole('region', { name: 'Решения', exact: true }),
    },
    {
      // Атрибут раскрыт адресом — замер видит и историю.
      name: 'Атрибуты',
      path: `/projects/TRK?attribute=${REPO}`,
      ready: page
        .getByRole('region', { name: `История атрибута ${REPO}` })
        .getByRole('article')
        .nth(1),
    },
    {
      name: 'Направления',
      path: '/projects/TRK?tab=directions',
      ready: page.locator(`li[data-direction-row="${DIRECTION}"]`),
    },
    {
      // Запись раскрыта адресом — замер видит и тело.
      name: 'Дело',
      path: `/projects/TRK?entry=${decisionNo}`,
      ready: page.getByText('расходится с'),
    },
    {
      name: 'направление: Дело',
      path: '/projects/TRK/directions/screen',
      ready: page.getByRole('region', { name: 'Дело направления' }).getByRole('table'),
    },
    {
      name: 'направление: Атрибуты',
      path: '/projects/TRK/directions/screen?tab=attributes',
      ready: page.getByRole('region', { name: 'Атрибуты' }).getByText('reddit'),
    },
  ];
}

test('дело проекта: фильтр по типу note — в описи только заметки, type=note в адресе, перезагрузка сохраняет', async ({
  page,
  request,
}) => {
  await seed(request);
  const noteTitle = `Заметка для отбора по типу, прогон ${RUN}`;
  await api(request, 'post', '/api/v1/projects/TRK/entries', {
    type: 'note',
    title: noteTitle,
    body: 'Заметка проекта для сквозного сценария фильтра.',
  });

  await page.goto('/projects/TRK?tab=case');
  const table = page.getByRole('table');
  await expect(table.getByRole('button', { name: DECISION })).toBeVisible();

  await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
  await page
    .getByRole('dialog', { name: 'Типы записей' })
    .getByRole('button', { name: 'note', exact: true })
    .click();
  await page.keyboard.press('Escape');

  await expect(page).toHaveURL(/[?&]type=note(&|$)/);
  await expect(table.getByRole('button', { name: noteTitle })).toBeVisible();
  await expect(table.getByRole('button', { name: DECISION })).toHaveCount(0);
  // Заведение проекта — запись другого типа: под отбором её в описи нет.
  await expect(table.getByRole('button', { name: /^Project created$|Проект заведён/ })).toHaveCount(
    0,
  );

  await page.reload();
  await expect(page).toHaveURL(/[?&]type=note(&|$)/);
  await expect(table.getByRole('button', { name: noteTitle })).toBeVisible();
  await expect(table.getByRole('button', { name: DECISION })).toHaveCount(0);
});

for (const colorScheme of ['light', 'dark'] as const) {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test(`каждая вкладка без нарушений axe и без прокрутки вбок: ${colorScheme}, ${viewport.width}px`, async ({
      page,
      request,
    }) => {
      const { decisionNo } = await seed(request);
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize(viewport);

      for (const { name, path, ready } of screens(page, decisionNo)) {
        await page.goto(path);
        await expect(ready, name).toBeVisible();
        await fontsReady(page);

        const report = await new AxeBuilder({ page }).analyze();
        expect(report.violations, name).toEqual([]);

        // Горизонтальной прокрутки нет ни на какой ширине, на телефоне — особенно: полоса
        // вкладок прокручивается сама, страница — нет.
        const over = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(over, name).toBeLessThanOrEqual(0);
      }

      // Меню «⋯» открытым — тоже без нарушений и без прокрутки вбок.
      await page.goto('/projects/TRK');
      await page.getByRole('button', { name: 'Действия с проектом TRK' }).click();
      await expect(page.getByRole('button', { name: 'В архив', exact: true })).toBeVisible();
      await fontsReady(page);
      expect((await new AxeBuilder({ page }).analyze()).violations, 'меню').toEqual([]);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        ),
        'меню',
      ).toBeLessThanOrEqual(0);
    });
  }
}
