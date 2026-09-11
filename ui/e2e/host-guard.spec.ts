import { expect, test } from '@playwright/test';
import { readE2eToken } from './contour';

/**
 * Защита от DNS rebinding (UI-107). Единственное, что отличает вкладку человека от
 * вкладки чужого домена, перепривязавшего DNS на этот же адрес, — заголовок `Host`:
 * порт опубликован лишь на петле, но соединение чужая вкладка открывает так же
 * свободно, как своя. Раньше `server_name _;` отвечал любому `Host`, и `/config.json`
 * читался с чужого источника как со своего.
 *
 * Проверка бьёт по уже собранному образу настоящего контура, а не подменяет ответ:
 * важно поведение самого nginx (`docker/nginx.conf.template`), а его даёт только
 * запрос с настоящим чужим заголовком. `request`, а не `page.request` через браузер:
 * тот же клиент на Node, которому, в отличие от `fetch` в браузере, заголовок `Host`
 * не запрещён, — проверено отдельно, что заголовок в него действительно доезжает
 * нетронутым (иначе тест впустую бил бы по своему же адресу).
 */
const token = readE2eToken();

function portOf(baseURL: string | undefined): string {
  return new URL(baseURL ?? '').port;
}

test.describe('nginx интерфейса отвечает только адресам петли', () => {
  test('чужой Host не отдаёт /config.json', async ({ request, baseURL }) => {
    const port = portOf(baseURL);
    const response = await request.get(`${baseURL}/config.json`, {
      headers: { Host: `evil.example:${port}` },
    });

    expect(response.status()).not.toBe(200);
    expect(await response.text()).not.toContain('"token"');
  });

  test('чужой Host не проксирует /api/v1/bootstrap', async ({ request, baseURL }) => {
    const port = portOf(baseURL);
    const response = await request.get(`${baseURL}/api/v1/bootstrap`, {
      headers: { Host: `evil.example:${port}`, Authorization: `Bearer ${token}` },
    });

    // Отказ nginx, а не ответ бэкенда: запрос не должен быть проксирован дальше.
    expect(response.status()).not.toBe(200);
    expect(await response.text()).not.toContain('"token"');
  });

  // Свои адреса петли — ровно то, чем установку и открывает человек (`docker-compose.yml`
  // публикует только `127.0.0.1`, но `Host` браузер посылает тем именем, которым набрал
  // адрес; `[::1]` в заголовке идёт в скобках — nginx обязан узнать его в этом виде).
  for (const host of ['localhost', '127.0.0.1', '[::1]']) {
    test(`свой Host ${host} отвечает как прежде`, async ({ request, baseURL }) => {
      const port = portOf(baseURL);
      const header = `${host}:${port}`;

      const config = await request.get(`${baseURL}/config.json`, {
        headers: { Host: header },
      });
      expect(config.status()).toBe(200);
      expect(((await config.json()) as { token?: string }).token).toBe(token);

      const bootstrap = await request.get(`${baseURL}/api/v1/bootstrap`, {
        headers: { Host: header, Authorization: `Bearer ${token}` },
      });
      expect(bootstrap.status()).toBe(200);
    });
  }
});
