import { expect, test, type Page } from '@playwright/test';
import { fontsReady, silenceJournal, tasksByStatus } from './contour';

/**
 * Раскрытие (`shared/ui/reveal.tsx`) по кадрам: видимая часть содержимого идёт вместе
 * со своим местом, а место в столбце доски со своей прокруткой флекс не сжимает (UI-112).
 *
 * Место едет строками сетки `0fr ↔ 1fr`, и Chrome считает долю `fr` дважды: высоту
 * месту — по содержимому (f·h), строку — ещё раз, от этой высоты (f·f·h). Обрезай
 * содержимое то, что стоит в строке, — видно было бы f²·h, а соседи ниже уже сдвинуты
 * на f·h: под обрезанным краем пустая полоса до четверти высоты на середине хода
 * (замер `UI-110#10`). В покое её нет — на 0fr и 1fr обе оценки совпадают, — поэтому
 * меряются кадры, и снимает их сам браузер: снаружи 120 мс кончаются раньше первого
 * замера (`docs/notes/ui.md`, «Кадр движения не поймать снаружи»).
 */

/** Числа замера — в отчёт прогона: по ним пишется вердикт, а не по зелёной строке. */
function report(type: string, numbers: unknown): void {
  const description = JSON.stringify(numbers);
  test.info().annotations.push({ type, description });
  console.log(`[${type}] ${description}`);
}

/** Кнопка раскрытия и где от неё искать место. */
interface Target {
  /** Селектор кнопки с `aria-expanded`. */
  toggle: string;
  /** Подстрока подписи кнопки, если селектор находит не одну. */
  text?: string;
  /** Место стоит в следующей строке таблицы, а не в том же разделе. */
  row?: boolean;
}

/** Кадр раскрытия. */
interface RevealFrame {
  /** Миллисекунды от начала наблюдения. */
  at: number;
  /** Высота места `data-reveal="place"`. */
  height: number;
  /** Низ места. */
  place: number;
  /**
   * Низ видимой части содержимого: низ самого нижнего узла содержимого, срезанный
   * краем каждого обрезающего узла между содержимым и местом включительно. Считается
   * по вычисленному `overflow`, а не по тому, на каком узле обрезание стоит сегодня:
   * замер обязан падать и там, где обрезание отстаёт от места, и там, где его нет вовсе.
   */
  visible: number;
  /** Высота содержимого: от верха места до низа самого нижнего узла в прослойке. */
  content: number;
  /** Обрезает ли что-нибудь между содержимым и местом. */
  clipped: boolean;
  /** Сколько раздел вокруг места прокручивает: у столбца доски — своя прокрутка. */
  over: number;
}

interface RevealWatch {
  /** Движение места в первом кадре, где оно едет, и чем; `null` — место не ехало ни кадра. */
  motion: { running: boolean; property: string } | null;
  frames: RevealFrame[];
  timedOut: boolean;
}

/**
 * Снимает раскрытие по кадрам. Нажимает сам браузер: наблюдение ставится до нажатия.
 *
 * Раскрытие (`leave: false`) кончается, когда место доехало, обрезание снято и три
 * кадра ничего не двигалось. Свёртывание (`leave: true`) — когда узел снят и три кадра
 * его нет.
 */
