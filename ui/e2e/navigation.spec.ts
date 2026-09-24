import { expect, test } from '@playwright/test';
import { fontsReady, layoutSettled, silenceJournal } from './contour';

test('возврат в список не теряет отбор, с которым человек ушёл', async ({ page }) => {
  await silenceJournal(page);

  const listed = '/tasks?project=DEMO&status=open';
  await page.goto(listed);
  // Дожидаемся строк, а не считаем сразу: `count()` не ждёт, и до прихода выдачи
  // таблица пуста — счётчик снял бы ноль и сравнивал его сам с собой.
  const rows = page.locator('tbody tr');
  await expect(rows.first()).toBeVisible();
  const before = await rows.count();

  // Список → задача → дело: отбор едет с человеком состоянием перехода.
  await page.locator('tbody tr').first().getByRole('link').click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-\d+$/);
  // Точное имя: «Открыть всё дело лентой» внизу карточки ведёт туда же и попала бы
  // под неточное совпадение.
  await page.getByRole('link', { name: 'Дело', exact: true }).click();
  await expect(page).toHaveURL(/\/case$/);

  // И обратно — одной ссылкой, а не тремя нажатиями «назад».
  await page.getByRole('link', { name: 'К списку с отбором' }).click();
  await expect(page).toHaveURL(new RegExp(`${listed.replace('?', '\\?').replace(/&/g, '&')}$`));
  await expect(rows).toHaveCount(before);
});

test('прямой вход в задачу зовёт ко всем задачам и говорит об этом', async ({ page }) => {
  await silenceJournal(page);

  // Чистый контекст: истории нет, отбору взяться неоткуда — и интерфейс не делает
  // вид, что он есть.
  await page.goto('/tasks/DEMO-3');

  const back = page.getByRole('link', { name: 'Ко всем задачам' });
  await expect(back).toHaveAttribute('href', '/tasks');
  await expect(page.getByRole('link', { name: 'К списку с отбором' })).toHaveCount(0);

  await back.click();
  await expect(page).toHaveURL(/\/tasks$/);
});

test('переключение «Карточка — Дело» видно с любой глубины прокрутки', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1/case');

  const toggle = page.getByRole('link', { name: 'Карточка', exact: true });
  await expect(toggle).toBeInViewport();

  // В конец дела: раньше отсюда наверх вела только кнопка браузера.
  await page.keyboard.press('End');
  await page.mouse.wheel(0, 20_000);
  await expect(toggle).toBeInViewport();

  /*
   * `fontsReady` одного вызова недостаточно: вторая подшрифтовка Fira Code
   * (кириллический диапазон отдельным файлом) грузится лениво и может стартовать
   * уже после того, как `document.fonts.ready` разрешился, — замерено, что запрос
   * приходит прямо во время `click()`. Раскладка от неё шевелится (`scroll y=`
   * прыгало на сотни пикселей несколькими раундами подряд в пределах одного
   * клика, UI-139), и клик, попавший в этот момент, промахивается мимо переехавшей
   * ссылки — адрес остаётся прежним, будто нажатия не было. Ждать поэтому нужно не
   * шрифт (о котором заранее знать нельзя), а сам факт: положение цели перестало
   * меняться (`e2e/contour.ts`, `layoutSettled`).
   */
  await layoutSettled(toggle);

  await toggle.click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-1$/);
});

test('номер записи вне отбора по типу объясняется, а не оставляет пустой экран', async ({
  page,
}) => {
  await silenceJournal(page);

  // Отбор оставляет только сводки, а названа запись `created` — она в отбор не попадает.
  await page.goto('/tasks/DEMO-1/case?type=summary&entry=1');

  await expect(page.getByText(/не попадает в отбор по типу/)).toBeVisible();

  await page.getByRole('button', { name: 'Показать все типы' }).click();
  // Точное совпадение: `DEMO-1#1` иначе находит и `DEMO-1#10`, и остальные.
  await expect(page.getByLabel('DEMO-1#1', { exact: true })).toHaveAttribute('data-highlighted');
});

test('номер записи, которой в деле нет, объясняется по-русски', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1/case?entry=999');

  await expect(page.getByText(/в деле нет/)).toBeVisible();
});

test('смена вида сохраняет отбор в обе стороны и не заводит второго пути', async ({ page }) => {
  await silenceJournal(page);

  const listed = '/tasks?project=DEMO&status=open&status=in_progress&sort=key';
  await page.goto(listed);
  await expect(page.getByRole('table')).toBeVisible();

  // Таблица → доска: раньше отсюда уходили на голое `/tasks?view=board`, и проект
  // с остальными условиями оставались позади молча.
  await page.getByRole('link', { name: 'Доска' }).click();
  await expect(page).toHaveURL(/view=board/);
  await expect(page).toHaveURL(/project=DEMO/);
  await expect(page).toHaveURL(/status=in_progress/);
  await expect(page).toHaveURL(/sort=key/);
  await expect(page.getByRole('region', { name: 'open' })).toBeVisible();

  // И обратно тем же правилом: адрес возвращается к исходному посимвольно.
  await page.getByRole('link', { name: 'Таблица' }).click();
  await expect(page).toHaveURL(new RegExp(`${listed.replace('?', '\\?')}$`));

  // Второй точки переключения вида в интерфейсе нет: в шапке доска не раздел.
  await expect(page.getByRole('link', { name: 'Доска' })).toHaveCount(1);
});

