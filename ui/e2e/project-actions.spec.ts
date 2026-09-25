import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { fontsReady, readE2eToken, side } from './contour';

/*
 * Действия человека с проектом (UI-175): завести проект из панели, повтор ключа,
 * остаток описания, атрибут без причины, изменение и снятие только с причиной,
 * заметка в дело проекта с подписью человека; `axe` в окнах и возврат фокуса.
 *
 * Сценарий пишущий — заводит проекты, атрибуты и записи — и идёт в проекте «запись».
 * Ключ проекта несёт метку прогона: на той же базе повторный прогон заводит свой, а
 * не натыкается на прежний (удалить проект нельзя — только архивировать, UI-176).
 * Ключом прогона служит ключ установки контура: набор `main`.
 */

const token = readE2eToken();
const RUN = Date.now().toString(36).toUpperCase();
/** Ключ проекта прогона: буква и латиница с цифрами, не длиннее 16 знаков. */
const KEY = `E${RUN}`.slice(0, 16);
const TITLE = `Проект прогона ${RUN}`;

/** Запросы записи к проектам: по ним видно, что ушло на бэкенд, а что нет. */
function projectWrites(page: Page): { method: string; url: string }[] {
  const seen: { method: string; url: string }[] = [];
  page.on('request', (request) => {
    if (request.method() !== 'GET' && request.url().includes('/api/v1/projects')) {
      seen.push({ method: request.method(), url: request.url() });
    }
  });
  return seen;
}

