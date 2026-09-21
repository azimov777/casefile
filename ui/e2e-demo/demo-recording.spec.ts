import { expect, test, type Page } from '@playwright/test';

/**
 * Записывает `docs/assets/demo-light.gif`/`demo-dark.gif` (TRK-82, тема — прогон
 * дважды с разным `DEMO_COLOR_SCHEME`): человек смотрит доску, агент заводит
 * задачу и ведёт её через MCP/REST, доска обновляется сама.
 *
 * Не часть `pnpm e2e` — своя папка (`testDir` в `playwright.demo.config.ts`), свой
 * конфиг без глобального подъёма контура. Бэкенд, участник `claude` и девять фоновых
 * задач (`APP-1`…`APP-9`: 3 backlog, 2 open, 2 in_progress, 1 waiting, 1 done —
 * столько, чтобы колонки не пустовали под записью, TRK-82) подготовлены заранее
 * отдельным контуром и скриптом `seed-background.py` — команды целиком в
 * `e2e-demo/README.md`. Здесь только то, что должно попасть в кадр: агент своим
 * токеном (`DEMO_AGENT_TOKEN`) заводит ОДНУ новую задачу вживую, а страница в это
 * время смотрит на доску тем же способом, каким её видит человек. Пауза после
 * каждого перехода статуса длиннее паузы после записи дела намеренно: среди
 * нескольких карточек колонки движение новой задачи должно быть заметно, а не
 * промелькнуть.
 *
 * Видео пишет `playwright.demo.config.ts` (`use.video: 'on'`) — по одному файлу на
 * прогон, без явного `recordVideo` в коде. Пауз `waitForTimeout` в сценарии столько,
 * сколько нужно, чтобы каждый кадр был читаем на GIF 10–12 fps, а не потому что чего-то
 * дожидаемся технически.
 */

const API = process.env.DEMO_API_URL ?? 'http://localhost:8020';
const TOKEN = process.env.DEMO_AGENT_TOKEN;

function column(page: Page, status: string) {
  return page.getByRole('region', { name: status });
}

async function agentCall(method: string, path: string, body?: unknown): Promise<unknown> {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${method} ${path} -> ${response.status}: ${await response.text()}`);
  }
  return response.status === 204 ? null : response.json();
}

test('agent works a task while the board watches', async ({ page }) => {
  if (!TOKEN) throw new Error('DEMO_AGENT_TOKEN is not set — see e2e-demo/README.md');
  test.setTimeout(90_000);

  // Сцена 1: доска уже живёт своей жизнью — фоновые задачи заведены заранее.
  await page.goto('/tasks?queue=APP&view=board');
  await expect(column(page, 'backlog').getByRole('article').first()).toBeVisible();
  await page.waitForTimeout(2_500);

  // Сцена 2: агент заводит новую задачу — карточка появляется сама, без перезагрузки.
  const created = (await agentCall('POST', '/api/v1/tasks', {
    queue: 'APP',
    title: 'Duplicate webhook events double-charge a retried payment',
    description:
      'Stripe redelivers a webhook after a slow 200 response, and the handler charges the order a second time.',
    goal: 'A redelivered webhook never charges the same order twice',
    context:
      "The handler is idempotent on nothing yet; Stripe's own `event.id` is on every payload",
    constraints: 'No schema change to the payments table today',
    output: "Webhook handler dedupes by Stripe's `event.id` before charging",
    checks: [
      'A redelivered event with the same event id is a no-op',
      'A genuinely new event still charges once',
    ],
    priority: 'critical',
    assignee: 'claude',
  })) as { data: { key: string } };
  const key = created.data.key;

  const card = (status: string) =>
    column(page, status).getByRole('article').filter({ hasText: key });
  await expect(card('backlog')).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(2_000);

  // Сцена 3: агент двигает задачу по статусам — доска повторяет движение сама.
  // Пауза дольше, чем в первой версии записи (TRK-82): колонки теперь не пустуют,
  // и карточке нужно время остаться на виду среди соседей, а не потеряться.
  await agentCall('POST', `/api/v1/tasks/${key}/transition`, { to: 'open' });
  await expect(card('open')).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(2_200);

  await agentCall('POST', `/api/v1/tasks/${key}/transition`, { to: 'in_progress' });
  await expect(card('in_progress')).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(2_200);

  // Сцена 4: агент подшивает записи в дело, пока человек смотрит доску.
  await agentCall('POST', `/api/v1/tasks/${key}/entries`, {
    type: 'finding',
    title: 'The handler has no idempotency key',
    body: "Only Stripe's own delivery guarantees stopped double-charges before — the handler itself never checked.",
  });
  await page.waitForTimeout(700);

  await agentCall('POST', `/api/v1/tasks/${key}/entries`, {
    type: 'decision',
    title: "Dedupe by Stripe's event id before charging",
    body: 'Store the event id in a small dedupe table, checked before the charge, not after.',
  });
  await page.waitForTimeout(1_200);

  // Сцена 5: открыть карточку задачи — видно, что записи оставил агент, а не человек.
  await card('in_progress').getByRole('link').click();
  await expect(page).toHaveURL(new RegExp(`/tasks/${key}$`));
  await expect(page.getByRole('heading', { level: 1 })).toContainText(key);
  await expect(page.getByText('claude').first()).toBeVisible();
  await page.waitForTimeout(3_500);
});
