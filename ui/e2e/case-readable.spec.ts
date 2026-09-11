import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/** Английские заготовки трекера: в русском интерфейсе их быть не должно нигде. */
const ENGLISH = [
  'Task created',
  'Status changed',
  'Section changed',
  'Field changed',
  'Assignee changed',
  'Link added',
  'Link removed',
  'Answer to',
  'Verdict on',
];

/** Причина перехода в три абзаца: свободный текст, который нельзя терять. */
const REASON = [
  'Возвращаю задачу: задание неполно и по нему нельзя работать.',
  'Раздел «выход» называет артефакт, которого нет в контракте, а обзорные проверки ссылаются на признак, отсутствующий в выдаче.',
  'Прошу дописать оба места и вернуть в работу; всё остальное в задании годится и переписывать его не нужно.',
].join('\n\n');

const LONG_GOAL = Array.from(
  { length: 8 },
  (_, index) => `Строка ${index + 1} прежней цели, которую правка обязана сохранить целиком.`,
).join('\n\n');

async function api(
  request: APIRequestContext,
  method: 'post' | 'patch',
  path: string,
  data: Record<string, unknown>,
  expected = 200,
): Promise<Record<string, unknown>> {
  const response = await request[method](path, {
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect(response.status(), await response.text()).toBe(expected);
  return ((await response.json()) as { data: Record<string, unknown> }).data;
}

/**
 * Задача, в деле которой есть все роды служебных записей: заведение, две правки
 * разделов, смена исполнителя, переход с причиной в три абзаца, связь и её снятие.
 *
 * Заводится один раз на файл и только недостающее: упавший сценарий выбрасывает воркер
 * вместе с памятью модуля (`docs/notes/testing.md`).
 */
let ready: Promise<string> | null = null;

/**
 * Чем сценарий узнаёт свою же задачу между прогонами. Раньше это была машинная метка
 * `tags`, снятая вместе со всей механикой (UI-41); теперь — фраза из описания, а находит
 * её отбор `text`: он ищет в названии и в описании сразу.
 *
 * Именно фраза, а не вставленное в скобках слово: односложную метку тут держало то, что
 * структурный отбор `text` отвергал значение из двух слов (`422 invalid_search_query`),
 * и это ограничение снято (TRK-21). Фраза обязана оставаться уникальной в очереди DEMO.
 */
const MARKER = 'ради читаемости дела';

function seed(request: APIRequestContext): Promise<string> {
  ready ??= (async () => {
    const existing = await request.get(
      `/api/v1/tasks?queue=DEMO&text=${encodeURIComponent(MARKER)}&fields=title`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const found = ((await existing.json()) as { data: { key: string }[] }).data;
    if (found.length > 0) return (found[0] as { key: string }).key;

    const task = await api(
      request,
      'post',
      '/api/v1/tasks',
      {
        queue: 'DEMO',
        title: 'Дело со служебными записями всех родов',
        description: `Заведена сквозным тестом ${MARKER}.`,
        goal: LONG_GOAL,
        context: 'контекст',
        constraints: 'ограничения',
        output: 'выход',
        checks: ['первая проверка', 'вторая проверка'],
      },
      201,
    );
    const key = task.key as string;

    // Правка раздела: прежнее и новое значения длинные, и оба обязаны остаться целыми.
    await api(request, 'patch', `/api/v1/tasks/${key}`, {
      goal: `${LONG_GOAL}\n\nИ ещё абзац, дописанный правкой.`,
      assignee: 'owner',
    });

    const other = await api(
      request,
      'post',
      '/api/v1/tasks',
      {
        queue: 'DEMO',
        title: 'Вторая сторона связи для дела',
        description: 'Заведена сквозным тестом.',
      },
      201,
    );

    await api(
      request,
      'post',
      `/api/v1/tasks/${key}/links`,
      { kind: 'relates', other: other.key },
      201,
    );
    await api(request, 'post', `/api/v1/tasks/${key}/transition`, { to: 'open' });
    await api(request, 'post', `/api/v1/tasks/${key}/transition`, {
      to: 'backlog',
      reason: REASON,
    });

    return key;
  })();

  return ready;
}

/** Суммарная высота служебных записей ленты. */
async function serviceHeight(page: Page): Promise<number> {
  return page.evaluate(() => {
    const service = new Set([
      'created',
      'status_changed',
      'section_changed',
      'field_changed',
      'assignee_changed',
      'link_added',
      'link_removed',
    ]);
    return Array.from(document.querySelectorAll('article[data-type]'))
      .filter((node) => service.has(node.getAttribute('data-type') ?? ''))
      .reduce((total, node) => total + node.getBoundingClientRect().height, 0);
  });
}

test.describe('дело читается по-русски', () => {
  test('ссылка на запись стоит на одном месте в каждой строке', async ({ page, request }) => {
    test.setTimeout(120_000);
    const key = await seed(request);
    await silenceJournal(page);

    await page.goto(`/tasks/${key}/case`);
    await expect(page.getByRole('article').first()).toBeVisible();
    await fontsReady(page);

    // Ссылку копируют, чтобы сослаться из другой задачи (решение Д15). Если она
    // едет вправо на разную длину, её каждый раз ищут глазами заново.
    const rights = await page.evaluate(() =>
      Array.from(document.querySelectorAll('article'))
        .map((card) => card.querySelector('button[type="button"]'))
        .filter((node): node is HTMLElement => node !== null)
        .map((node) => Math.round(node.getBoundingClientRect().right * 10) / 10),
    );

    expect(rights.length).toBeGreaterThan(3);
    expect(Math.max(...rights) - Math.min(...rights)).toBeLessThanOrEqual(1);
  });

  test.use({ viewport: { width: 1440, height: 900 } });

  test('ни лента, ни опись не говорят по-английски', async ({ page, request }) => {
    const key = await seed(request);
    await silenceJournal(page);

    for (const path of [`/tasks/${key}/case`, `/tasks/${key}`]) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toContainText(key);

      const shown = await page.evaluate(() => document.body.innerText);
      for (const english of ENGLISH) {
        expect(
          shown,
          `${path}: на экране осталась английская заготовка «${english}»`,
        ).not.toContain(english);
      }
    }

    // Идентификаторы контракта при этом на месте и не переведены.
    await page.goto(`/tasks/${key}/case`);
    await expect(page.getByText('Правка раздела').first()).toBeVisible();
    await expect(
      page
        .locator('code')
        .filter({ hasText: /^goal$/ })
        .first(),
    ).toBeVisible();
  });

  test('длинное содержание служебной записи доступно целиком', async ({ page, request }) => {
    const key = await seed(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}/case`);

    // Причина перехода в три абзаца: заголовок говорит, что она есть, а текст виден
    // целиком — ни многоточий, ни потолка высоты.
    const reason = page.locator('article').filter({ hasText: 'Возвращаю задачу' }).first();
    await expect(reason).toBeVisible();
    for (const paragraph of REASON.split('\n\n')) {
      await expect(reason).toContainText(paragraph);
    }

    // Сравнение разделов: обе стороны целиком, включая дописанный абзац.
    const section = page.locator('article').filter({ hasText: 'Правка раздела' }).first();
    await expect(section).toContainText('Строка 8 прежней цели');
    await expect(section).toContainText('И ещё абзац, дописанный правкой');

    // Ничего не спрятано переполнением: обрезанный текст пропал бы навсегда.
    const clipped = await page.evaluate(() =>
      Array.from(document.querySelectorAll('article'))
        .filter((node) => node.scrollHeight > node.clientHeight + 1)
        .map((node) => node.getAttribute('aria-label') ?? 'без имени'),
    );
    expect(clipped).toEqual([]);
  });

  test('служебная запись без свободного текста занимает место одной строки', async ({
    page,
    request,
  }) => {
    const key = await seed(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}/case`);
    await expect(page.locator('article').first()).toBeVisible();

    const total = await serviceHeight(page);
    const count = await page.evaluate(
      () =>
        Array.from(document.querySelectorAll('article[data-type]')).filter((node) =>
          ['created', 'section_changed', 'assignee_changed', 'link_added'].includes(
            node.getAttribute('data-type') ?? '',
          ),
        ).length,
    );
    expect(count).toBeGreaterThan(0);

    // Прежде служебная запись занимала столько же, сколько сводка из четырёх частей, —
    // около 120 px на запись. Теперь у записи без свободного текста это строка.
    const withoutText = await page.evaluate(() =>
      Array.from(document.querySelectorAll('article[data-type]'))
        .filter((node) =>
          ['created', 'assignee_changed', 'link_added', 'link_removed'].includes(
            node.getAttribute('data-type') ?? '',
          ),
        )
        .map((node) => node.getBoundingClientRect().height),
    );
    expect(withoutText.length).toBeGreaterThan(0);
    for (const height of withoutText) {
      expect(height).toBeLessThan(60);
    }
    expect(total).toBeGreaterThan(0);
  });

  test('у сводки заголовок не повторяет «следующий шаг» из её же тела', async ({
    page,
    request,
  }) => {
    const key = await seed(request);
    await silenceJournal(page);

    await api(
      request,
      'post',
      `/api/v1/tasks/${key}/entries`,
      {
        type: 'summary',
        payload: {
          done: 'Разобрал, как читается дело',
          remaining: 'Показать служебные записи строкой',
          blockers: 'Ничего',
          next_step: 'Собрать заголовок служебной записи по фактам описи',
        },
      },
      201,
    );

    await page.goto(`/tasks/${key}/case`);
    const summary = page.locator('article').filter({ hasText: 'Следующий шаг' }).first();
    await expect(summary).toBeVisible();

    // Заголовок сводки трекер выводит из первой строки «следующего шага»: показать его
    // вторым разом жирным над тем же текстом значит занять две строки ничем.
    await expect(summary.locator('h3')).toHaveCount(0);
    const step = 'Собрать заголовок служебной записи по фактам описи';
    expect(
      (await summary.innerText()).split(step).length - 1,
      'строка «следующего шага» встречается в записи дважды',
    ).toBe(1);
  });

  test('отбор «Служебные» показывает все служебные записи', async ({ page, request }) => {
    const key = await seed(request);
    // Своя запись агента, чтобы отбору было что отсеивать независимо от соседей.
    await api(
      request,
      'post',
      `/api/v1/tasks/${key}/entries`,
      { type: 'note', title: 'Заметка ради отбора' },
      201,
    );

    await silenceJournal(page);
    await page.goto(`/tasks/${key}/case`);
    await expect(page.locator('article').first()).toBeVisible();

    const before = await page
      .locator('article[data-type]')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-type') ?? ''));
    await page.getByRole('button', { name: 'Служебные' }).click();
    await expect(page.locator('article[data-type="note"]')).toHaveCount(0);

    const after = await page
      .locator('article[data-type]')
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-type') ?? ''));

    // Ни одна служебная запись не потеряна: до отбора и после — тот же набор типов.
    const service = [
      'created',
      'status_changed',
      'section_changed',
      'assignee_changed',
      'link_added',
    ];
    for (const type of service) {
      expect(before, `до отбора в деле нет записи ${type}`).toContain(type);
      expect(after, `отбор потерял записи ${type}`).toContain(type);
    }
    expect(after.length).toBeLessThan(before.length);
  });

  test('доступность ленты дела', async ({ page, request }) => {
    const key = await seed(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}/case`);
    await expect(page.locator('article').first()).toBeVisible();

    const found = await new AxeBuilder({ page }).analyze();
    const serious = found.violations
      .filter((violation) => violation.impact === 'serious' || violation.impact === 'critical')
      .map((violation) => violation.id);

    expect(serious).toEqual([]);
  });
});