/** Имя участника за ключом контура: им подписаны записи человека. */
async function signature(page: Page): Promise<string> {
  const response = await page.request.get('/api/v1/bootstrap', {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { data: { participant: { name: string } } };
  return body.data.participant.name;
}

test('проект заводится из панели и открывается; повтор ключа объяснён; 321 знак не уходит', async ({
  page,
}) => {
  const writes = projectWrites(page);
  await page.goto('/tasks');

  const create = side(page).getByRole('button', { name: 'Новый проект' });
  await create.click();
  const dialog = page.getByRole('dialog', { name: 'Новый проект' });
  await dialog.getByLabel('Ключ').fill(KEY.toLowerCase());
  await dialog.getByLabel('Название').fill(TITLE);

  // Описание в 321 знак: лишний знак назван, отправка запрещена, запроса нет.
  const description = dialog.getByLabel('Описание');
  await description.fill('д'.repeat(321));
  await expect(dialog.getByText('Лишних знаков: 1.', { exact: false })).toBeVisible();
  await expect(description).toHaveAttribute('aria-invalid', 'true');
  const submit = dialog.getByRole('button', { name: 'Завести проект' });
  await expect(submit).toBeDisabled();
  await submit.click({ force: true });
  expect(writes).toEqual([]);

  // Ровно 320 — остаток ноль, и проект заводится.
  await description.fill(`Короткое «что это» прогона ${RUN}.`);
  await expect(dialog.getByText(/Осталось знаков: \d+ из 320/)).toBeVisible();
  await submit.click();

  await expect(page).toHaveURL(new RegExp(`/projects/${KEY}$`));
  await expect(page.getByRole('heading', { level: 1 })).toContainText(TITLE);
  await expect(side(page).getByRole('link', { name: new RegExp(`^${KEY}`) })).toBeVisible();
  expect(writes.filter((write) => write.method === 'POST')).toHaveLength(1);

  // Тот же ключ второй раз — понятное сообщение, окно остаётся открытым.
  await create.click();
  await dialog.getByLabel('Ключ').fill(KEY);
  await dialog.getByLabel('Название').fill('Второй с тем же ключом');
  await dialog.getByRole('button', { name: 'Завести проект' }).click();
  await expect(dialog.getByText('Ключ проекта занят.')).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/projects/${KEY}$`));

  // Отмена закрывает окно и возвращает фокус на кнопку, которая его открыла.
  await dialog.getByRole('button', { name: 'Отмена' }).click();
  await expect(dialog).toBeHidden();
  await expect(create).toBeFocused();
});

test('атрибут ставится без причины, меняется и снимается только с причиной', async ({ page }) => {
  await ensureProject(page);
  const writes = projectWrites(page);
  await page.goto(`/projects/${KEY}`);
  const attributes = page.getByRole('region', { name: 'Атрибуты' });
  const name = `repo-${RUN.toLowerCase()}`;

  // Заведение — без поля причины.
  await attributes.getByRole('button', { name: 'Добавить атрибут' }).click();
  const add = page.getByRole('dialog', { name: 'Новый атрибут' });
  await expect(add.getByLabel('Причина')).toHaveCount(0);
  await add.getByLabel('Имя').fill(name);
  await add.getByLabel('Значение').fill('github.com/old/casefile');
  await add.getByRole('button', { name: 'Добавить', exact: true }).click();
  await expect(add).toBeHidden();
  await expect(attributes.getByText('github.com/old/casefile')).toBeVisible();

  // Изменение без причины не уходит.
  const change = attributes.getByRole('button', { name: `Изменить атрибут ${name}` });
  await change.click();
  const edit = page.getByRole('dialog', { name: `Атрибут ${name}` });
  await edit.getByLabel('Значение').fill('github.com/azimov777/casefile');
  const before = writes.length;
  await edit.getByRole('button', { name: 'Сохранить' }).click();
  await expect(edit.getByRole('alert')).toContainText('Без причины изменение не отправится');
  expect(writes.length).toBe(before);
  // Поле причины помечено отказом и видом, а не только атрибутом: рамка — цвет отказа,
  // не цвет соседнего поля в покое (ждём конца перехода цвета, `transition-colors`).
  const reasonField = edit.getByLabel('Причина');
  await expect(reasonField).toHaveAttribute('aria-invalid', 'true');
  const danger = await edit.getByRole('alert').evaluate((node) => getComputedStyle(node).color);
  await expect(reasonField).toHaveCSS('border-top-color', danger);

  // С причиной — уходит и встаёт в историю атрибута и в дело.
  await edit.getByLabel('Причина').fill(`Переезд в организацию ${RUN}`);
  await edit.getByRole('button', { name: 'Сохранить' }).click();
  await expect(edit).toBeHidden();
  await expect(change).toBeFocused();
  await expect(attributes.getByText('github.com/azimov777/casefile')).toBeVisible();

  // Имя атрибута — кнопка раскрытия; её имя несёт знак `▸` псевдоэлементом, а
  // «Изменить атрибут …» содержит то же имя, поэтому она ищется по точному имени со
  // знаком (так её называет и диктор).
  const row = attributes.locator(`li[data-attribute="${name}"]`);
  await row.getByRole('button', { name: `▸ ${name}`, exact: true }).click();
  const history = page.getByRole('region', { name: `История атрибута ${name}` });
  const changed = history.locator('article[data-type="attribute_changed"]');
  await expect(changed.locator('[data-side="was"]')).toContainText('github.com/old/casefile');
  await expect(changed.locator('[data-side="now"]')).toContainText('github.com/azimov777/casefile');
  await expect(changed).toContainText(`Переезд в организацию ${RUN}`);
  const index = page.getByRole('region', { name: 'Дело проекта' }).getByRole('table');
  await expect(index.getByRole('row').filter({ hasText: 'attribute_changed' })).toHaveCount(1);

  // Снятие — окно-вопрос, без причины не уходит.
  await attributes.getByRole('button', { name: `Снять атрибут ${name}` }).click();
  const remove = page.getByRole('alertdialog', { name: `Снять атрибут ${name}?` });
  const beforeRemove = writes.length;
  await remove.getByRole('button', { name: 'Снять атрибут' }).click();
  await expect(remove.getByRole('alert')).toContainText('Без причины атрибут не снимается');
  expect(writes.length).toBe(beforeRemove);
  await remove.getByLabel('Причина').fill(`Больше не верно ${RUN}`);
  await remove.getByRole('button', { name: 'Снять атрибут' }).click();
  await expect(remove).toBeHidden();
  await expect(row).toHaveCount(0);
  await expect(index.getByRole('row').filter({ hasText: 'attribute_removed' })).toHaveCount(1);
});

test('заметка из формы встаёт в дело проекта с подписью человека', async ({ page }) => {
  await ensureProject(page);
  const me = await signature(page);
  const title = `Релизы по пятницам, прогон ${RUN}`;
  await page.goto(`/projects/${KEY}`);

  const caseBlock = page.getByRole('region', { name: 'Дело проекта' });
  const open = caseBlock.getByRole('button', { name: 'Написать заметку' });
  await open.click();
  const form = page.getByRole('form', { name: `Заметка в дело ${KEY}` });
  await expect(form.getByLabel('Заметка')).toBeFocused();
  await form.getByLabel('Заметка').fill(`${title}\nТак договорились с агентами.`);
  await form.getByRole('button', { name: 'Подшить заметку' }).click();

  const receipt = page.getByRole('region', { name: `Заметка в дело ${KEY} подшита` });
  await expect(receipt).toBeVisible();

  const row = caseBlock.getByRole('table').getByRole('row').filter({ hasText: title });
  await expect(row).toHaveCount(1);
  await expect(row).toContainText(me);
  await expect(row.locator('[data-mark="kind"]')).toContainText('note');
});

/** Проект прогона: заведён первым сценарием, а при прицельном прогоне — здесь. */
async function ensureProject(page: Page): Promise<void> {
  const response = await page.request.post('/api/v1/projects', {
    headers: { Authorization: `Bearer ${token}` },
    data: { key: KEY, title: TITLE, description: '' },
  });
  expect([201, 409], await response.text()).toContain(response.status());
}

for (const colorScheme of ['light', 'dark'] as const) {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    test(`окна действий с проектом без нарушений axe: ${colorScheme}, ${viewport.width}px`, async ({
      page,
    }) => {
      await ensureProject(page);
      await page.request.put(`/api/v1/projects/${KEY}/attributes/axe`, {
        headers: { Authorization: `Bearer ${token}` },
        data: { value: 'значение для проверки окон' },
      });
      await page.emulateMedia({ colorScheme });
      await page.setViewportSize(viewport);
      await page.goto(`/projects/${KEY}`);
      await expect(page.getByRole('heading', { level: 1 })).toContainText(TITLE);
      await fontsReady(page);

      const attributes = page.getByRole('region', { name: 'Атрибуты' });
      const dialogs: {
        open: () => Promise<unknown>;
        name: string;
        role: 'dialog' | 'alertdialog';
      }[] = [
        {
          open: () => page.getByRole('button', { name: 'Изменить', exact: true }).click(),
          name: `Проект ${KEY}`,
          role: 'dialog',
        },
        {
          open: () => attributes.getByRole('button', { name: 'Добавить атрибут' }).click(),
          name: 'Новый атрибут',
          role: 'dialog',
        },
        {
          open: () => attributes.getByRole('button', { name: 'Изменить атрибут axe' }).click(),
          name: 'Атрибут axe',
          role: 'dialog',
        },
        {
          open: () => attributes.getByRole('button', { name: 'Снять атрибут axe' }).click(),
          name: 'Снять атрибут axe?',
          role: 'alertdialog',
        },
      ];

      for (const { open, name, role } of dialogs) {
        await open();
        const dialog = page.getByRole(role, { name });
        await expect(dialog).toBeVisible();
        const report = await new AxeBuilder({ page }).analyze();
        expect(report.violations, name).toEqual([]);
        // Esc закрывает окно, фокус возвращается на кнопку, которая его открыла.
        await page.keyboard.press('Escape');
        await expect(dialog).toBeHidden();
        await expect(page.locator(':focus')).toHaveAttribute('aria-haspopup', 'dialog');
      }

      // Окно создания — из панели; на телефоне панель сперва выезжает шторкой.
      if (viewport.width < 800) {
        await page.getByRole('button', { name: /Показать разделы/ }).click();
        await page
          .getByRole('dialog', { name: 'Разделы Casefile' })
          .getByRole('button', { name: 'Новый проект' })
          .click();
      } else {
        await side(page).getByRole('button', { name: 'Новый проект' }).click();
      }
      const dialog = page.getByRole('dialog', { name: 'Новый проект' });
      await expect(dialog).toBeVisible();
      await dialog.getByLabel('Описание').fill('д'.repeat(321));
      const report = await new AxeBuilder({ page }).analyze();
      expect(report.violations, 'Новый проект').toEqual([]);

      // Горизонтальной прокрутки нет и с открытым окном.
      const over = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(over).toBeLessThanOrEqual(0);
    });
  }
}
