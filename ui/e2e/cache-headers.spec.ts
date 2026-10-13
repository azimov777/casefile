import { expect, test } from '@playwright/test';

/**
 * Заголовки кэша nginx интерфейса (TRK-700). Без `Cache-Control` на `index.html`
 * браузер сам назначал ответу срок свежести в часы и после обновления установки
 * открывал оболочку старого выпуска. Проверка бьёт по собранному образу настоящего
 * контура: важен ответ самого nginx (`docker/nginx.conf.template`).
 */
test.describe('кэш оболочки и сборки', () => {
  test('корень и путь приложения отдают index.html с no-cache', async ({ request }) => {
    for (const path of ['/', '/tasks/DEMO-1']) {
      const response = await request.get(path);
      expect(response.status(), path).toBe(200);
      expect(response.headers()['cache-control'], path).toBe('no-cache');
    }
  });

  test('файл сборки с хешем в имени — immutable, а несуществующий — 404 без этого', async ({
    request,
  }) => {
    const html = await (await request.get('/')).text();
    const asset = /\/assets\/index-[\w-]+\.js/.exec(html)?.[0];
    expect(asset, 'в разметке есть файл сборки').toBeTruthy();

    const file = await request.get(asset ?? '');
    expect(file.status()).toBe(200);
    expect(file.headers()['cache-control']).toContain('immutable');

    const missing = await request.get('/assets/index-nothere.js');
    expect(missing.status()).toBe(404);
    expect(missing.headers()['cache-control'] ?? '').not.toContain('immutable');
  });

  test('config.json остаётся no-store', async ({ request }) => {
    const response = await request.get('/config.json');
    expect(response.status()).toBe(200);
    expect(response.headers()['cache-control']).toBe('no-store');
  });

  test('повторный переход на тот же адрес доходит до сервера', async ({ page }) => {
    // Играет Chromium: признак «ответ из кэша» отдаёт только его протокол.
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('Network.enable');
    const documents: { fromDiskCache: boolean; status: number; url: string }[] = [];
    cdp.on('Network.responseReceived', (event) => {
      if (event.type === 'Document') {
        documents.push({
          fromDiskCache: event.response.fromDiskCache === true,
          status: event.response.status,
          url: event.response.url,
        });
      }
    });

    const first = await page.goto('/start');
    expect(first?.headers()['cache-control']).toBe('no-cache');
    await page.goto('/start');

    const second = documents.filter((d) => d.url.endsWith('/start')).at(-1);
    expect(second?.fromDiskCache).toBe(false);
    expect([200, 304]).toContain(second?.status);
  });
});
