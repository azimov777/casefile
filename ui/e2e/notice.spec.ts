import { expect, test, type Page } from '@playwright/test';
import { curve, fontsReady, ms, readFrame, shellReady } from './contour';

/**
 * Подменяет живой поток: соединение отвечает нашим потоком, а кадры в него шлёт сам
 * тест вызовом `ask`.
 *
 * Так, а не подшивкой вопроса через API, по двум причинам. Первая: вопрос, заданный
 * по-настоящему, остаётся во входящей демо-установки, и убирать его пришлось бы
 * ответом — сценарий стал бы пишущим и уехал бы в проект «запись», хотя проверяет он
 * кадры, а не бэкенд. Вторая: уведомлений надо три и сразу, а три подшивки по сети —
 * это три разных момента прихода, то есть три разных состояния стопки.
 *
 * Настоящий SSE от начала до конца проверяет `live.spec.ts`; здесь подменена ровно
 * граница «что приехало в поток».
 */
async function fakeJournal(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const encoder = new TextEncoder();
    let sink: ReadableStreamDefaultController<Uint8Array> | null = null;
    const network = window.fetch.bind(window);

    window.fetch = (input, init) => {
      const address =
        typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (!address.includes('/api/v1/journal/stream')) return network(input, init);

      // Поток не кончается: клиент считает закрытие сервером обрывом и через паузу
      // переподключается, а нам нужно одно соединение на весь сценарий.
      const body = new ReadableStream<Uint8Array>({
        start: (controller) => {
          sink = controller;
        },
      });
      return Promise.resolve(
        new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } }),
      );
    };

    Object.assign(window, {
      ask: (question: { no: number; title: string }) => {
        const entry = {
          id: `00000000-0000-4000-8000-${String(question.no).padStart(12, '0')}`,
          seq: 900_000 + question.no,
          no: question.no,
          // Вопрос задан не по той задаче, что открыта на экране: иначе кадр перечитал бы
          // её ленту, и в замере смешались бы две причины сдвига.
          task_key: 'DEMO-4',
          author: { kind: 'agent', signature: 'demo_agent' },
          title: question.title,
          body: '',
          created_at: '2026-09-01T10:00:00Z',
          type: 'question',
          payload: { addressees: ['owner'], blocking: false },
        };
        sink?.enqueue(encoder.encode(`data: ${JSON.stringify(entry)}\n\n`));
      },
    });
  });
}

/** Шлёт кадр с вопросом ко мне в подменённый поток. */
async function ask(page: Page, no: number, title: string): Promise<void> {
  await page.evaluate(
    (question) =>
      (window as unknown as { ask: (asked: { no: number; title: string }) => void }).ask(question),
    { no, title },
  );
}

/** Стопка уведомлений. */
function stack(page: Page) {
  return page.getByRole('complementary', { name: 'Вопросы ко мне' });
}

/**
 * Кадр ухода карточки: узел живёт ровно столько, сколько идёт движение, и снаружи
 * успеть некуда — 120 мс короче цепочки «нажми, дождись, прочитай». Поэтому карточку
 * закрывает сам браузер, а замер снимается на `animationstart` выхода.
 */
function readExitFrame(node: Element) {
  return new Promise<{ name: string; duration: string; easing: string }>((resolve) => {
    node.addEventListener(
      'animationstart',
      () => {
        const style = getComputedStyle(node);
        resolve({
          name: style.animationName,
          duration: style.animationDuration,
          easing: style.animationTimingFunction,
        });
      },
      { once: true },
    );
    node.querySelector<HTMLElement>('button[aria-label^="Закрыть уведомление"]')?.click();
  });
}

/** Ждёт, пока приход доедет: замер кадра выхода не должен поймать хвост входа. */
async function motionSettled(page: Page): Promise<void> {
  await stack(page).evaluate((node) =>
    Promise.all(node.getAnimations({ subtree: true }).map((animation) => animation.finished)),
  );
}

