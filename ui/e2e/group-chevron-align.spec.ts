import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, silenceJournal } from './contour';

/**
 * UI-162: проверка находки UI-158 («иконки/`::before`-треугольник и текст на
 * `items-baseline` выравниваются не по оптическому центру, а по метрике каждого
 * своей») на втором узле с тем же паттерном — треугольник раскрытия группы правок
 * в описи задачи (`entities/entry/ui/entry-index.tsx`, `GroupRows`, `before:content-['▸']`
 * / `before:content-['▾']` внутри `flex items-baseline`).
 *
 * UI-158 не измерял этот узел напрямую: там в строке только текст (`EntryHeadline`),
 * не смесь SVG-иконки с текстом, как у заголовка столбца доски, и находка о разных
 * метриках шрифта не переносится однозначно.
 *
 * Треугольник — `::before`, а не узел: `getBoundingClientRect` на псевдоэлементе
 * недоступен (та же причина, по которой UI-158 заменил его на `ChevronRight`).
 * Не трогая разметку, замер строит «зонд» — временный `<span>` с тем же символом
 * (`getComputedStyle(button, '::before').content`) и теми же шрифтовыми свойствами
 * (`font-*`, `line-height`), вставленный первым ребёнком кнопки — туда же, куда
 * браузер кладёт сгенерированный псевдоэлементом бокс в потоке флекс-контейнера
 * (`::before` — первый флекс-айтем по спецификации). Зонд убирается тем же
 * синхронным вызовом `evaluate`, до первой отрисовки с ним, — снимок делает не
 * прогон, отличный от боевого.
 */
async function chevronOffset(button: Locator): Promise<number> {
  return button.evaluate((node) => {
    const label = node.querySelector('span');
    if (label === null) throw new Error('заголовок группы (span) не найден в кнопке');

    const before = getComputedStyle(node, '::before');
    const raw = before.content;
    if (raw === 'none' || raw === '""' || raw === '') {
      throw new Error(`::before кнопки пуст: content="${raw}"`);
    }
    const char = raw.replace(/^["']|["']$/g, '');

    const probe = document.createElement('span');
    probe.textContent = char;
    probe.style.fontFamily = before.fontFamily;
    probe.style.fontSize = before.fontSize;
    probe.style.fontWeight = before.fontWeight;
    probe.style.fontStyle = before.fontStyle;
    probe.style.lineHeight = before.lineHeight;
    probe.style.letterSpacing = before.letterSpacing;
    node.insertBefore(probe, node.firstChild);

    const iconBox = probe.getBoundingClientRect();
    const labelBox = label.getBoundingClientRect();
    node.removeChild(probe);

    return (iconBox.top + iconBox.bottom) / 2 - (labelBox.top + labelBox.bottom) / 2;
  });
}

const token = readE2eToken();

function auth() {
  return { Authorization: `Bearer ${token}` };
}

/** Все пять разделов разом — так группа из нескольких `section_changed` рождается одним действием (UI-133). */
function sections(round: number) {
  return {
    goal: `Цель UI-162, заход ${round}`,
    context: `Контекст UI-162, заход ${round}`,
    constraints: `Ограничения UI-162, заход ${round}`,
    output: `Выход UI-162, заход ${round}`,
    checks: [`Проверка UI-162, заход ${round}`],
  };
}

async function seed(
  request: APIRequestContext,
): Promise<{ key: string; first: number; last: number }> {
  const created = await request.post('/api/v1/tasks', {
    headers: auth(),
    data: {
      project: 'DEMO',
      title: 'Подопытная задача для замера треугольника группы (UI-162)',
      description: 'Заведена сквозным тестом UI-162.',
      ...sections(0),
    },
  });
  expect(created.status()).toBe(201);
  const key = ((await created.json()) as { data: { key: string } }).data.key;

  // PATCH правит пять разделов разом — трекер подшивает по одной `section_changed`
  // на раздел, все с одним `action_id` (UI-133): так рождается группа в описи. REST
  // `PATCH /tasks/{key}` отдаёт саму задачу (`TaskRead`), не номера подшитых записей —
  // их читаем следующим `GET`, как и `section-edits.spec.ts`.
  const patched = await request.patch(`/api/v1/tasks/${key}`, {
    headers: auth(),
    data: sections(1),
  });
  expect(patched.status()).toBe(200);

  const detail = await request.get(`/api/v1/tasks/${key}`, { headers: auth() });
  expect(detail.status()).toBe(200);
  const index = (
    (await detail.json()) as {
      data: { index: { no: number; type: string; action_id?: string | null }[] };
    }
  ).data.index;

  const byAction = new Map<string, number[]>();
  for (const heading of index) {
    if (heading.type !== 'section_changed' || heading.action_id == null) continue;
    byAction.set(heading.action_id, [...(byAction.get(heading.action_id) ?? []), heading.no]);
  }
  const pack = [...byAction.values()].find((nos) => nos.length > 1);
  if (pack === undefined) throw new Error('группа правок разделов не сложилась');

  return { key, first: Math.min(...pack), last: Math.max(...pack) };
}

async function cancel(request: APIRequestContext, key: string): Promise<void> {
  const response = await request.post(`/api/v1/tasks/${key}/transition`, {
    headers: auth(),
    data: { to: 'cancelled', reason: 'Уборка сквозного теста UI-162' },
  });
  if (!response.ok()) {
    await test.info().attach(`уборка ${key} не удалась`, {
      body: await response.text(),
      contentType: 'text/plain',
    });
  }
}

async function group(page: Page, first: number, last: number): Promise<Locator> {
  return page.getByRole('button', {
    name: `Записи ${first}–${last}: правка разделов одним действием`,
  });
}

/**
 * Задача пишущая (заводит и отменяет свою задачу DEMO) и потому идёт одна в проекте
 * «запись» (`playwright.config.ts`), а не в «светлая»/«тёмная» — у тех своя параллельная
 * демо-установка, и вторая тема живёт не вторым прогоном всего файла, а переключением
 * `page.emulateMedia` внутри одного теста на одной и той же странице: тот же приём, что
 * у других пишущих сценариев с обеими темами (`layout.spec.ts`, `link-groups.spec.ts`).
 */
test('значок раскрытия группы в описи стоит на оси заголовка группы, тем же замером, что у доски (UI-158, UI-162)', async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const { key, first, last } = await seed(request);

  try {
    await silenceJournal(page);
    await page.goto(`/tasks/${key}`);
    const toggle = await group(page, first, last);
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    await fontsReady(page);

    const offsets: Record<string, number> = {};
    offsets['collapsed светлая'] = Math.round((await chevronOffset(toggle)) * 100) / 100;

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    offsets['expanded светлая'] = Math.round((await chevronOffset(toggle)) * 100) / 100;

    await page.emulateMedia({ colorScheme: 'dark' });
    offsets['expanded тёмная'] = Math.round((await chevronOffset(toggle)) * 100) / 100;

    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'false');
    offsets['collapsed тёмная'] = Math.round((await chevronOffset(toggle)) * 100) / 100;

    const report = JSON.stringify(offsets);
    console.log('[UI-162 смещение треугольника группы]', report);
    for (const [label, offset] of Object.entries(offsets)) {
      expect(Math.abs(offset), `${label}: ${report}`).toBeLessThanOrEqual(1);
    }
  } finally {
    await cancel(request, key);
  }
});
