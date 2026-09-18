import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import {
  compose,
  LOGIN_PORT,
  LOGIN_URL,
  SECRETS_DIR,
  TASK_TOKEN_FILE,
  TOKEN_FILE,
} from './contour';

/**
 * Поднимает установку в том же порядке, что и продакшен-контур (`../docker-compose.prod.yml`):
 * бэкенд, миграции, владелец, ключ интерфейса — и только потом интерфейс, которому ключ
 * приезжает переменной, а не томом: контуру нужен ещё и сам ключ, чтобы им пользовались
 * тесты. Дальше сценарии открывают адрес и видят задачи, ничего не вводя, — ровно то,
 * что делает человек. Иначе продуктовый путь не проверял бы никто.
 *
 * Ключ установки из вывода команд не разбирается: результат `local-token` — файл, а
 * секрет не печатается никогда (`UI-75#6`). Прежний способ — регулярка по выводу
 * `issue-token` — снят вместе с ним.
 *
 * Порядок тот же, что у первого запуска бэкенда: `init` считает установку настроенной по
 * наличию **любого** токена и после ключа интерфейса промолчал бы. Права владельца это не
 * отнимает — ключ интерфейса сам набора `main`, — но своего токена `init` не выпустил бы.
 * Демо-данные идут последними — им нужна настроенная установка.
 *
 * `--build` обязателен: без него compose поднимает уже собранный образ, и прогон молча
 * проверяет код прошлой задачи. Ошибка при этом выглядит как поломка нового экрана,
 * а не как устаревший образ.
 */
async function globalSetup(): Promise<void> {
  mkdirSync(SECRETS_DIR, { recursive: true });

  compose(['up', '-d', '--wait', '--build', 'api']);
  compose(['run', '--rm', 'migrate']);
  compose(['run', '--rm', 'init']);
  compose(['run', '--rm', 'local-token']);
  compose(['run', '--rm', 'demo']);
  issueTaskToken();

  const token = readFileSync(TOKEN_FILE, 'utf8').trim();
  compose(['up', '-d', '--wait', '--build', 'ui'], { TRACKER_UI_TOKEN: token });
  await startLockedInterface(token);
}

/**
 * Второй экземпляр интерфейса — установка, закрытая паролем владельца (`TRK-90`).
 *
 * Одноразовый контейнер той же службы `ui`, а не отдельная служба: так он берёт тот же
 * образ, что собран выше, — с тегом, который соседнее дерево подменило своим дополнением
 * к `ui`. Режим задаётся окружением контейнера (`TRACKER_UI_LOGIN`), ключ — тот же, что
 * у основного экземпляра. Бэкенд общий: пароль знает API всего контура.
 *
 * `run -d` не ждёт готовности, поэтому ждём сами — первой отданной страницы. Гасит
 * контейнер `global-teardown.ts` (`down --remove-orphans`: одноразовые контейнеры
 * обычный `down` не трогает).
 *
 * `--use-aliases` даёт контейнеру имя службы в сети контура. Без него API не узнал бы в
 * нём свой nginx (`TRACKER_REAL_IP_FROM: ui`) и считал бы попытки входа на адрес
 * контейнера, а не на тот, что nginx прислал в `X-Real-IP`, — не тем путём, что у
 * владельца (`TRK-98`).
 */
async function startLockedInterface(token: string): Promise<void> {
  compose(
    [
      ...['run', '-d', '--rm', '--no-deps', '--use-aliases'],
      ...['-p', `127.0.0.1:${LOGIN_PORT}:80`],
      ...['-e', 'TRACKER_UI_LOGIN=password'],
      'ui',
    ],
    { TRACKER_UI_TOKEN: token },
  );

  const deadline = Date.now() + 60_000;
  for (;;) {
    try {
      if ((await fetch(LOGIN_URL)).ok) return;
    } catch {
      // Порт ещё не открыт: nginx стартует после шагов входа образа.
    }
    if (Date.now() > deadline) throw new Error(`${LOGIN_URL} did not answer within a minute`);
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

/**
 * Ключ набора `task` владельцу — для сценариев входа на `/login` (`readTaskToken`).
 *
 * Набор назван в команде, а не взят у ключа установки: тот задаёт установка, и с TRK-69
 * он станет `main` (`UI-105`). Файлом ключ, в отличие от ключа установки, установка
 * не выдаёт — у `local-token` набор свой, — поэтому здесь единственное место, где
 * секрет берётся из вывода команды: `issue-token` для того и печатает его. Вывод
 * уходит в трубу этого процесса, а не в журнал прогона, и ложится в файл `0600`
 * в `.secrets/`, который уносит `global-teardown.ts`.
 */
function issueTaskToken(): void {
  const printed = compose([
    'run',
    '--rm',
    '--no-deps',
    'api',
    ...['python', '-m', 'app.cli', 'issue-token'],
    ...['--participant', 'owner', '--scope', 'task', '--name', 'e2e-login'],
  ]);
  const secret = /^token:\s+(\S+)\s*$/m.exec(printed)?.[1];
  // Сообщение без вывода команды: в нём секрет.
  if (secret === undefined) throw new Error('issue-token printed no token line');
  writeFileSync(TASK_TOKEN_FILE, secret, { mode: 0o600 });
}

export default globalSetup;
