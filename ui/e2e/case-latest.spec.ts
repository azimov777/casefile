import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/** Столько записей помещается на страницу ленты (`entities/entry`, `ENTRY_PAGE_SIZE`). */
const PAGE_SIZE = 25;

/**
 * Столько записей в подопытном деле: больше ста и заведомо больше четырёх страниц.
 * Ровно то, ради чего задача заведена, — дело, которое не листают руками.
 */
const ENTRIES = 104;

async function api(
  request: APIRequestContext,
  path: string,
  data: Record<string, unknown>,
  expected = 201,
): Promise<Record<string, unknown>> {
  const response = await request.post(path, {
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect(response.status(), await response.text()).toBe(expected);
  return ((await response.json()) as { data: Record<string, unknown> }).data;
}

/**
 * Задача с делом длиннее ста записей. Заводится один раз на файл и только если её
 * ещё нет: упавший сценарий выбрасывает воркер вместе с памятью модуля
 * (`docs/notes/testing.md`), а сто записей стоят времени прогона.
 */
let ready: Promise<string> | null = null;

/**
 * Чем сценарий узнаёт свою же задачу между прогонами. Раньше это была машинная метка
 * `tags`, но поле снято вместе со всей механикой (UI-41): опознавателем стала фраза из
 * описания, а находит её отбор `text` — он ищет в названии и в описании сразу.
 *
 * Опознаватель живёт в описании, а не в названии, намеренно: описание в списке не
 * показано, поэтому он не участвует ни в одном замере ширин и переносов.
 *
 * Фраза, а не вставленное в скобках слово: односложную метку тут держало то, что
 * структурный отбор `text` отвергал значение из двух слов (`422 invalid_search_query`),
 * и это ограничение снято (TRK-21). Фраза обязана оставаться уникальной в очереди DEMO:
 * совпав с чужой задачей, сценарий нашёл бы её и своей не завёл.
 */
const MARKER = 'ради перехода к свежей записи';

function seed(request: APIRequestContext): Promise<string> {
  ready ??= (async () => {
    const existing = await request.get(
      `/api/v1/tasks?queue=DEMO&text=${encodeURIComponent(MARKER)}&fields=title`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const found = ((await existing.json()) as { data: { key: string }[] }).data;
    if (found.length > 0) return (found[0] as { key: string }).key;

    const task = await api(request, '/api/v1/tasks', {
      queue: 'DEMO',
      title: 'Дело длиннее четырёх страниц',
      description: `Заведена сквозным тестом ${MARKER}.`,
      goal: 'цель',
      context: 'контекст',
      constraints: 'ограничения',
      output: 'выход',
      checks: ['единственная проверка'],
    });
    const key = task.key as string;

    // Записи подшиваются по очереди: номера выдаются подряд, и последний номер дела
    // обязан совпасть с числом записей — на это опирается проверка.
    for (let no = 2; no <= ENTRIES; no += 1) {
      await api(request, `/api/v1/tasks/${key}/entries`, {
        type: 'note',
        title: `Заметка номер ${no}`,
        body: `Тело заметки номер ${no}.`,
      });
    }

    return key;
  })();

  return ready;
}

/** Сколько раз страница ходила за телами записей — и с какими параметрами. */
function watchFeed(page: Page): URL[] {
  const seen: URL[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (url.pathname.endsWith('/entries')) seen.push(url);
  });
  return seen;
}

test.describe('дело длиннее страницы', () => {
  test('панель «Фильтр» ставит типы подряд, перезагрузка их не теряет', async ({
    page,
    request,
  }) => {
    const key = await seed(request);
    await silenceJournal(page);
    await page.goto(`/tasks/${key}/case`);

    // Панели до нажатия нет вовсе — она вне потока, как и у отбора задач (UI-130).
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
    const menu = page.getByRole('dialog', { name: 'Типы записей' });
    await menu.getByRole('button', { name: 'note', exact: true }).click();
    await expect(page).toHaveURL(/type=note/);
    const chosen = page.getByRole('list', { name: 'Отобранные типы записей' });
    await expect(chosen.getByRole('listitem')).toHaveCount(1);
    await expect(chosen).toContainText('note');

    // Панель не закрывается от нажатия: второй тип ставится следом.
    await menu.getByRole('button', { name: 'summary', exact: true }).click();
    await expect(page).toHaveURL(/type=summary/);
    await expect(chosen.getByRole('listitem')).toHaveCount(2);

    // `Esc` закрывает панель и возвращает фокус на кнопку — это приходит с Radix.
    await page.keyboard.press('Escape');
    await expect(menu).toBeHidden();
    await expect(page.getByRole('button', { name: 'Фильтр', exact: true })).toBeFocused();

    await page.reload();

    // Выбор пережил перезагрузку, и чипы видны без открытия панели.
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(chosen).toContainText('note');
    await expect(chosen).toContainText('summary');
    await expect(page).toHaveURL(/type=note/);
    await expect(page).toHaveURL(/type=summary/);

    // Панель по-прежнему показывает то же самое нажатым.
    await page.getByRole('button', { name: 'Фильтр', exact: true }).click();
    await expect(menu.getByRole('button', { name: 'note', exact: true })).toHaveAttribute(
      'aria-pressed',
      'true',
    );
  });

  test('к свежей записи ведёт одно действие, а не листание всего дела', async ({
    page,
    request,
  }) => {
    const key = await seed(request);
    await silenceJournal(page);
    const feed = watchFeed(page);
    await page.goto(`/tasks/${key}/case`);

    // Первая запись дела на месте: без действия человека лента начинается с начала.
    await expect(page.getByLabel(`${key}#1`, { exact: true })).toBeVisible();
    const before = feed.length;

    await page.getByRole('button', { name: 'К свежей записи' }).click();

    // Показана именно последняя запись всего дела, с телом, и она помечена.
    const last = page.getByLabel(`${key}#${ENTRIES}`, { exact: true });
    await expect(last).toBeVisible();
    await expect(last).toContainText(`Тело заметки номер ${ENTRIES}.`);
    await expect(page).toHaveURL(new RegExp(`entry=${ENTRIES}`));

    // Одним запросом-окном, а не четырьмя страницами подряд: тела первой сотни
    // записей ради этого перехода никто не читал.
    expect(feed.length - before).toBe(1);
    expect(feed.at(-1)?.searchParams.get('after_no')).toBe(String(ENTRIES - PAGE_SIZE));

    // Из окна есть путь обратно к началу дела, и он тоже одно действие.
    await page.getByRole('button', { name: 'Читать дело сначала' }).first().click();
    await expect(page.getByLabel(`${key}#1`, { exact: true })).toBeVisible();
    await expect(page).not.toHaveURL(/from=/);
  });

  test('ссылка на далёкую запись открывает её вместе с соседями', async ({ page, request }) => {
    const key = await seed(request);
    await silenceJournal(page);
    const feed = watchFeed(page);
    await page.goto(`/tasks/${key}/case?entry=77`);

    const target = page.getByLabel(`${key}#77`, { exact: true });
    await expect(target).toBeVisible();
    await expect(target).toContainText('Тело заметки номер 77.');
    // Соседи сверху пришли вместе с ней: решение читают рядом с тем, что к нему привело.
    await expect(page.getByLabel(`${key}#73`, { exact: true })).toBeVisible();

    // Два запроса: страница с начала дела и окно под названную запись.
    expect(feed.length).toBeLessThanOrEqual(2);
    expect(feed.at(-1)?.searchParams.get('after_no')).toBe('72');
  });

  test('в описи карточки свежая запись открывается одним действием', async ({ page, request }) => {
    const key = await seed(request);
    await silenceJournal(page);
    const feed = watchFeed(page);
    await page.goto(`/tasks/${key}`);

    await expect(page.getByRole('table', { name: /^В деле \d+ запис/ })).toBeVisible();
    await page.getByRole('button', { name: 'К свежей записи' }).click();

    const row = page.getByRole('button', { name: `Заметка номер ${ENTRIES}` });
    await expect(row).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByText(`Тело заметки номер ${ENTRIES}.`)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`entry=${ENTRIES}`));

    // Прочитана ровно одна запись — последняя.
    expect(feed).toHaveLength(1);
    expect(feed[0]?.searchParams.getAll('nos')).toEqual([String(ENTRIES)]);
  });

  test('доступность дела с окном и свёрнутым отбором', async ({ page, request }) => {
    const key = await seed(request);
    await silenceJournal(page);

    for (const address of [`/tasks/${key}/case`, `/tasks/${key}/case?entry=${ENTRIES}`]) {
      await page.goto(address);
      await expect(page.getByRole('main')).toBeVisible();
      const found = await new AxeBuilder({ page }).analyze();
      expect(found.violations, address).toEqual([]);
    }
  });
});