test('уведомление о вопросе приходит и уходит движением из словаря', async ({ page }) => {
  await fakeJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
  // Кадр, пришедший раньше участника, уведомления не даст: «спросили ли меня»
  // сверяется с именем из `bootstrap`, а он приезжает после первой отрисовки.
  await shellReady(page);

  // Кадры сверяются с токенами словаря движения, а не с числами: число, написанное
  // в разметке, вывело бы уведомление из-под `prefers-reduced-motion`, и проверка
  // на число такую подмену пропустила бы.
  const motion = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    return {
      fast: root.getPropertyValue('--motion-fast'),
      slow: root.getPropertyValue('--motion-slow'),
      enter: root.getPropertyValue('--ease-fast'),
      exit: root.getPropertyValue('--ease-exit'),
    };
  });

  await ask(page, 31, 'Вопрос из подменённого потока');
  const card = stack(page).locator('article');
  await expect(card).toBeVisible();

  // Пришло само и требует внимания: медленный конец словаря и кривая входа.
  const entering = await card.evaluate(readFrame);
  expect(entering.name).toBe('appear');
  expect(ms(entering.duration)).toBe(ms(motion.slow));
  expect(curve(entering.easing)).toBe(curve(motion.enter));

  await motionSettled(page);

  // Уход отвечает человеку и потому вдвое короче входа, а кривая у него своя: он
  // разгоняется и уходит, а не замирает на последнем кадре (`UI-59#11`).
  const leaving = await card.evaluate(readExitFrame);
  expect(leaving.name).toBe('disappear');
  expect(ms(leaving.duration)).toBe(ms(motion.fast));
  expect(curve(leaving.easing)).toBe(curve(motion.exit));
  expect(ms(entering.duration)).toBe(ms(leaving.duration) * 2);

  // Узел дожил до конца выхода и снят после него: движение показано, а не оборвано.
  await expect(card).toHaveCount(0);
  // Область объявления осталась: она обязана существовать до следующего вопроса.
  await expect(stack(page)).toBeAttached();
});

test('закрытое уведомление не дёргает ни соседей по стопке, ни дело под ней', async ({ page }) => {
  await fakeJournal(page);
  await page.goto('/tasks/DEMO-1/case');
  await expect(page.locator('article[data-type]').first()).toBeVisible();
  // Замеры снимаются уже подставленным шрифтом: Fira меняет метрику после первой
  // отрисовки, и разница «до и после» оказалась бы разницей гарнитур.
  await fontsReady(page);
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
  // Кадр, пришедший раньше участника, уведомления не даст: «спросили ли меня»
  // сверяется с именем из `bootstrap`, а он приезжает после первой отрисовки.
  await shellReady(page);

  for (const no of [41, 42, 43]) {
    await ask(page, no, `Вопрос ${no} из подменённого потока`);
  }
  await expect(stack(page).locator('article')).toHaveCount(3);
  await motionSettled(page);

  const motion = await page.evaluate(() => {
    const root = getComputedStyle(document.documentElement);
    return {
      fast: root.getPropertyValue('--motion-fast'),
      exit: root.getPropertyValue('--ease-exit'),
    };
  });

  /*
   * Закрывает среднее уведомление и снимает положения по кадрам — изнутри браузера,
   * потому что снаружи 120 мс успевают кончиться раньше первого замера.
   *
   * Смотрят за тремя вещами: соседи по стопке (верхнему предстоит съехать вниз на
   * место закрытого, нижнему — не двигаться вовсе) и первая запись ленты, которую
   * человек в этот момент читает.
   */
  const seen = await page.evaluate(() => {
    interface Sample {
      at: number;
      above: number;
      below: number;
      entryTop: number;
      entryOpacity: string;
    }

    return new Promise<{
      place: { running: boolean; property: string; duration: string; easing: string };
      before: Sample;
      frames: Sample[];
    }>((resolve, reject) => {
      const cards = Array.from(
        document.querySelectorAll<HTMLElement>('[aria-label="Вопросы ко мне"] article'),
      );
      const entry = document.querySelector('article[data-type]');
      if (cards.length !== 3 || entry === null) {
        reject(new Error(`ожидались три уведомления и лента, а найдено ${cards.length}`));
        return;
      }

      const [above, middle, below] = cards;
      const place = middle.closest<HTMLElement>('[data-notice="place"]');
      if (place === null) {
        reject(new Error('у карточки нет узла места'));
        return;
      }

      const started = performance.now();
      const sample = (): Sample => ({
        at: Math.round(performance.now() - started),
        above: Math.round(above.getBoundingClientRect().top),
        below: Math.round(below.getBoundingClientRect().top),
        entryTop: Math.round(entry.getBoundingClientRect().top),
        entryOpacity: getComputedStyle(entry).opacity,
      });

      const before = sample();
      const frames: Sample[] = [];

      middle.addEventListener(
        'animationstart',
        () => {
          /*
           * Место карточки едет своим движением, и снимается оно отдельно: без него
           * стопка простояла бы все 120 мс и схлопнулась бы в один кадр после них.
           * Что движение идёт прямо сейчас, а не только объявлено, видно по тому, что
           * у узла есть живая анимация; длительность и кривую отдаёт вычисленный стиль
           * (у перехода они лежат на кадрах, а не на самом эффекте).
           */
          const style = getComputedStyle(place);
          const moving = {
            running: place.getAnimations().length > 0,
            property: style.transitionProperty,
            duration: style.transitionDuration,
            easing: style.transitionTimingFunction,
          };

          const tick = () => {
            frames.push(sample());
            if (performance.now() - started < 400) {
              requestAnimationFrame(tick);
              return;
            }
            resolve({ place: moving, before, frames });
          };
          tick();
        },
        { once: true },
      );

      cards[1].querySelector<HTMLElement>('button[aria-label^="Закрыть уведомление"]')?.click();
    });
  });

  // Место закрытой карточки едет тем же движением, что и она сама, и едет прямо сейчас.
  expect(seen.place.running).toBe(true);
  expect(seen.place.property).toBe('grid-template-rows');
  expect(ms(seen.place.duration)).toBe(ms(motion.fast));
  expect(curve(seen.place.easing)).toBe(curve(motion.exit));

  const moved = seen.frames.map((frame) => frame.above);
  const settled = moved[moved.length - 1];

  // Сосед снизу стоит: закрытая карточка забирает место только у тех, кто над ней.
  expect(seen.frames.map((frame) => frame.below)).toEqual(seen.frames.map(() => seen.before.below));
  // Сосед сверху съехал вниз ровно на место закрытой, а не остался висеть.
  expect(settled).toBeGreaterThan(seen.before.above);

  // Место не схлопнулось разом: на первом же снятом кадре сосед ещё в пути.
  expect(moved[0]).toBeLessThan(settled);
  // И дальше он ехал, а не прыгнул: самый большой шаг за кадр меньше всего пути.
  const steps = moved.map(
    (top, index) => top - (index === 0 ? seen.before.above : moved[index - 1]),
  );
  expect(Math.max(...steps)).toBeLessThan(settled - seen.before.above);

  // Дело под уведомлением человек читает: оно не двигается и не гаснет ни на кадр.
  expect(seen.frames.map((frame) => frame.entryTop)).toEqual(
    seen.frames.map(() => seen.before.entryTop),
  );
  expect(seen.frames.map((frame) => frame.entryOpacity)).toEqual(seen.frames.map(() => '1'));

  // Ушло ровно одно уведомление: стопка редеет по одному.
  await expect(stack(page).locator('article')).toHaveCount(2);
});

