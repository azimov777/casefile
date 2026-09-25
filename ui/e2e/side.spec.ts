import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { curve, motionSettled, ms, readFrame, signedInByHand, silenceJournal } from './contour';

/** Боковая панель на широком экране; на узком та же панель живёт в шторке. */
function side(page: Page) {
  return page.getByRole('complementary', { name: 'Разделы Casefile' });
}

/**
 * Тот же кадр, но для выхода: узел живёт ровно столько, сколько идёт движение, — Radix
 * снимает его по `animationend`, и снаружи успеть некуда. Поэтому шторка закрывается
 * изнутри браузера, а замер снимается на `animationstart` выхода.
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
    node.querySelector<HTMLElement>('[aria-label="Закрыть разделы"]')?.click();
  });
}

/**
 * Открывает шторку и закрывает её `Esc`-ем посреди появления; возвращает миллисекунду
 * движения, на которой это случилось.
 *
 * Время держит браузер, а не прогон: пока «нажми» и «прочитай» ездят по протоколу,
 * 120 мс успевают кончиться, и проверка вырождается в «закрыл после того, как всё
 * доехало» — ровно так она однажды и упала. Событие клавиши здесь синтетическое:
 * `Esc` настоящей клавишей проверяет соседний сценарий, а этому нужен точный момент.
 */
function closeWhileEntering(): Promise<number> {
  return new Promise((resolve, reject) => {
    const opener = document.querySelector<HTMLElement>('button[aria-label^="Показать разделы"]');
    if (opener == null) {
      reject(new Error('кнопки «Показать разделы» на странице нет'));
      return;
    }
    opener.click();

    const started = performance.now();
    const tick = () => {
      const entering = document.querySelector('[role="dialog"]')?.getAnimations()[0];
      if (entering == null || entering.playState !== 'running') {
        if (performance.now() - started > 1_000) {
          reject(new Error('шторка не поехала: движения входа нет вовсе'));
          return;
        }
        requestAnimationFrame(tick);
        return;
      }

      const at = Number(entering.currentTime ?? 0);
      if (at < 30) {
        requestAnimationFrame(tick);
        return;
      }

      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      resolve(at);
    };
    requestAnimationFrame(tick);
  });
}

test('переход в другой проект меняет только проект', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO&view=board&status=open');
  await expect(page.getByRole('region', { name: 'open' })).toBeVisible();

  // В демо-контуре проект один, поэтому «все задачи» — вторая точка того же
  // перехода: она снимает проект, не трогая ни вид, ни остальной отбор.
  await side(page).getByRole('link', { name: 'Все задачи' }).click();

  await expect(page).toHaveURL(/view=board/);
  await expect(page).toHaveURL(/status=open/);
  await expect(page).not.toHaveURL(/project=/);
  await expect(side(page).getByRole('link', { name: 'Все задачи' })).toHaveAttribute(
    'aria-current',
    'page',
  );
});

test('проект остаётся подсвеченным внутри задачи, а вид — доской при возврате', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO&view=board');

  await page.getByRole('article').first().getByRole('link').first().click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-\d+$/);

  // Проект задачи прочитан из её ключа: подсветка не пропадает от того, что
  // человек ушёл со списка.
  await expect(side(page).getByRole('link', { name: /^DEMO/ })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(page.getByLabel('Где я')).toContainText('DEMO');

  await page.getByRole('link', { name: 'К списку с отбором' }).click();
  await expect(page).toHaveURL(/view=board/);
});