async function watchReveal(page: Page, target: Target, leave: boolean): Promise<RevealWatch> {
  return page.evaluate(
    ({ target: aim, leave: leaving }) =>
      new Promise<RevealWatch>((resolve, reject) => {
        const buttons = Array.from(document.querySelectorAll<HTMLElement>(aim.toggle)).filter(
          (node) => aim.text === undefined || node.textContent?.includes(aim.text) === true,
        );
        const button = buttons[0];
        if (buttons.length !== 1 || button === undefined) {
          reject(new Error(`кнопок раскрытия ${aim.toggle} «${aim.text}»: ${buttons.length}`));
          return;
        }
        const find = () =>
          (aim.row === true
            ? button.closest('tr')?.nextElementSibling
            : button.closest('section')
          )?.querySelector<HTMLElement>('[data-reveal="place"]') ?? undefined;

        let place = leaving ? find() : undefined;
        if (leaving !== (place !== undefined)) {
          reject(new Error(leaving ? 'свёртывать нечего' : 'место уже в разметке'));
          return;
        }

        const measure = (node: HTMLElement): RevealFrame | null => {
          const layer = node.firstElementChild;
          if (layer === null || layer.children.length === 0) return null;
          const box = node.getBoundingClientRect();
          const bottom = Math.max(
            ...Array.from(layer.children, (child) => child.getBoundingClientRect().bottom),
          );
          let visible = bottom;
          let clipped = false;
          for (let at: Element | null = layer; at !== null; at = at.parentElement) {
            const style = getComputedStyle(at);
            if (style.overflowY !== 'visible') {
              clipped = true;
              // Край обрезания — внутренний край рамки, а не внешний.
              const edge =
                at.getBoundingClientRect().bottom - Number.parseFloat(style.borderBottomWidth);
              visible = Math.min(visible, edge);
            }
            if (at === node) break;
          }
          const section = node.closest('section');
          return {
            at: 0,
            height: box.height,
            place: box.bottom,
            visible,
            content: bottom - box.top,
            clipped,
            over: section === null ? 0 : section.scrollHeight - section.clientHeight,
          };
        };

        const started = performance.now();
        const record: RevealWatch = { motion: null, frames: [], timedOut: false };
        let calm = 0;

        const tick = () => {
          place ??= find();
          let frame: RevealFrame | null = null;
          if (place?.isConnected === true) {
            // Движение снимается с первого кадра, где место едет, а не где оно есть: доска
            // кладёт свёрнутые столбцы в адрес, и нажатие доходит до разметки кадром позже.
            if (record.motion === null && place.getAnimations().length > 0) {
              record.motion = {
                running: true,
                property: getComputedStyle(place).transitionProperty,
              };
            }
            frame = measure(place);
            if (frame === null) {
              reject(new Error('у места нет прослойки с содержимым'));
              return;
            }
            frame.at = Math.round(performance.now() - started);
            record.frames.push(frame);
          }

          const resting = leaving
            ? place?.isConnected !== true
            : place !== undefined &&
              place.getAnimations({ subtree: true }).length === 0 &&
              frame?.clipped === false;
          calm = resting ? calm + 1 : 0;
          if (calm >= 3 || performance.now() - started > 10_000) {
            record.timedOut = calm < 3;
            resolve(record);
            return;
          }
          requestAnimationFrame(tick);
        };

        button.click();
        requestAnimationFrame(tick);
      }),
    { target, leave },
  );
}

/** Ждёт, пока в документе ничего не едет: следующий замер начинается с покоя. */
async function motionsSettled(page: Page): Promise<void> {
  await page.evaluate(() =>
    Promise.allSettled(document.getAnimations().map((motion) => motion.finished)),
  );
}

/** Кадры коротко — для отчёта: одна десятая пикселя точнее, чем видит глаз. */
function framesReport(watch: RevealWatch) {
  const round = (value: number) => Math.round(value * 10) / 10;
  return {
    frames: watch.frames.length,
    at: watch.frames.map((frame) => frame.at),
    height: watch.frames.map((frame) => round(frame.height)),
    gap: watch.frames.map((frame) => round(frame.place - frame.visible)),
    content: round(watch.frames.at(-1)?.content ?? Number.NaN),
  };
}

/**
 * Проверка кадров одного хода: место ехало прямо сейчас, среди кадров есть середина
 * хода, и на каждом кадре низ видимой части содержимого — это низ места.
 */
function expectVisibleFollowsPlace(name: string, watch: RevealWatch): void {
  expect(watch.timedOut, `${name}: место не доехало или не снялось`).toBe(false);
  expect(watch.motion?.running, `${name}: место не ехало`).toBe(true);
  expect(watch.motion?.property, name).toBe('grid-template-rows');

  const heights = watch.frames.map((frame) => frame.height);
  const low = Math.min(...heights);
  const high = Math.max(...heights);
  expect(
    heights.some((height) => height > low && height < high),
    `${name}: ни одного кадра посреди хода`,
  ).toBe(true);

  // Числа одного источника (`getBoundingClientRect`), поэтому сравниваются точно.
  const gaps = watch.frames.map((frame) => frame.place - frame.visible);
  expect(
    Math.max(...gaps.map((gap) => Math.abs(gap))),
    `${name}: низ видимого содержимого ушёл от низа места, ${JSON.stringify(gaps)}`,
  ).toBe(0);
}

/** Запись в описи карточки: место — в ячейке таблицы. */
const INDEX_ENTRY: Target = {
  toggle: 'table button[aria-expanded]',
  text: 'Обзорная проверка 2',
  row: true,
};