/** Числа замера — в отчёт прогона: по ним пишется вердикт, а не по зелёной строке. */
function report(type: string, numbers: unknown): void {
  const description = JSON.stringify(numbers);
  test.info().annotations.push({ type, description });
  console.log(`[${type}] ${description}`);
}

/** Кадр места карточки в стопке: его высота и где низ места и низ прослойки в нём. */
interface PlaceFrame {
  /** Миллисекунды от начала наблюдения. */
  at: number;
  /** Высота места `data-notice="place"`. */
  height: number;
  /** Низ места. */
  place: number;
  /** Низ прослойки `min-h-0` — того, что несёт карточку внутри места. */
  layer: number;
  /** Непрозрачность самой карточки: у неё своё движение, и оно тоже обязано доехать. */
  opacity: number;
}

interface PlaceWatch {
  /** Движение места в первом кадре, где место есть: идёт ли прямо сейчас и чем. */
  motion: { running: boolean; property: string } | null;
  frames: PlaceFrame[];
  timedOut: boolean;
}

/**
 * Снимает место карточки по кадрам — изнутри браузера, по той же причине, что и
 * соседний сценарий: снаружи 120 мс ухода кончаются раньше первого замера.
 *
 * Приход (`leave: false`): наблюдение ставится до кадра потока с вопросом, и кадр шлёт
 * сам браузер; кончается, когда место доехало и три кадра простояло. Уход
 * (`leave: true`): карточку закрывает сам браузер; наблюдение кончается, когда узел
 * снят и три кадра его нет.
 */
