import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { fontsReady, motionSettled, readE2eToken, silenceJournal } from './contour';

/**
 * Блок «Связи» насыщенной задачей (UI-125): несколько видов, по нескольку задач
 * в одной группе, длинное название среди них. Таких связей в демо нет — оно держит
 * по одной связи на вид (`app/services/demo.py`), — поэтому сценарий заводит их сам
 * и потому идёт в проекте «запись», как `parents-long.spec.ts`.
 *
 * Пример, который был поводом задачи, — настоящая TRK-106 (`relates` и пять детей) —
 * снять здесь нельзя: контур сценария — своя пустая установка, а не установка
 * владельца или общий дев-контур (`docs/CONVENTIONS.md`, «Слияние ветки задачи в
 * main» и правила рабочего дерева). Сценарий строит равносильный пример сам.
 */

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

async function create(request: APIRequestContext, title: string): Promise<string> {
  const response = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: {
      project: 'DEMO',
      title,
      description: 'Заведена сквозным тестом UI-125: насыщенный блок «Связи».',
    },
  });
  expect(response.status()).toBe(201);
  return ((await response.json()) as { data: { key: string } }).data.key;
}

/** Ставит связь `subject <kind> other` со стороны `subject` — тем же путём, что агент. */
async function link(
  request: APIRequestContext,
  subject: string,
  kind: string,
  other: string,
): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${subject}/links`, {
    headers: auth(),
    data: { kind, other },
  });
  expect(response.status(), `${subject} ${kind} ${other}`).toBe(201);
}

/**
 * Уборка — лучшее усилие: контур этого сценария одноразовый и в конце гасится целиком
 * (`docker compose down -v`), а отказ уборки не должен топить проверку рисунка блока.
 * Дети — раньше `subject`: он для них родитель, и родитель с незакрытыми детьми не
 * закрывается (`parents-long.spec.ts`).
 */
async function cancel(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: auth(),
    data: { to: 'cancelled', reason: 'Уборка сквозного теста UI-125' },
  });
  if (!response.ok()) {
    await test.info().attach(`уборка ${key} не удалась`, {
      body: await response.text(),
      contentType: 'text/plain',
    });
  }
}

function linksSection(page: Page): Locator {
  return page.getByRole('region', { name: 'Связи' });
}

function groupHeadings(page: Page): Locator {
  return linksSection(page).getByRole('heading', { level: 3 });
}

/**
 * Вертикальные зазоры блока «Связи» по содержимому строк: `inside` — между частями одной
 * связи, стоящими друг под другом (ключ, название, статус), `between` — от низа
 * содержимого связи до верха содержимого следующей в той же группе. Меряются части,
 * а не `li`: поля и линия строки — это и есть граница, её и сравнивают.
 */
async function rowGaps(page: Page): Promise<{ inside: number[]; between: number[] }> {
  return linksSection(page).evaluate((region) => {
    const inside: number[] = [];
    const between: number[] = [];
    for (const list of Array.from(region.querySelectorAll('ul'))) {
      const rows = Array.from(list.children).map((row) =>
        Array.from(row.children)
          .map((part) => part.getBoundingClientRect())
          .sort((a, b) => a.top - b.top),
      );
      rows.forEach((parts, at) => {
        for (let i = 1; i < parts.length; i += 1) {
          const above = Math.max(...parts.slice(0, i).map((part) => part.bottom));
          // Часть на той же линии, что предыдущая, — не «под ней»: зазора нет.
          if (parts[i].top >= above) inside.push(parts[i].top - above);
        }
        const next = rows[at + 1];
        if (next !== undefined) {
          between.push(
            Math.min(...next.map((part) => part.top)) -
              Math.max(...parts.map((part) => part.bottom)),
          );
        }
      });
    }
    return { inside, between };
  });
}

/**
 * Заголовки групп блока «Связи» по линиям (UI-168): базовая линия каждой текстовой части
 * заголовка — подписи и счётчика — и сколько строк он занял. Базовую
 * линию даёт нулевой `inline-block` в конце текста части: его верх стоит ровно на ней.
 * Высота строки берётся у самого заголовка: одна строка — высота не больше полутора.
 */
async function headingLines(
  page: Page,
): Promise<{ text: string; baselines: number[]; height: number; lineHeight: number }[]> {
  return linksSection(page).evaluate((region) =>
    Array.from(region.querySelectorAll('h3')).map((heading) => {
      const parts = Array.from(heading.querySelectorAll('span')).filter(
        (part) => part.children.length === 0 && (part.textContent ?? '').trim() !== '',
      );
      const baselines = parts.map((part) => {
        const probe = document.createElement('span');
        probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
        part.appendChild(probe);
        const y = probe.getBoundingClientRect().top;
        probe.remove();
        return y;
      });
      const style = getComputedStyle(heading);
      const lineHeight =
        style.lineHeight === 'normal'
          ? parseFloat(style.fontSize) * 1.2
          : parseFloat(style.lineHeight);
      return {
        text: heading.textContent ?? '',
        baselines,
        height: heading.getBoundingClientRect().height,
        lineHeight,
      };
    }),
  );
}

const LONG_CHILD_TITLE =
  'Задача этого вида связи с названием такой длины, что на узком экране ей есть, где перенестись: src/pages/task/ui/task-links.tsx';

test('насыщенный блок «Связи»: заголовок группы со счётчиком, ничего не обрезано, строки одной формы', async ({
  page,
  request,
}) => {
  test.setTimeout(120_000);

  const subject = await create(request, 'Подопытная задача блока «Связи» (UI-125)');
  const blockerA = await create(request, 'Первый блокер подопытной задачи');
  const blockerB = await create(request, 'Второй блокер подопытной задачи');
  const blocked = await create(request, 'Задача, которую держит подопытная');
  const parent = await create(request, 'Родитель подопытной задачи');
  const childA = await create(request, 'Первый ребёнок подопытной задачи');
  const childB = await create(request, 'Второй ребёнок подопытной задачи');
  const childC = await create(request, LONG_CHILD_TITLE);
  const related = await create(request, 'Просто связанная задача');

  try {
    await link(request, subject, 'blocked_by', blockerA);
    await link(request, subject, 'blocked_by', blockerB);
    await link(request, subject, 'blocks', blocked);
    /*
     * Вид называет роль `subject`: «subject child parent» — подопытная ребёнок своего
     * родителя, «subject parent childA» — она родитель ребёнка. До UI-166 здесь стояло
     * наоборот, и сценарий заводил подопытной трёх родителей и одного ребёнка,
     * называя их обратными именами, — ровно та путаница, которую блок показывал.
     */
    await link(request, subject, 'child', parent);
    await link(request, subject, 'parent', childA);
    await link(request, subject, 'parent', childB);
    await link(request, subject, 'parent', childC);
    await link(request, subject, 'relates', related);

    await silenceJournal(page);

    for (const width of [1440, 390] as const) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`/tasks/${subject}`);
      await expect(page.getByRole('heading', { level: 1 })).toContainText(subject);
      await fontsReady(page);

      const headings = groupHeadings(page);
      await expect(headings).toHaveCount(5);

      // Порядок групп по значимости: то, что держит задачу, стоит первым, необязывающая
      // связь `relates` — последней (владелец, UI-125); родитель (`child`) — выше
      // дочерних (`parent`, UI-166).
      const order = await headings.evaluateAll((nodes) =>
        nodes.map(
          (node) => node.querySelector('[data-mark="link-kind"]')?.getAttribute('data-kind') ?? '',
        ),
      );
      expect(order, `порядок групп на ${width}px`).toEqual([
        'blocked_by',
        'blocks',
        'child',
        'parent',
        'relates',
      ]);

      // Заголовок называет, кем задачи группы приходятся подопытной, её глазами
      // (UI-166, UI-168), а счётчик — собственные задачи группы, не связи целиком.
      const expected = [
        ['Блокирует эту задачу', '2 задачи'],
        ['Эта задача блокирует', '1 задача'],
        ['Родитель', '1 задача'],
        ['Дочерние задачи', '3 задачи'],
        ['Связанные', '1 задача'],
      ] as const;
      for (const [at, [caption, count]] of expected.entries()) {
        await expect(headings.nth(at)).toHaveText(`${caption}${count}`);
      }
      // Идентификатора вида рядом с подписью нет (владелец, UI-168#10): `parent` над
      // «Дочерние задачи» читался противоречием — вид называет роль подопытной.
      for (const kind of order) {
        await expect(groupHeadings(page).filter({ hasText: kind })).toHaveCount(0);
      }

      // Ни одна подпись вида связи не обрезана — ни на широком экране, ни на узком.
      const marks = linksSection(page).locator('[data-mark="link-kind"]');
      const clipped = await marks.evaluateAll((nodes) =>
        nodes.map((node) => {
          const caption = node.querySelector('span') as HTMLElement;
          return {
            text: caption.textContent,
            clipped: caption.scrollWidth > caption.clientWidth,
          };
        }),
      );
      for (const item of clipped) {
        expect(item.clipped, `${width}px, ${JSON.stringify(item)}`).toBe(false);
      }

      // Заголовок группы — одна строка на одной оси (UI-168): прежде базовой линией
      // знака вида браузер брал низ его иконки, и счётчик стоял на 3–4 px ниже подписи.
      for (const heading of await headingLines(page)) {
        const label = `${width}px, «${heading.text}»: ${heading.baselines.join(', ')}`;
        // Две части — подпись и счётчик.
        expect(heading.baselines.length, label).toBeGreaterThanOrEqual(2);
        expect(
          Math.max(...heading.baselines) - Math.min(...heading.baselines),
          label,
        ).toBeLessThanOrEqual(0.5);
        expect(heading.height, `${label}; высота ${heading.height}`).toBeLessThanOrEqual(
          heading.lineHeight * 1.5,
        );
      }

      // Все три ребёнка перечислены под общим заголовком — ни один не потерялся
      // за счётчиком, а самый длинный ключ виден целиком, не многоточием.
      for (const key of [childA, childB, childC]) {
        await expect(linksSection(page).getByRole('link', { name: key })).toBeVisible();
      }

      // Статус связанной задачи — тем же знаком, что в таблице задач: форма, а не
      // голая плашка (`StatusMark`, `data-mark="status"`), и у него есть рисунок.
      const statusMark = linksSection(page)
        .locator('li')
        .filter({ hasText: blockerA })
        .locator('[data-mark="status"]');
      await expect(statusMark).toBeVisible();
      await expect(statusMark.locator('svg')).toHaveCount(1);

      // Одна форма у каждой строки (UI-148): статус у всех связей блока начинается
      // с одного и того же левого края, как бы ни было длинно название.
      const statusLefts = await linksSection(page)
        .locator('li [data-mark="status"]')
        .evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().left));
      expect(statusLefts.length, `${width}px`).toBe(8);
      expect(
        Math.max(...statusLefts) - Math.min(...statusLefts),
        `${width}px, левые края статусов: ${statusLefts.join(', ')}`,
      ).toBeLessThanOrEqual(0.5);

      // Граница между связями видна сразу: зазор между соседними связями группы больше
      // любого зазора внутри одной связи (закон близости).
      const gaps = await rowGaps(page);
      expect(
        Math.min(...gaps.between),
        `${width}px, между: ${gaps.between.join(', ')}; внутри: ${gaps.inside.join(', ')}`,
      ).toBeGreaterThan(Math.max(...gaps.inside));

      const lightShot = await linksSection(page).screenshot({
        path: test.info().outputPath(`link-groups-${width}-light.png`),
      });
      await test.info().attach(`связи ${width}px светлая`, {
        body: lightShot,
        contentType: 'image/png',
      });

      await page.emulateMedia({ colorScheme: 'dark' });
      await motionSettled(linksSection(page));
      const darkShot = await linksSection(page).screenshot({
        path: test.info().outputPath(`link-groups-${width}-dark.png`),
      });
      await test.info().attach(`связи ${width}px тёмная`, {
        body: darkShot,
        contentType: 'image/png',
      });
      await page.emulateMedia({ colorScheme: 'light' });
    }
  } finally {
    for (const key of [childA, childB, childC]) await cancel(request, key);
    await cancel(request, subject);
    for (const key of [blockerA, blockerB, blocked, parent, related]) await cancel(request, key);
  }
});

/** Поля тела блока «Связи»: от рамки до первой строки слева, от линии заголовка сверху, до рамки снизу. */
async function bodyInsets(page: Page): Promise<{ left: number; top: number; bottom: number }> {
  return linksSection(page).evaluate((region) => {
    const heading = region.querySelector('h2') as HTMLElement;
    // Тело — следующий за заголовком узел; строки — его прямые потомки (группы или «связей нет»).
    const body = heading.nextElementSibling as HTMLElement;
    const first = body.firstElementChild as HTMLElement;
    const last = body.lastElementChild as HTMLElement;
    const frame = region.getBoundingClientRect();
    const style = getComputedStyle(region);
    const inner = {
      left: frame.left + parseFloat(style.borderLeftWidth),
      bottom: frame.bottom - parseFloat(style.borderBottomWidth),
    };
    // Строка списка — `li` (ключ, название, статус), а у пустого блока — сам текст.
    const row = (region.querySelector('li') ?? first).getBoundingClientRect();
    return {
      left: row.left - inner.left,
      top: first.getBoundingClientRect().top - heading.getBoundingClientRect().bottom,
      bottom: inner.bottom - last.getBoundingClientRect().bottom,
    };
  });
}

test('пустой блок «Связи» держит те же поля, что непустой список (UI-141)', async ({
  page,
  request,
}) => {
  test.setTimeout(90_000);

  const lonely = await create(request, 'Задача без связей (UI-141)');
  const linked = await create(request, 'Задача с одной связью (UI-141)');
  const other = await create(request, 'Связанная задача (UI-141)');

  try {
    await link(request, linked, 'relates', other);
    await silenceJournal(page);

    for (const width of [1440, 390] as const) {
      await page.setViewportSize({ width, height: 900 });

      await page.goto(`/tasks/${linked}`);
      await expect(page.getByRole('heading', { level: 1 })).toContainText(linked);
      await fontsReady(page);
      await linksSection(page).scrollIntoViewIfNeeded();
      const list = await bodyInsets(page);

      await page.goto(`/tasks/${lonely}`);
      await expect(page.getByRole('heading', { level: 1 })).toContainText(lonely);
      await expect(linksSection(page).getByText('Связей нет.')).toBeVisible();
      await fontsReady(page);
      await linksSection(page).scrollIntoViewIfNeeded();
      const empty = await bodyInsets(page);

      // Поле непустое: текст не прижат к рамке — и ровно то же, что у строк списка.
      expect(list.left, `${width}px, список`).toBeGreaterThan(4);
      for (const side of ['left', 'top', 'bottom'] as const) {
        expect(
          Math.abs(empty[side] - list[side]),
          `${width}px, ${side}: пусто ${empty[side]}, список ${list[side]}`,
        ).toBeLessThanOrEqual(0.5);
      }
    }
  } finally {
    await cancel(request, other);
    await cancel(request, linked);
    await cancel(request, lonely);
  }
});