test('запись описи открывается и сворачивается: видимое содержимое идёт вместе с местом', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-6');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('DEMO-6');
  await fontsReady(page);

  // Тело записи читается запросом на первом раскрытии. Меряется второе: тело уже
  // в кэше и стоит в месте с первого кадра, а не приезжает посреди хода.
  const toggle = page.getByRole('button', { name: /Обзорная проверка 2/ });
  await toggle.click();
  await expect(page.getByRole('cell').filter({ hasText: 'Неприменимый оператор' })).toBeVisible();
  await motionsSettled(page);
  await toggle.click();
  await expect(page.locator('table [data-reveal="place"]')).toHaveCount(0);
  await motionsSettled(page);

  const opening = await watchReveal(page, INDEX_ENTRY, false);
  await motionsSettled(page);
  const closing = await watchReveal(page, INDEX_ENTRY, true);

  report('UI-112 опись, раскрытие', framesReport(opening));
  report('UI-112 опись, свёртывание', framesReport(closing));

  expectVisibleFollowsPlace('раскрытие', opening);
  expectVisibleFollowsPlace('свёртывание', closing);
  expect(opening.frames.at(-1)?.clipped, 'раскрытое место осталось обрезанным').toBe(false);
});

/**
 * Столбец доски на широком экране прокручивается сам (`fold:overflow-y-auto`), и
 * раскрытое место в нём — элемент переполненной флекс-колонки. Место, ставшее
 * контейнером прокрутки, теряет автоматический минимальный размер, и флекс сжал бы его
 * до остатка столбца: высота стояла бы на месте посреди хода и добирала бы содержимое
 * скачком в кадр, где снято обрезание. Поэтому меряется высота места по кадрам: она
 * не убывает, не стоит, пока не доехала, и доходит до высоты содержимого.
 *
 * Окно низкое, чтобы самый длинный столбец демо заведомо не поместился: длину столбцов
 * решает бэкенд, и выписанное здесь число карточек устарело бы вместе с ним.
 */
test('раскрытие столбца доски со своей прокруткой: флекс не сжимает место посреди хода', async ({
  page,
  request,
}) => {
  const all = await tasksByStatus(request);
  const longest = [...all.entries()].sort(([, left], [, right]) => right.length - left.length)[0];
  expect(longest, 'в демо нет ни одной задачи').toBeDefined();
  const [status] = longest as [string, string[]];

  await silenceJournal(page);
  await page.setViewportSize({ width: 1024, height: 420 });
  // `collapsed=` — все столбцы раскрыты: первая страница столбца прочитана до замера,
  // и раскрытие берёт её из кэша, а не ждёт посреди хода.
  await page.goto('/tasks?project=DEMO&view=board&collapsed=');
  const column = page.getByRole('region', { name: status });
  await expect(column.getByRole('article').first()).toBeVisible();
  await fontsReady(page);
  await motionsSettled(page);

  const target: Target = { toggle: `section[aria-label="${status}"] h2 button[aria-expanded]` };
  const closing = await watchReveal(page, target, true);
  await expect(column.getByRole('article')).toHaveCount(0);
  await motionsSettled(page);
  const opening = await watchReveal(page, target, false);

  report(`UI-112 столбец ${status}, свёртывание`, framesReport(closing));
  report(`UI-112 столбец ${status}, раскрытие`, {
    ...framesReport(opening),
    over: opening.frames.map((frame) => Math.round(frame.over)),
  });

  expectVisibleFollowsPlace('свёртывание столбца', closing);
  expectVisibleFollowsPlace('раскрытие столбца', opening);

  const last = opening.frames.at(-1);
  // Столбец переполнен: без своей прокрутки сжимать было бы нечего, и проверка ниже
  // прошла бы по другой причине.
  expect(last?.over, `столбцу ${status} нечего прокручивать`).toBeGreaterThan(0);

  const heights = opening.frames.map((frame) => frame.height);
  for (const [index, frame] of opening.frames.entries()) {
    const before = opening.frames[index - 1];
    if (before === undefined) continue;
    const step = JSON.stringify({ before, frame });
    expect(frame.height, `высота места убыла: ${step}`).toBeGreaterThanOrEqual(before.height);
    // Место тронулось и ещё не доехало — значит, в следующем кадре оно выше. Плато
    // ниже высоты содержимого — это и есть сжатие флексом.
    if (before.height > 0 && before.height < before.content) {
      expect(frame.height, `место стоит посреди хода: ${step}`).toBeGreaterThan(before.height);
    }
  }
  expect(last?.height, `место не дошло до содержимого: ${JSON.stringify(heights)}`).toBe(
    last?.content,
  );
});
