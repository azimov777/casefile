import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

const token = readE2eToken();

/**
 * Фраза, по которой сценарий узнаёт свою задачу между прогонами (`e2e/AGENTS.md`):
 * отбор `text` ищет её в описании. Уникальна в очереди DEMO.
 */
const MARKER = 'ради группы правок разделов';

/** Все разделы разом — так их правит агент одним `update_task` (UI-133). */
function sections(round: number) {
  return {
    title: `Правки разделов одним действием, заход ${round}`,
    description: `Заведена сквозным тестом ${MARKER}. Заход ${round}.`,
    goal: `Цель после захода ${round}`,
    context: `Контекст после захода ${round}`,
    constraints: `Ограничения после захода ${round}`,
    output: `Выход после захода ${round}`,
    checks: [`Первая проверка захода ${round}`, `Вторая проверка захода ${round}`],
  };
}

async function api(
  request: APIRequestContext,
  method: 'get' | 'post' | 'patch',
  path: string,
  data?: Record<string, unknown>,
  expected = 200,
): Promise<Record<string, unknown>> {
  const response = await request[method](path, {
    headers: { Authorization: `Bearer ${token}` },
    ...(data === undefined ? {} : { data }),
  });
  expect(response.status(), await response.text()).toBe(expected);
  return ((await response.json()) as { data: Record<string, unknown> }).data;
}

interface Seeded {
  key: string;
  /** Номера правок разделов по действиям: две пачки по семь записей. */
  packs: number[][];
  decision: number;
}

let ready: Promise<Seeded> | null = null;

/**
 * Задача, как TRK-106: пачка из семи правок, решение, ещё одна пачка из семи.
 * Заводится один раз на файл и узнаётся по фразе (`e2e/AGENTS.md`).
 */
function seed(request: APIRequestContext): Promise<Seeded> {
  ready ??= (async () => {
    const existing = await request.get(
      `/api/v1/tasks?queue=DEMO&text=${encodeURIComponent(MARKER)}&fields=title`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    const found = ((await existing.json()) as { data: { key: string }[] }).data;
    let key = found[0]?.key;

    if (key === undefined) {
      const task = await api(
        request,
        'post',
        '/api/v1/tasks',
        { queue: 'DEMO', ...sections(0) },
        201,
      );
      key = task.key as string;
      await api(request, 'patch', `/api/v1/tasks/${key}`, sections(1));
      await api(
        request,
        'post',
        `/api/v1/tasks/${key}/entries`,
        {
          type: 'decision',
          title: 'Решение между двумя пачками правок',
          body: 'Содержательная запись не должна тонуть в служебных.',
        },
        201,
      );
      await api(request, 'patch', `/api/v1/tasks/${key}`, sections(2));
    }

    const detail = await api(request, 'get', `/api/v1/tasks/${key}`);
    const index = detail.index as { no: number; type: string; action_id?: string | null }[];
    const byAction = new Map<string, number[]>();
    for (const heading of index) {
      if (heading.type !== 'section_changed' || heading.action_id == null) continue;
      byAction.set(heading.action_id, [...(byAction.get(heading.action_id) ?? []), heading.no]);
    }
    const decision = index.find((heading) => heading.type === 'decision')?.no ?? -1;
    return { key, packs: [...byAction.values()], decision };
  })();
  return ready;
}

/** Документ не шире окна: группа не должна раздвигать страницу на телефоне. */
async function overflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
}

/** Строка в поле зрения окна, а не где-то ниже сгиба. */
async function inView(page: Page, selector: string): Promise<boolean> {
  return page.evaluate((css) => {
    const node = document.querySelector(css);
    if (node === null) return false;
    const box = node.getBoundingClientRect();
    return box.top >= 0 && box.bottom <= window.innerHeight;
  }, selector);
}

/*
 * Задача отменяется после файла, как у соседей по проекту «запись»: незакрытая, она
 * стояла бы в списке и на доске DEMO под замерами других сценариев. Отменённая
 * читается так же, и следующий прогон узнаёт её по фразе.
 */
