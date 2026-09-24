import { expect, test } from '@playwright/test';
import { readE2eToken, side, silenceJournal } from './contour';

/*
 * Проект — место в боковой панели, а не условие отбора (UI-38 в терминах v0.4.0,
 * UI-172). В демо-контуре проект один, поэтому переход «из проекта в проект» здесь
 * проверяется на двух своих: сценарий заводит `UI` и `TRK` и потому пишущий — идёт
 * в проекте «запись», после читающих, которые считают проекты панели.
 */
test('переход из проекта в проект сохраняет вид и отбор, смена вида — проект и отбор', async ({
  page,
  request,
}) => {
  const token = readE2eToken();
  for (const [key, title] of [
    ['UI', 'Интерфейс'],
    ['TRK', 'Бэкенд'],
  ]) {
    const created = await request.post('/api/v1/projects', {
      headers: { Authorization: `Bearer ${token}` },
      data: { key, title },
    });
    // Повторный прогон на той же базе застаёт проекты уже заведёнными.
    expect([201, 409]).toContain(created.status());
  }

  await silenceJournal(page);
  await page.goto('/tasks?project=UI&view=board&status=open');
  await expect(page.getByRole('region', { name: 'open' })).toBeVisible();
  await expect(side(page).getByRole('link', { name: /^UI/ })).toHaveAttribute(
    'aria-current',
    'page',
  );

  // Переход через панель меняет только проект: вид и условие отбора едут с ним.
  await side(page).getByRole('link', { name: /^TRK/ }).click();
  await expect(page).toHaveURL(/[?&]project=TRK(&|$)/);
  await expect(page).toHaveURL(/[?&]view=board(&|$)/);
  await expect(page).toHaveURL(/[?&]status=open(&|$)/);
  await expect(side(page).getByRole('link', { name: /^TRK/ })).toHaveAttribute(
    'aria-current',
    'page',
  );
  await expect(page.getByLabel('Где я')).toContainText('TRK');

  // Смена вида меняет только вид: проект и отбор остаются.
  await page.getByRole('link', { name: 'Таблица' }).click();
  await expect(page).not.toHaveURL(/view=board/);
  await expect(page).toHaveURL(/[?&]project=TRK(&|$)/);
  await expect(page).toHaveURL(/[?&]status=open(&|$)/);
  await expect(side(page).getByRole('link', { name: /^TRK/ })).toHaveAttribute(
    'aria-current',
    'page',
  );
});
