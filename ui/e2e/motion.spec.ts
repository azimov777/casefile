import { expect, test, type Page } from '@playwright/test';
import { readE2eToken, silenceJournal } from './contour';

/**
 * Сторож гашения: движение гасится **переменной**, а не перечислением переходов, —
 * значит и сторож не вправе быть перечислением мест.
 *
 * До UI-63 здесь проверялась одна кнопка «Изменить отбор». Пока движение было одного
 * рода, этого хватало; после UI-60, UI-61 и UI-62 родов стало три, а мест двадцать,
 * и проверка одной кнопки перестала что-либо говорить о правиле.
 *
 * Ничего не выписано руками. Словарь движения собирается обходом живых
 * `document.styleSheets` — все объявленные `--motion-*`, `--ease-*` и `--animate-*`;
 * места — обходом `document.querySelectorAll('*')` с отбором узлов, у которых
 * вычисленная длительность не ноль. Новое движение попадает под сторожа само.
 *
 * Чего этот сторож **не** проверяет и почему: он не отличает движение на токене
 * от движения на числе. Страховка `*` с `transition-duration: 0.01ms !important`
 * (`shared/styles/index.css`) гасит и то и другое, поэтому нарушение «длительность
 * написана числом» браузеру не видно вовсе — его ловит `src/shared/styles/motion.test.ts`
 * чтением исходников. Разделение и его причина — `UI-63#10`.
 */

const token = readE2eToken();

/** Длительность мала настолько, что движения не видно, мс (`0.01ms` в `index.css`). */
const EXTINGUISHED = 1;

interface Place {
  mark: string;
  transition: number;
  animation: number;
  /** Чем именно движется: список свойств перехода или имя `@keyframes`. */
  moves: string;
}

interface Reading {
  vocabulary: { token: string; value: string; duration: number | null }[];
  places: Place[];
}

test.beforeEach(async ({ context }) => {
  await context.addInitScript((value) => {
    window.localStorage.setItem('tracker.token', value);
  }, token);
});

/**
 * Приводит на экран движение всех трёх родов: переход по цвету живёт на любой кнопке,
 * переход по месту — в раскрытии отбора, `@keyframes` — в шторке.
 *
 * Экран узкий: ниже точки `fold` боковая панель уезжает в шторку, а шторка —
 * единственное движение `@keyframes`, до которого можно дойти без подменённого потока.
 * Раскрытие приходится открыть: свёрнутого узла в разметке нет вовсе — его не рисуют,
 * пока показывать нечего (`useExitHold`).
 */
async function motionOnScreen(page: Page): Promise<void> {
  await silenceJournal(page);
  await page.setViewportSize({ width: 600, height: 900 });
  await page.goto('/tasks?queue=DEMO');
  await expect(page.locator('tbody tr').first()).toBeVisible();

  await page.getByRole('button', { name: 'Изменить отбор' }).click();
  await expect(page.locator('[data-reveal="place"]')).toBeVisible();

  await page.getByRole('button', { name: /Показать разделы/ }).click();
  await expect(page.getByRole('dialog', { name: 'Разделы трекера' })).toBeVisible();
}

/**
 * Снимок движения страницы: словарь и места, оба найденные обходом.
 *
 * Числами, а не строками: браузер печатает те же `0.01ms` то как `0.0001s`, то как
 * `1e-05s`, и сравнение с текстом ломалось бы от формата, ничего не говоря о том,
 * видно движение или нет.
 */
