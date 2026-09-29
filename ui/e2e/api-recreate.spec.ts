import { execFileSync } from 'node:child_process';
import { expect, test } from '@playwright/test';
import { compose } from './contour';

/**
 * Пересозданный `api` не ломает интерфейс (TRK-388). nginx с готовым именем в
 * `proxy_pass` разрешал его один раз при старте и после `docker compose up -d`,
 * давшего `api` новый адрес, отвечал `502`, пока не перезапущен `ui`.
 *
 * Общий `api` контура сценарий не трогает — под ним идёт весь остальной прогон. Вместо
 * него — свой «бэкенд» (nginx с одним файлом `/api/ping`) под сетевым именем
 * `recreate-api` в той же сети и свой экземпляр интерфейса из того же образа, что и `ui`
 * контура, с `TRACKER_API_URL=http://recreate-api:80`. Бэкенд убирается, его адрес
 * занимает чужой контейнер, и новый бэкенд под тем же именем получает другой адрес —
 * ровно то, что делает пересоздание службы, когда её прежний адрес уже занят.
 *
 * Идёт в проекте «запись»: контейнеры и порт у сценария свои, но он гоняет docker, а
 * читающим проектам это без пользы.
 */
const SUFFIX = String(process.pid);
const BACKEND = `e2e-recreate-backend-${SUFFIX}`;
const HOLDER = `e2e-recreate-holder-${SUFFIX}`;
const PROBE = `e2e-recreate-ui-${SUFFIX}`;
const ALIAS = 'recreate-api';
const BACKEND_IMAGE = 'nginx:1.27-alpine';

function docker(args: string[]): string {
  return execFileSync('docker', args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'inherit'],
  }).trim();
}

function inspect(container: string, format: string): string {
  return docker(['inspect', '-f', format, container]);
}

function forget(...names: string[]): void {
  for (const name of names) {
    try {
      execFileSync('docker', ['rm', '-f', name], { stdio: 'ignore' });
    } catch {
      // Контейнера может не быть: уборка не должна падать из-за него.
    }
  }
}

function startBackend(network: string, answer: string): string {
  docker([
    'run',
    '-d',
    '--name',
    BACKEND,
    '--network',
    network,
    '--network-alias',
    ALIAS,
    BACKEND_IMAGE,
  ]);
  docker([
    'exec',
    BACKEND,
    'sh',
    '-c',
    `mkdir -p /usr/share/nginx/html/api && printf %s ${answer} > /usr/share/nginx/html/api/ping`,
  ]);
  return inspect(BACKEND, `{{(index .NetworkSettings.Networks "${network}").IPAddress}}`);
}

async function ping(base: string): Promise<{ status: number; body: string }> {
  const response = await fetch(`${base}/api/ping`);
  return { status: response.status, body: await response.text() };
}

test.describe('интерфейс находит пересозданный api без перезапуска', () => {
  test.afterAll(() => {
    forget(PROBE, BACKEND, HOLDER);
  });

  test('после смены адреса api запрос через nginx отвечает 200 от нового', async () => {
    test.setTimeout(120_000);

    const uiContainer = compose(['ps', '-q', 'ui']).split('\n')[0]?.trim() ?? '';
    expect(uiContainer, 'служба ui контура не запущена').not.toBe('');
    const image = inspect(uiContainer, '{{.Config.Image}}');
    const network = inspect(
      uiContainer,
      '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}',
    );

    forget(PROBE, BACKEND, HOLDER);
    const firstAddress = startBackend(network, 'first');

    docker([
      'run',
      '-d',
      '--name',
      PROBE,
      '--network',
      network,
      '-e',
      `TRACKER_API_URL=http://${ALIAS}:80`,
      // Режим входа: ключа не нужно, а проверка `Host` снята.
      '-e',
      'TRACKER_UI_LOGIN=password',
      '-p',
      '127.0.0.1::80',
      image,
    ]);
    const mapped = docker(['port', PROBE, '80/tcp']).split('\n')[0] ?? '';
    const base = `http://127.0.0.1:${mapped.split(':').pop() ?? ''}`;

    await expect
      .poll(async () => (await ping(base).catch(() => ({ status: 0, body: '' }))).body, {
        timeout: 30_000,
      })
      .toBe('first');

    // Бэкенд уходит, его адрес занимает чужой контейнер, новый бэкенд получает другой.
    forget(BACKEND);
    docker(['run', '-d', '--name', HOLDER, '--network', network, BACKEND_IMAGE, 'sleep', '300']);
    const secondAddress = startBackend(network, 'second');
    expect(secondAddress, 'сценарий не смог сменить адрес бэкенда').not.toBe(firstAddress);

    // `valid=5s` у резолвера: ответ живёт в кэше nginx считанные секунды.
    await expect
      .poll(async () => ping(base), { timeout: 30_000, intervals: [1000] })
      .toEqual({ status: 200, body: 'second' });
  });
});
