import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

/**
 * Родитель и дети читаются с точки зрения открытой задачи (UI-166): программа с двумя
 * детьми, заведённая тем же путём, что `create_task(parent=…)` агента, — связью `parent`
 * со стороны программы.
 *
 * Вид связи называет роль задачи из карточки: у программы `parent DEMO-9` значит «она
 * родитель DEMO-9». До UI-166 блок «Связи» ставил подпись вида над списком других задач
 * и показывал у ребёнка родителя под «Дети», а детей программы — под «Родитель».
 *
 * Ожидаемые подписи вписаны руками на обоих языках: взятые из словаря, они проверяли бы
 * связь ключа с элементом, а не то, что человек читает (`docs/CONVENTIONS.md`, «Тесты»).
 * Сценарий пишущий — заводит свои задачи — и потому идёт в проекте «запись».
 */

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

async function create(request: APIRequestContext, title: string): Promise<string> {
  const response = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: {
      queue: 'DEMO',
      title,
      description: 'Заведена сквозным тестом UI-166: родитель и дети.',
    },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

async function adopt(request: APIRequestContext, parent: string, child: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${parent}/links`, {
    headers: auth(),
    data: { kind: 'parent', other: child },
  });
  expect(response.status(), `${parent} parent ${child}`).toBe(201);
}

/** Уборка — лучшее усилие: дети раньше программы, иначе она не закроется. */
async function cancel(request: APIRequestContext, key: string): Promise<void> {
  await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: auth(),
    data: { to: 'cancelled', reason: 'Уборка сквозного теста UI-166' },
  });
}

const WORDS = {
  ru: {
    locale: 'ru-RU',
    links: 'Связи',
    parentGroup: 'Родитель',
    childrenGroup: 'Дочерние задачи',
    parentLabel: 'родитель',
    linkAdded: 'Связь',
    asChild: '— дочерняя задача',
    asParent: '— родитель',
  },
  en: {
    locale: 'en-US',
    links: 'Links',
    parentGroup: 'Parent',
    childrenGroup: 'Child tasks',
    parentLabel: 'parent',
    linkAdded: 'Link',
    asChild: '— child task',
    asParent: '— parent',
  },
} as const;

/**
 * Заголовок записи о связи. Части стоят во флекс-строке с зазором, а не через пробел,
 * поэтому в тексте между ними пробела может не быть — его и допускает выражение.
 */
function line(...parts: string[]): RegExp {
  return new RegExp(parts.map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s*'));
}

/**
 * Группа блока «Связи» по виду связи. Идентификатора вида в заголовке группы нет
 * (UI-168): он стоит в разметке знака, `data-kind`, а видна подпись.
 */
function group(page: Page, links: string, kind: string) {
  return page
    .getByRole('region', { name: links })
    .locator('section')
    .filter({
      has: page.getByRole('heading', { level: 3 }).locator(`[data-kind="${kind}"]`),
    });
}

for (const [lang, say] of Object.entries(WORDS)) {
  test.describe(`родитель и дети, ${lang}`, () => {
    test.use({ locale: say.locale });

    test('программа видит детей дочерними, ребёнок программу — родителем, дело обеих — со своей стороны', async ({
      page,
      request,
    }) => {
      test.setTimeout(90_000);
      const program = await create(request, 'Программа сквозного теста UI-166');
      const first = await create(request, 'Первый ребёнок программы UI-166');
      const second = await create(request, 'Второй ребёнок программы UI-166');

      try {
        await adopt(request, program, first);
        await adopt(request, program, second);
        await silenceJournal(page);

        // Карточка программы: дети под «Дочерние задачи», группы «Родитель» нет.
        await page.goto(`/tasks/${program}`);
        await expect(page.getByRole('heading', { level: 1 })).toContainText(program);
        const children = group(page, say.links, 'parent');
        await expect(children.getByRole('heading', { level: 3 })).toContainText(say.childrenGroup);
        await expect(children.getByRole('link', { name: first })).toBeVisible();
        await expect(children.getByRole('link', { name: second })).toBeVisible();
        await expect(group(page, say.links, 'child')).toHaveCount(0);
        // В шапке программы родителя нет: путь — только очередь.
        await expect(
          page.locator('header').getByRole('link', { name: new RegExp(first) }),
        ).toHaveCount(0);

        // Карточка ребёнка: программа — родитель и в шапке, и в блоке «Связи».
        await page.goto(`/tasks/${first}`);
        await expect(page.getByRole('heading', { level: 1 })).toContainText(first);
        await expect(
          page
            .locator('header')
            .getByRole('link', { name: `${say.parentLabel} ${program}`, exact: false }),
        ).toBeVisible();
        const parent = group(page, say.links, 'child');
        await expect(parent.getByRole('heading', { level: 3 })).toContainText(say.parentGroup);
        await expect(parent.getByRole('link', { name: program })).toBeVisible();
        await expect(group(page, say.links, 'parent')).toHaveCount(0);

        // Дело программы: вторая сторона названа дочерней задачей.
        await page.goto(`/tasks/${program}/case`);
        await expect(page.locator('body')).toContainText(
          line(say.linkAdded, 'parent', say.asChild, first),
        );
        // Дело ребёнка: вторая сторона названа родителем.
        await page.goto(`/tasks/${first}/case`);
        await expect(page.locator('body')).toContainText(
          line(say.linkAdded, 'child', say.asParent, program),
        );
      } finally {
        await cancel(request, first);
        await cancel(request, second);
        await cancel(request, program);
      }
    });
  });
}