function readMotion(page: Page): Promise<Reading> {
  return page.evaluate(() => {
    const ms = (value: string): number => {
      const number = Number.parseFloat(value);
      if (!Number.isFinite(number)) return 0;
      return value.trim().endsWith('ms') ? number : number * 1000;
    };
    const longest = (value: string): number => Math.max(0, ...value.split(',').map(ms));

    const root = getComputedStyle(document.documentElement);

    /*
     * Значение токена, развёрнутое до чисел. Браузер подставляет `var()` внутри
     * пользовательского свойства сам, но полагаться на это нельзя: неразвёрнутое
     * значение выглядело бы как «времени в токене нет», и проверка молча ослабла бы.
     */
    const unfold = (value: string): string => {
      let unfolded = value;
      for (let step = 0; step < 8 && unfolded.includes('var('); step += 1) {
        unfolded = unfolded.replace(/var\((--[\w-]+)\)/, (_, name: string) =>
          root.getPropertyValue(name).trim(),
        );
      }
      return unfolded.trim();
    };

    const names = new Set<string>();
    const walk = (rules: CSSRuleList): void => {
      for (const rule of Array.from(rules)) {
        const nested = (rule as CSSGroupingRule).cssRules as CSSRuleList | undefined;
        if (nested !== undefined) walk(nested);

        const style = (rule as CSSStyleRule).style as CSSStyleDeclaration | undefined;
        if (style === undefined) continue;
        for (const property of Array.from(style)) {
          if (/^--(motion|ease|animate)-/.test(property)) names.add(property);
        }
      }
    };
    for (const sheet of Array.from(document.styleSheets)) {
      try {
        walk(sheet.cssRules);
      } catch {
        // Чужой хост: правил такой таблицы не прочитать, и нашего словаря в ней нет.
      }
    }

    const vocabulary = [...names].sort().map((token) => {
      const value = unfold(root.getPropertyValue(token));
      const timed = /(?:^|\s)(\d*\.?\d+(?:e-?\d+)?m?s)(?:\s|$)/.exec(value);
      return { token, value, duration: timed === null ? null : ms(timed[1] as string) };
    });

    const places = [];
    for (const node of Array.from(document.querySelectorAll('*'))) {
      const style = getComputedStyle(node);
      const animated = style.animationName !== 'none' && style.animationName !== '';
      const transition = longest(style.transitionDuration);
      const animation = animated ? longest(style.animationDuration) : 0;
      if (transition === 0 && animation === 0) continue;

      const label = node.getAttribute('data-reveal') ?? node.getAttribute('data-notice');
      places.push({
        mark: `${node.tagName.toLowerCase()}${label === null ? '' : `[${label}]`}`,
        transition,
        animation,
        moves: animated ? style.animationName : style.transitionProperty,
      });
    }

    return { vocabulary, places };
  });
}

/** Роды движения, разложенные по тому, чем оно движется, а не по тому, где стоит. */
function kinds(places: Place[]): Record<string, Place[]> {
  const byKeyframes = places.filter((place) => place.animation > 0);
  const byTransition = places.filter((place) => place.animation === 0);
  return {
    'переход по цвету': byTransition.filter((place) => place.moves.includes('color')),
    'переход по месту и прозрачности': byTransition.filter(
      (place) => !place.moves.includes('color'),
    ),
    'движение по @keyframes': byKeyframes,
  };
}

test('движение находят обходом, а не перечнем: на экране есть все три рода', async ({ page }) => {
  await motionOnScreen(page);
  const { vocabulary, places } = await readMotion(page);

  // Гасить должно быть что: проверка ниже прошла бы и на интерфейсе вовсе без движения.
  const durations = vocabulary.filter(({ token }) => token.startsWith('--motion-'));
  expect(durations.length).toBeGreaterThan(0);
  for (const { token, duration } of durations) {
    expect(duration, `${token} обязан нести длительность`).not.toBeNull();
    expect(duration ?? 0, `${token} до просьбы не двигать`).toBeGreaterThan(1);
  }

  // Ни одно имя движения не осталось без длительности: имя без неё не поедет вовсе.
  for (const { token, duration } of vocabulary.filter((it) => it.token.startsWith('--animate-'))) {
    expect(duration, `${token} обязан брать длительность токеном`).not.toBeNull();
  }

  // Число мест не сверяется: счёт — тот же перечень, только в одной цифре. Сверяется,
  // что найден каждый род движения, — иначе сторож стерёг бы один род из трёх, как
  // стерёг одну кнопку до UI-63.
  for (const [kind, found] of Object.entries(kinds(places))) {
    expect(found.length, `род «${kind}» не найден на экране`).toBeGreaterThan(0);
  }
  expect(places.length).toBeGreaterThan(10);
});

test('человек просит не двигать интерфейс — гаснет всё найденное', async ({ page }) => {
  await motionOnScreen(page);
  const before = await readMotion(page);

  // `emulateMedia`, а не `contextOptions` в `test.use`: просьба не двигать интерфейс
  // приходит от системы в любой момент, и гасить движение надо на уже открытой
  // странице — ровно это здесь и проверяется.
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const after = await readMotion(page);

  // Переменная — то, чем гасят, и то, из чего задержку размонтирования читает
  // `exitDurationMs`: узел, придержанный на 120 мс без всякого движения, — тот же
  // дефект, только без кадров.
  for (const { token, duration } of after.vocabulary) {
    if (duration === null) continue;
    expect(duration, `${token} не погашен`).toBeLessThan(EXTINGUISHED);
  }

  // Из-под замера никто не ушёл: погашенное движение остаётся движением на `0.01ms`,
  // а не исчезает — переход обязан продолжать слать `transitionend`.
  expect(after.places.length).toBeGreaterThanOrEqual(before.places.length);

  for (const place of after.places) {
    expect(place.transition, `${place.mark} (${place.moves})`).toBeLessThan(EXTINGUISHED);
    expect(place.animation, `${place.mark} (${place.moves})`).toBeLessThan(EXTINGUISHED);
  }
});