async function watchPlace(
  page: Page,
  question: { no: number; title: string },
  leave: boolean,
): Promise<PlaceWatch> {
  return page.evaluate(
    ({ question: asked, leave: leaving }) =>
      new Promise<PlaceWatch>((resolve, reject) => {
        const find = () =>
          Array.from(document.querySelectorAll<HTMLElement>('[data-notice="place"]')).find(
            (node) => node.textContent?.includes(asked.title) === true,
          );
        let place = leaving ? find() : undefined;
        if (leaving && place === undefined) {
          reject(new Error('закрываемой карточки на странице нет'));
          return;
        }

        const started = performance.now();
        const record: PlaceWatch = { motion: null, frames: [], timedOut: false };
        let calm = 0;

        const tick = () => {
          place ??= find();
          if (place?.isConnected === true) {
            // Что движение идёт прямо сейчас, видно по живой анимации на самом месте,
            // а не на карточке внутри него: у карточки движение своё.
            record.motion ??= {
              running: place.getAnimations().length > 0,
              property: getComputedStyle(place).transitionProperty,
            };
            const box = place.getBoundingClientRect();
            const layer = place.firstElementChild?.getBoundingClientRect();
            const card = place.querySelector('article');
            if (layer === undefined || card === null) {
              reject(new Error('у места карточки нет прослойки или самой карточки'));
              return;
            }
            record.frames.push({
              at: Math.round(performance.now() - started),
              height: box.height,
              place: box.bottom,
              layer: layer.bottom,
              opacity: Number(getComputedStyle(card).opacity),
            });
          }

          const resting = leaving
            ? place?.isConnected !== true
            : place !== undefined && place.getAnimations().length === 0;
          calm = resting ? calm + 1 : 0;
          if (calm >= 3 || performance.now() - started > 10_000) {
            record.timedOut = calm < 3;
            resolve(record);
            return;
          }
          requestAnimationFrame(tick);
        };

        if (leaving) {
          place?.querySelector<HTMLElement>('button[aria-label^="Закрыть уведомление"]')?.click();
        } else {
          (window as unknown as { ask: (sent: { no: number; title: string }) => void }).ask(asked);
        }
        requestAnimationFrame(tick);
      }),
    { question, leave },
  );
}

/**
 * Карточка держится нижнего края своего места на всём ходу, а не только в покое
 * (UI-110). Chrome считает долю `fr` у места дважды: высоту месту — по содержимому,
 * а строку — ещё раз, от этой высоты. Строка выходит короче места, и без `content-end`
 * стоит у его верха: посреди хода карточка всплывала бы над низом места на f(1−f) своей
 * высоты и съезжала обратно. Прячется это за собственным движением карточки, а соседний
 * сценарий мерит соседей по стопке и дело под ней — поэтому мерится сама прослойка.
 */
test('карточка стоит у нижнего края своего места на всём приходе и уходе', async ({ page }) => {
  await fakeJournal(page);
  await page.goto('/tasks/DEMO-1/case');
  await expect(page.locator('article[data-type]').first()).toBeVisible();
  await fontsReady(page);
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
  // Кадр, пришедший раньше участника, уведомления не даст: «спросили ли меня»
  // сверяется с именем из `bootstrap`, а он приезжает после первой отрисовки.
  await shellReady(page);

  // Карточки две: и приход, и уход идут в стопке с соседом, как у человека.
  const first = { no: 61, title: 'Вопрос 61, который закроют' };
  const second = { no: 62, title: 'Вопрос 62, который придёт к уже висящему' };
  await ask(page, first.no, first.title);
  await expect(stack(page).locator('article')).toHaveCount(1);
  await motionSettled(page);

  const arrival = await watchPlace(page, second, false);
  await expect(stack(page).locator('article')).toHaveCount(2);
  await motionSettled(page);
  const departure = await watchPlace(page, first, true);
  await expect(stack(page).locator('article')).toHaveCount(1);

  const watches = [
    ['приход', arrival],
    ['уход', departure],
  ] as const;
  // Числа обоих ходов — в отчёт до первого ожидания: упавший приход не прячет ухода.
  for (const [name, watch] of watches) {
    report(`UI-110 ${name}`, {
      frames: watch.frames.length,
      at: watch.frames.map((frame) => frame.at),
      height: watch.frames.map((frame) => Math.round(frame.height * 10) / 10),
      gap: watch.frames.map((frame) => Math.round((frame.place - frame.layer) * 10) / 10),
    });
  }

  for (const [name, watch] of watches) {
    const heights = watch.frames.map((frame) => frame.height);
    const gaps = watch.frames.map((frame) => frame.place - frame.layer);

    expect(watch.timedOut, `${name}: место не доехало или не снялось`).toBe(false);
    // Место ехало, и ехало прямо сейчас: без этого проверка ниже была бы пустой.
    expect(watch.motion?.running, name).toBe(true);
    expect(watch.motion?.property, name).toBe('grid-template-rows');
    const low = Math.min(...heights);
    const high = Math.max(...heights);
    expect(
      heights.some((height) => height > low && height < high),
      `${name}: ни одного кадра посреди хода`,
    ).toBe(true);

    // На каждом кадре низ прослойки — это низ места: карточка не всплывает над ним.
    // Числа одного источника (`getBoundingClientRect`), поэтому сравниваются точно.
    expect(
      Math.max(...gaps.map((gap) => Math.abs(gap))),
      `${name}: низ карточки ушёл от низа места, ${JSON.stringify(gaps)}`,
    ).toBe(0);
  }
});

