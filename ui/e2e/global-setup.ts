import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { compose, SECRETS_DIR, TASK_TOKEN_FILE, TOKEN_FILE } from './contour';

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

  compose(['up', '-d', '--wait', '--build', 'ui'], {
    TRACKER_UI_TOKEN: readFileSync(TOKEN_FILE, 'utf8').trim(),
  });
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