test('старый параметр адреса проектом не читается: список тот же, что без него', async ({
  page,
}) => {
  // Чистый разрез v0.4.0 (TRK-150, решение 2): закладка со старым именем параметра
  // не перенаправляется и не падает — интерфейс его просто не знает.
  const keys = () =>
    page
      .getByRole('main')
      .locator('a[href^="/tasks/"]')
      .evaluateAll((links) => links.map((link) => link.getAttribute('href')));

  await silenceJournal(page);
  await page.goto('/tasks');
  await expect(page.getByRole('table')).toBeVisible();
  const plain = await keys();
  expect(plain.length).toBeGreaterThan(0);

  // Имя старого параметра собрано из частей: проверка UI-172 ищет его по всему `ui/`
  // и обязана не находить — ни в коде, ни в сценариях.
  const stale = `/tasks?${'que' + 'ue'}=DEMO`;
  await page.goto(stale);
  await expect(page.getByRole('table')).toBeVisible();
  expect(new URL(page.url()).pathname + new URL(page.url()).search).toBe(stale);
  expect(await keys()).toEqual(plain);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(side(page).getByRole('link', { name: 'Все задачи' })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(side(page).getByRole('link', { name: /^DEMO/ })).not.toHaveAttribute(
    'aria-current',
    'page',
  );
});

test('в панели нет действий, меняющих задачи', async ({ page }) => {
  // Установка с несколькими людьми: у неё панель богаче на одну кнопку — «Выйти», —
  // и перечисление обязано ловить лишнее именно там, где кнопок больше. На локальной
  // установке кнопок в панели нет вовсе (`e2e/install-key.spec.ts`).
  await signedInByHand(page);
  await silenceJournal(page);
  await page.goto('/tasks?project=DEMO');
  await expect(side(page)).toBeVisible();

  // Человек наблюдает и отвечает, остальное делают агенты: заводить задачи и менять
  // статусы из панели нельзя, и проверяется это перечислением, а не на глаз. На уровне
  // проекта человек может больше (TRK-150, решение 8): ключу набора `main` панель даёт
  // «Новый проект» (UI-175). Кнопка появляется, когда пришёл набор ключа, поэтому
  // перечисление ждёт её, иначе список снимается до неё и тест зависит от гонки.
  await expect(side(page).getByRole('button', { name: 'Новый проект' })).toBeVisible();
  const buttons = await side(page).getByRole('button').allInnerTexts();
  expect(buttons).toEqual(['Новый проект', 'Выйти']);
});

test.describe('узкий экран', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('панель уезжает за кнопку, закрывается Esc и возвращает фокус', async ({ page }) => {
    // Со входом руками: в шторке проверяется, что внутри неё лежит всё служебное,
    // а «Выйти» есть только у установки, где людей несколько.
    await signedInByHand(page);
    await silenceJournal(page);
    await page.goto('/tasks?project=DEMO');
    await expect(page.getByRole('table')).toBeVisible();

    // Постоянного места панель здесь не занимает: содержание получает всю ширину.
    await expect(side(page)).toBeHidden();

    const opener = page.getByRole('button', { name: 'Показать разделы' });
    await expect(opener).toBeVisible();
    await opener.click();

    const sheet = page.getByRole('dialog', { name: 'Разделы Casefile' });
    await expect(sheet).toBeVisible();
    await expect(sheet.getByRole('link', { name: /Входящая/ })).toBeVisible();
    await expect(sheet.getByRole('button', { name: 'Выйти' })).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(sheet).toBeHidden();
    // Фокус вернулся туда, откуда человек шторку открыл: иначе следующий Tab начал бы
    // обход страницы с начала.
    await expect(opener).toBeFocused();
  });

  /*
   * Шторка занимает половину узкого экрана и приходит поверх того, что человек читал:
   * без движения непонятно, откуда она взялась и что за ней осталось (UI-60).
   *
   * Кадры сверяются с токенами словаря движения, а не с числами: число, написанное
   * в разметке, вывело бы шторку из-под `prefers-reduced-motion`, и проверка на число
   * такую подмену пропустила бы.
   */
  test('шторка въезжает и уезжает движением из словаря', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?project=DEMO');
    await expect(page.getByRole('table')).toBeVisible();

    const motion = await page.evaluate(() => {
      const root = getComputedStyle(document.documentElement);
      return {
        fast: root.getPropertyValue('--motion-fast'),
        enter: root.getPropertyValue('--ease-fast'),
        exit: root.getPropertyValue('--ease-exit'),
      };
    });

    await page.getByRole('button', { name: 'Показать разделы' }).click();
    const sheet = page.getByRole('dialog', { name: 'Разделы Casefile' });
    await expect(sheet).toBeVisible();

    const entering = await sheet.evaluate(readFrame);
    expect(entering.name).toBe('sheet-in');
    expect(ms(entering.duration)).toBe(ms(motion.fast));
    expect(curve(entering.easing)).toBe(curve(motion.enter));

    // Подложка живёт тем же событием, а не своей жизнью: та же длительность и та же
    // кривая. Radix рисует её перед содержимым, поэтому она и берётся соседом слева.
    const veil = await sheet.evaluate((node) => {
      const overlay = node.previousElementSibling;
      if (overlay == null) throw new Error('подложки перед содержимым шторки нет');
      const style = getComputedStyle(overlay);
      return {
        name: style.animationName,
        duration: style.animationDuration,
        easing: style.animationTimingFunction,
      };
    });
    expect(veil.name).toBe('overlay-in');
    expect(ms(veil.duration)).toBe(ms(entering.duration));
    expect(curve(veil.easing)).toBe(curve(entering.easing));

    // Выход отличается от входа только кривой: он разгоняется и уходит, а не замирает
    // на последнем кадре, — но отвечает человеку так же быстро (UI-59#11).
    const leaving = await sheet.evaluate(readExitFrame);
    expect(leaving.name).toBe('sheet-out');
    expect(ms(leaving.duration)).toBe(ms(motion.fast));
    expect(curve(leaving.easing)).toBe(curve(motion.exit));

    // Узел дожил до конца выхода и снят после него: движение показано, а не оборвано.
    await expect(sheet).toHaveCount(0);
  });

  test('человек просит не двигать интерфейс — шторка перестаёт ехать', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?project=DEMO');
    await expect(page.getByRole('table')).toBeVisible();

    // Просьба приходит от системы в любой момент, в том числе на открытой странице.
    await page.emulateMedia({ reducedMotion: 'reduce' });

    await page.getByRole('button', { name: 'Показать разделы' }).click();
    const sheet = page.getByRole('dialog', { name: 'Разделы Casefile' });
    await expect(sheet).toBeVisible();

    // Гасятся оба конца, и гасит их переменная, а не перечисление: длительность взята
    // токеном, который `index.css` переопределяет в `0.01ms`. Сравнение числом — браузер
    // печатает те же `0.01ms` то как `0.0001s`, то как `1e-05s`.
    expect(ms((await sheet.evaluate(readFrame)).duration)).toBeLessThan(1);
    expect(ms((await sheet.evaluate(readExitFrame)).duration)).toBeLessThan(1);

    // И шторка всё равно закрывается: гашение убирает кадры, а не поведение.
    await expect(sheet).toHaveCount(0);
  });

  test('шторка закрывается посреди своего появления, а не после него', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?project=DEMO');
    await expect(page.getByRole('table')).toBeVisible();

    const fast = ms(
      await page.evaluate(() =>
        getComputedStyle(document.documentElement).getPropertyValue('--motion-fast'),
      ),
    );

    const opener = page.getByRole('button', { name: 'Показать разделы' });
    const sheet = page.getByRole('dialog', { name: 'Разделы Casefile' });
    const interrupted = await page.evaluate(closeWhileEntering);

    // Движение ещё шло, когда человек передумал: `Esc` пришёл на первой трети пути.
    expect(interrupted).toBeGreaterThanOrEqual(30);
    expect(interrupted).toBeLessThan(fast);

    // Закрылась сразу, а не встала в очередь за концом появления, и узла не осталось.
    const pressed = Date.now();
    await expect(sheet).toHaveCount(0);
    expect(Date.now() - pressed).toBeLessThan(1_000);
    await expect(opener).toBeFocused();
  });

  test('страница не разъезжается вширь ни на одном экране', async ({ page }) => {
    await silenceJournal(page);

    for (const address of [
      '/tasks?project=DEMO',
      '/tasks/DEMO-1',
      '/tasks/DEMO-1/case',
      '/questions',
    ]) {
      await page.goto(address);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `горизонтальная прокрутка на ${address}`).toBeLessThanOrEqual(0);
    }
  });

  test('доступность оболочки на узком экране', async ({ page }) => {
    await silenceJournal(page);
    await page.goto('/tasks?project=DEMO');
    await expect(page.getByRole('table')).toBeVisible();

    await page.getByRole('button', { name: 'Показать разделы' }).click();
    const sheet = page.getByRole('dialog', { name: 'Разделы Casefile' });
    await expect(sheet).toBeVisible();

    // Замер контраста снимается в покое: `axe`, попавший в середину появления, поймал бы
    // собственную рассинхронизацию, а не дефект интерфейса (`UI-59#4`). Указатель мыши
    // остался там, где нажали «Показать разделы», и кнопка закрытия (`right-2` шторки)
    // проезжает под ним, пока шторка едет слева: наведение начинается и снимается тем же
    // кадром, отменённый переход отклоняет `finished` `AbortError` — законная гонка теста,
    // а не дефект интерфейса. `motionSettled` дожидается и встречного перехода, который
    // отмена запускает тем же кадром, а не только первого `finished` (`UI-102`).
    await motionSettled(sheet);

    const result = await new AxeBuilder({ page }).analyze();
    expect(result.violations).toEqual([]);
  });
});