/**
 * Выход доезжает до конца раньше, чем узел снимают (UI-111). Узел держит общая
 * задержка размонтирования (`shared/lib/exit-hold.ts`), и снятый посреди выхода он
 * обнулил бы остаток хода места одним кадром — тем самым рывком, от которого место
 * и едет. Мерится последний кадр, где узел ещё в разметке: место в нём уже схлопнулось.
 */
test('закрытая карточка доезжает до конца выхода раньше, чем её снимают', async ({ page }) => {
  await fakeJournal(page);
  await page.goto('/tasks/DEMO-1/case');
  await expect(page.locator('article[data-type]').first()).toBeVisible();
  await fontsReady(page);
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
  // Кадр, пришедший раньше участника, уведомления не даст: «спросили ли меня»
  // сверяется с именем из `bootstrap`, а он приезжает после первой отрисовки.
  await shellReady(page);

  const closed = { no: 71, title: 'Вопрос 71, который закроют' };
  const kept = { no: 72, title: 'Вопрос 72, который останется' };
  await ask(page, closed.no, closed.title);
  await ask(page, kept.no, kept.title);
  await expect(stack(page).locator('article')).toHaveCount(2);
  await motionSettled(page);

  const departure = await watchPlace(page, closed, true);
  await expect(stack(page).locator('article')).toHaveCount(1);
  const last = departure.frames.at(-1);
  report('UI-111 уход карточки', {
    frames: departure.frames.length,
    at: departure.frames.map((frame) => frame.at),
    height: departure.frames.map((frame) => Math.round(frame.height * 10) / 10),
    opacity: departure.frames.map((frame) => Math.round(frame.opacity * 1000) / 1000),
  });

  expect(departure.timedOut, 'узел не снялся').toBe(false);
  // Место ехало прямо сейчас: иначе последний кадр был бы нулём по другой причине.
  expect(departure.motion?.running).toBe(true);
  expect(departure.frames.length).toBeGreaterThan(1);
  // В последнем кадре, где узел ещё в разметке, место уже доехало до нуля само,
  // а не обнуляется снятием узла.
  expect(last?.height, `место снято на ${JSON.stringify(last)}`).toBeLessThanOrEqual(1);
  // И собственное движение карточки не срезано: к этому кадру она уже погасла.
  expect(last?.opacity, `карточка снята на ${JSON.stringify(last)}`).toBe(0);
});

test('человек просит не двигать интерфейс — уведомление перестаёт ехать', async ({ page }) => {
  await fakeJournal(page);
  await page.goto('/tasks?queue=DEMO');
  await expect(page.getByRole('banner').getByText('на связи')).toBeVisible();
  // Кадр, пришедший раньше участника, уведомления не даст: «спросили ли меня»
  // сверяется с именем из `bootstrap`, а он приезжает после первой отрисовки.
  await shellReady(page);

  // Просьба приходит от системы в любой момент, в том числе на открытой странице.
  await page.emulateMedia({ reducedMotion: 'reduce' });

  await ask(page, 51, 'Вопрос при погашенном движении');
  const card = stack(page).locator('article');
  await expect(card).toBeVisible();

  /*
   * Гасятся оба конца, и гасит их переменная, а не перечисление: длительность взята
   * токеном, который `index.css` переопределяет в `0.01ms`. Сравнение числом — браузер
   * печатает те же `0.01ms` то как `0.0001s`, то как `1e-05s`.
   *
   * Кадр ухода здесь снимается подменой имени движения на живом узле, а не на
   * `animationstart`, как в движущемся случае: погашенный узел до этого события
   * не доживает. Вместе с движением гаснет и задержка размонтирования — узел
   * снимается в том же кадре, и это ровно то, о чём человек просил.
   */
  const quiet = await card.evaluate((node) => {
    const entering = getComputedStyle(node).animationDuration;
    node.classList.remove('animate-appear');
    node.classList.add('animate-disappear');
    return { entering, leaving: getComputedStyle(node).animationDuration };
  });
  expect(ms(quiet.entering)).toBeLessThan(1);
  expect(ms(quiet.leaving)).toBeLessThan(1);

  // И уведомление всё равно приходит и закрывается: гашение убирает кадры, а не
  // поведение.
  await card.getByRole('button', { name: /^Закрыть уведомление/ }).click();
  await expect(card).toHaveCount(0);
});
