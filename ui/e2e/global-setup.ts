import { compose, writeE2eToken } from './contour';

/**
 * Поднимает контур и добывает токен так, как это делает человек по README бэкенда:
 * миграции, `init`, демо-данные.
 *
 * Токен выпускается отдельной командой, а не берётся из вывода `init`: тот молчит
 * на уже настроенной установке, и повторный прогон остался бы без токена. Набор
 * `task` — ровно тот, которого хватает интерфейсу человека.
 *
 * `--build` обязателен: без него compose поднимает уже собранный `tracker-ui:latest`,
 * и прогон молча проверяет код прошлой задачи. Ошибка при этом выглядит как поломка
 * нового экрана, а не как устаревший образ.
 */
async function globalSetup(): Promise<void> {
  compose(['up', '-d', '--wait', '--build', 'ui']);
  compose(['run', '--rm', 'migrate']);
  compose(['run', '--rm', 'init']);
  compose(['run', '--rm', 'demo']);

  const issued = compose([
    'run',
    '--rm',
    'api',
    'python',
    '-m',
    'app.cli',
    'issue-token',
    '--participant',
    'owner',
    '--scope',
    'task',
  ]);

  const token = /trk_[A-Za-z0-9_-]+/.exec(issued)?.[0];
  if (token === undefined) {
    throw new Error(`Не удалось выпустить токен для сквозных тестов. Вывод команды:\n${issued}`);
  }

  writeE2eToken(token);
}

export default globalSetup;