test('возврат с доски в задачу и назад сохраняет и вид, и условия', async ({ page }) => {
  await silenceJournal(page);

  await page.goto('/tasks?project=DEMO&view=board&assignee=demo_agent');
  const card = page.getByRole('article').first();
  await expect(card).toBeVisible();
  await card.getByRole('link').first().click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-\d+$/);

  // Место не врёт: проект задачи прочитан из её ключа и подсвечена в панели —
  // подробнее это проверяет `side.spec.ts`.
  await expect(page.getByLabel('Где я')).toContainText('DEMO');

  await page.getByRole('link', { name: 'К списку с отбором' }).click();
  await expect(page).toHaveURL(/view=board/);
  await expect(page).toHaveURL(/assignee=demo_agent/);
});

test('из входящей ссылка «Все задачи» ведёт ко всем задачам, а не в чужой отбор', async ({
  page,
}) => {
  await silenceJournal(page);
  await page.goto('/questions');

  const section = page.getByRole('link', { name: 'Все задачи' });
  await expect(section).toHaveAttribute('href', '/tasks');
  await section.click();
  await expect(page).toHaveURL(/\/tasks$/);
  await expect(page.getByRole('link', { name: 'Доска' })).toBeVisible();
});

/*
 * Действие и переключатель вида в липкой строке задачи — одной высоты и на одной
 * оси (UI-128): до правки кнопка была 33.6 px, переключатель 28, и строка читалась
 * как «кнопки разных размеров». Обе ширины, потому что на узкой группа переносится.
 */
for (const width of [1440, 390]) {
  test(`действие и переключатель «Карточка — Дело» одной высоты и вровень на ${width}`, async ({
    page,
  }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/tasks/DEMO-1');

    const remark = page.getByRole('button', { name: 'Оставить замечание' });
    const toggle = page.getByRole('navigation', { name: 'Вид задачи' });
    await expect(remark).toBeVisible();
    await fontsReady(page);

    const [a, b] = await Promise.all([remark.boundingBox(), toggle.boundingBox()]);
    expect(a).not.toBeNull();
    expect(b).not.toBeNull();
    if (a === null || b === null) return;
    expect(Math.abs(a.height - b.height)).toBeLessThan(0.5);
    expect(Math.abs(a.y + a.height / 2 - (b.y + b.height / 2))).toBeLessThan(0.5);
  });
}

/*
 * Переключатель «Карточка / Дело» стоит на одних координатах на обеих страницах (UI-144).
 * Раньше он жался к правому краю строки, а правый край у карточки (100rem, с кнопкой
 * замечания) и у дела (64rem, без неё) разный: на 1440 он переезжал с x 1291 на 1115,
 * на 390 — со второй строки на первую, и второй клик промахивался. Замер — до пикселя
 * и по обеим ссылкам, а не только по дорожке: жирный текущий сегмент шире обычного, и
 * без резерва под жирное «Дело» ездило бы на доли пикселя внутри неподвижной дорожки.
 * Переход — кликом по самому переключателю, как у человека, туда и обратно.
 */
for (const width of [1440, 390]) {
  test(`переключатель «Карточка — Дело» не двигается при переходе на ${width}`, async ({
    page,
  }) => {
    await silenceJournal(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/tasks/DEMO-1');

    const toggle = page.getByRole('navigation', { name: 'Вид задачи' });
    const card = toggle.getByRole('link', { name: 'Карточка', exact: true });
    const caseLink = toggle.getByRole('link', { name: 'Дело', exact: true });
    // Карточка догружает шапку и блоки; мерить до них — мерить не ту страницу.
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await fontsReady(page);

    const measure = async () => {
      await layoutSettled(toggle);
      return Promise.all([toggle.boundingBox(), card.boundingBox(), caseLink.boundingBox()]);
    };

    const onCard = await measure();
    await caseLink.click();
    await expect(page).toHaveURL(/\/tasks\/DEMO-1\/case$/);
    await expect(caseLink).toHaveAttribute('aria-current', 'page');
    await fontsReady(page);
    const onCase = await measure();

    await card.click();
    await expect(page).toHaveURL(/\/tasks\/DEMO-1$/);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await fontsReady(page);
    const backOnCard = await measure();

    for (const box of onCard) expect(box).not.toBeNull();
    expect(onCase).toEqual(onCard);
    expect(backOnCard).toEqual(onCard);
  });
}

test('«Карточка → Дело → назад» браузера возвращает карточку и её подсветку', async ({ page }) => {
  await silenceJournal(page);
  await page.goto('/tasks/DEMO-1');

  const toggle = page.getByRole('navigation', { name: 'Вид задачи' });
  await toggle.getByRole('link', { name: 'Дело', exact: true }).click();
  await expect(page).toHaveURL(/\/tasks\/DEMO-1\/case$/);
  await expect(toggle.getByRole('link', { name: 'Дело', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );

  await page.goBack();
  await expect(page).toHaveURL(/\/tasks\/DEMO-1$/);
  await expect(toggle.getByRole('link', { name: 'Карточка', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );

  await page.goForward();
  await expect(page).toHaveURL(/\/tasks\/DEMO-1\/case$/);
});