test.afterAll(async ({ playwright }) => {
  if (ready === null) return;
  const { key } = await ready;
  const request = await playwright.request.newContext({
    baseURL: test.info().project.use.baseURL,
  });
  await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { to: 'cancelled', reason: 'Сквозной тест UI-133 отработал.' },
  });
  await request.dispose();
});

for (const width of [1440, 390]) {
  test.describe(`правки разделов одним действием на ${width} px (UI-133)`, () => {
    test.beforeEach(async ({ page }) => {
      await silenceJournal(page);
      await page.setViewportSize({ width, height: width > 500 ? 900 : 844 });
    });

    test('в описи семь правок — одна строка, раскрытие показывает все семь', async ({
      page,
      request,
    }) => {
      const { key, packs } = await seed(request);
      expect(packs.map((pack) => pack.length)).toEqual([7, 7]);
      const [first] = packs;
      if (first === undefined) throw new Error('нет первой пачки');

      await page.goto(`/tasks/${key}`);
      const group = page.getByRole('button', {
        name: `Записи ${first[0]}–${first.at(-1)}: правка разделов одним действием`,
      });
      await expect(group).toHaveAttribute('aria-expanded', 'false');
      // Ни одной строки отдельной правки, пока группы свёрнуты.
      await expect(page.locator('tr[data-nested]')).toHaveCount(0);
      await expect(page.locator('tr[data-group]')).toHaveCount(2);
      // Решение между пачками видно без раскрытия.
      await expect(
        page.getByRole('button', { name: /Решение между двумя пачками правок/ }),
      ).toBeVisible();

      await group.click();
      await expect(page.locator('tr[data-nested]')).toHaveCount(7);
      expect(page.url()).not.toContain('entry=');
      await fontsReady(page);
      expect(await overflow(page)).toBeLessThanOrEqual(0);
    });

    test('?entry=N раскрывает группу описи и показывает именно запись N', async ({
      page,
      request,
    }) => {
      const { key, packs } = await seed(request);
      const target = packs[1]?.[2];
      if (target === undefined) throw new Error('нет второй пачки');

      await page.goto(`/tasks/${key}?entry=${target}`);
      const row = page.locator('tr[data-nested]').filter({
        has: page.locator('th', { hasText: new RegExp(`^${target}$`) }),
      });
      // Кнопка раскрытия, а не первая попавшаяся: в строке есть и знак ссылки (UI-155).
      await expect(row.locator('button[aria-expanded]')).toHaveAttribute('aria-expanded', 'true');
      // Раскрыта одна запись — названная, её соседи по группе свёрнуты.
      await expect(page.locator('tr[data-nested] button[aria-expanded="true"]')).toHaveCount(1);
      // Тело записи пришло: пара «было / стало» этой правки.
      await expect(page.locator('[data-side="now"]').first()).toBeVisible();
      await expect
        .poll(() =>
          row.evaluate((node) => {
            const box = node.getBoundingClientRect();
            return box.top >= 0 && box.bottom <= window.innerHeight;
          }),
        )
        .toBe(true);
    });

    test('в ленте пачка — одна строка, ?entry=N раскрывает её и ведёт к записи N', async ({
      page,
      request,
    }) => {
      const { key, packs, decision } = await seed(request);
      const target = packs[0]?.[3];
      if (target === undefined) throw new Error('нет первой пачки');

      await page.goto(`/tasks/${key}/case`);
      await expect(page.getByLabel(`${key}#${decision}`)).toBeVisible();
      await expect(page.locator('section[data-group]')).toHaveCount(2);
      await expect(page.locator('article[data-type="section_changed"]')).toHaveCount(0);
      await fontsReady(page);
      expect(await overflow(page)).toBeLessThanOrEqual(0);

      await page.goto(`/tasks/${key}/case?entry=${target}`);
      const card = page.locator(`#entry-${target}`);
      await expect(card).toHaveAttribute('data-highlighted', '');
      // Раскрыта только группа названной записи: вторая пачка свёрнута.
      await expect(page.locator('article[data-type="section_changed"]')).toHaveCount(7);
      await expect.poll(() => inView(page, `#entry-${target}`)).toBe(true);
      expect(await overflow(page)).toBeLessThanOrEqual(0);

      const found = await new AxeBuilder({ page }).analyze();
      expect(found.violations).toEqual([]);
    });
  });
}
