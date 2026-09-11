import { expect, test, type Locator, type Page } from '@playwright/test';
import { silenceJournal } from './contour';

/*
 * Язык говорит не только подписями (UI-79). Здесь проверяется то, что подписью
 * не является: что страница сообщает о себе браузеру и программе чтения с экрана,
 * как называется вкладка и на каком языке отбиты форматы времени.
 *
 * Часовой пояс у обоих языков один и назван явно: проверяется, что от языка он
 * не зависит, а значит и сравнивать надо в одном поясе.
 */
const ZONE = 'America/New_York';

/** Дело демо-задачи: лента записей, и в каждой записи — подпись времени. */
const CASE = '/tasks/DEMO-1/case';

const SWITCH = { en: 'Interface language', ru: 'Язык интерфейса' };
const NAME = { en: 'Casefile', ru: 'Casefile' };

test.beforeEach(async ({ page }) => {
  await silenceJournal(page);
});

/** Первая подпись времени в ленте дела: тег `time` с машинной меткой и подсказкой. */
function firstTime(page: Page): Locator {
  return page.locator('article time[title]').first();
}

async function switchTo(page: Page, from: 'en' | 'ru', to: 'English' | 'Русский'): Promise<void> {
  await page.getByRole('combobox', { name: SWITCH[from] }).click();
  await page.getByRole('option', { name: to }).click();
}

test.describe('английский интерфейс', () => {
  test.use({ locale: 'en-US', timezoneId: ZONE });

  test('страница объявляет себя английской, и вкладка называется по-английски', async ({
    page,
  }) => {
    await page.goto(CASE);
    await expect(firstTime(page)).toBeVisible();

    // Атрибут стоит с первого кадра, а не после первой отрисовки: ставит его
    // `syncDocumentLanguage()` до `createRoot`.
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page).toHaveTitle(NAME.en);
  });

  test('подписи времени и точная дата в подсказке — английские', async ({ page }) => {
    await page.goto(CASE);

    const stamp = firstTime(page);
    await expect(stamp).toBeVisible();

    // Кириллицы нет ни в подписи, ни в подсказке: «3 мин. назад» и «10 сентября 2026 г.»
    // на английском экране — ровно то, ради чего заведена задача.
    expect(await stamp.innerText()).not.toMatch(/[А-Яа-яЁё]/);
    expect(await stamp.getAttribute('title')).not.toMatch(/[А-Яа-яЁё]/);
    // Месяц назван словом, и слово это английское.
    expect(await stamp.getAttribute('title')).toMatch(
      /January|February|March|April|May|June|July|August|September|October|November|December/,
    );
  });
});

test.describe('русский интерфейс', () => {
  test.use({ locale: 'ru-RU', timezoneId: ZONE });

  test('страница объявляет себя русской, и вкладка называется по-русски', async ({ page }) => {
    await page.goto(CASE);
    await expect(firstTime(page)).toBeVisible();

    await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
    await expect(page).toHaveTitle(NAME.ru);
  });
});

test.describe('смена языка', () => {
  test.use({ locale: 'en-US', timezoneId: ZONE });

  test('меняет `lang`, заголовок вкладки и формат времени сразу, без перезагрузки', async ({
    page,
  }) => {
    await page.goto(CASE);

    const stamp = firstTime(page);
    await expect(stamp).toBeVisible();

    const english = { label: await stamp.innerText(), exact: await stamp.getAttribute('title') };

    /*
     * Перезагрузки не будет: её признак — новая отрисовка документа. Сторожим это
     * меткой на самом документе: перезагрузка её потеряет.
     */
    await page.evaluate(() => {
      document.documentElement.dataset.beforeSwitch = 'yes';
    });

    await switchTo(page, 'en', 'Русский');

    await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
    await expect(page).toHaveTitle(NAME.ru);
    await expect(page.locator('html')).toHaveAttribute('data-before-switch', 'yes');

    // Подпись времени сменилась вместе со всем остальным: компонент подписан на язык.
    await expect(stamp).not.toHaveText(english.label);
    const russian = { label: await stamp.innerText(), exact: await stamp.getAttribute('title') };
    expect(russian.exact).not.toBe(english.exact);
    expect(russian.exact).toMatch(/[А-Яа-яЁё]/);

    /*
     * Пояс от языка не зависит: слова разошлись, а числа — день, год, минута и секунда —
     * обязаны совпасть знак в знак. Это и есть «человек с английским интерфейсом сидит
     * в своём поясе, а не в лондонском».
     *
     * Час сравнивается отдельно и по модулю 12: английская подсказка двенадцатичасовая,
     * русская — двадцатичетырёхчасовая, и один и тот же миг читается как `2:38:49 PM`
     * и `14:38:49`. Прежняя проверка равняла все числа подряд и потому падала каждый
     * день после полудня — с полуночи до полудня числа совпадали, и никто этого
     * не замечал (найдено прогоном UI-75 в 14:38 по Нью-Йорку).
     */
    const numbers = (value: string | null) => (value ?? '').match(/\d+/g)?.map(Number) ?? [];
    const [ruDay, ruYear, ruHour, ruMinute, ruSecond] = numbers(russian.exact);
    const [enDay, enYear, enHour, enMinute, enSecond] = numbers(english.exact);

    expect([ruDay, ruYear, ruMinute, ruSecond]).toEqual([enDay, enYear, enMinute, enSecond]);
    expect(ruHour % 12).toBe(enHour % 12);

    // И обратно: язык возвращается тем же переключателем, а не перезагрузкой.
    await switchTo(page, 'ru', 'English');
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page).toHaveTitle(NAME.en);
    await expect(stamp).toHaveText(english.label);
  });
});
