import { HttpResponse, http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { setToken } from '@/shared/api';

const VALID = 'trk_valid';

/** Токен проверяется настоящим запросом, поэтому подмена смотрит на заголовок. */
function bootstrapByToken(payload = bootstrap()) {
  return http.get(`${API}/api/v1/bootstrap`, ({ request }) => {
    if (request.headers.get('Authorization') !== `Bearer ${VALID}`) {
      return failure('unauthorized', 401, 'Authentication required');
    }
    return data(payload);
  });
}

// Удачный вход уводит на список задач, и тот сразу идёт за своей страницей.
// Без этого обработчика подмена ругалась бы на неперехваченный запрос, а экран,
// на котором проверяют шапку, стоял бы в отказе.
beforeEach(() => {
  server.use(http.get(`${API}/api/v1/tasks`, () => collection([])));
});

async function submitToken(token: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Токен участника'), token);
  await user.click(screen.getByRole('button', { name: 'Войти' }));
}

describe('экран входа', () => {
  /**
   * Токены, из которых браузер не соберёт заголовок. Собираются кодами символов,
   * а не буквами: управляющий символ иначе не написать в исходнике, а кириллицу
   * в строке легко принять за латиницу, набранную по ошибке.
   */
  const CYRILLIC = `trk_${String.fromCharCode(1087, 1088, 1080)}`;
  const CONTROL = `trk_a${String.fromCharCode(1)}b`;

  it('токен с кириллицей объясняется видом токена, а не недоступным сервером', async () => {
    let asked = 0;
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => {
        asked += 1;
        return data(bootstrap());
      }),
    );
    renderApp('/login');

    await submitToken(CYRILLIC);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Токен такого вида отправить нельзя/,
    );
    expect(screen.queryByText(/Сервер недоступен/)).not.toBeInTheDocument();
    // Запроса не было вовсе: заголовка из такого значения не выходит.
    expect(asked).toBe(0);
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('токен с управляющим символом объясняется так же', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    await submitToken(CONTROL);

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Токен такого вида отправить нельзя/,
    );
  });

  it('токен без префикса trk_ уходит на сервер: формат интерфейс не угадывает', async () => {
    let seen: string | null = null;
    server.use(
      http.get(`${API}/api/v1/bootstrap`, ({ request }) => {
        seen = request.headers.get('Authorization');
        return failure('unauthorized', 401, 'Authentication required');
      }),
    );
    renderApp('/login');

    // Значение из годных для заголовка символов, но не похожее на токен: годен ли он
    // по существу, решает сервер, а не мы.
    await submitToken('not-a-tracker-token');

    expect(await screen.findByRole('alert')).toHaveTextContent('Токен неизвестен или отозван.');
    expect(seen).toBe('Bearer not-a-tracker-token');
  });

  it('при упавшей сети сообщение про недоступный сервер осталось', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => HttpResponse.error()));
    renderApp('/login');

    await submitToken(VALID);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Сервер недоступен/);
  });

  it('испорченный токен в хранилище уводит на вход, а не на отказ сети', async () => {
    // Человек открывает список напрямую, а в хранилище лежит испорченное значение:
    // экрана входа на этом пути нет, и ошибиться причиной особенно легко.
    // Через `setToken`, а не мимо него: модуль держит значение и в памяти, и запись
    // прямо в хранилище прошла бы мимо этого снимка.
    setToken(CYRILLIC);
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));

    renderApp('/tasks');

    expect(await screen.findByLabelText('Токен участника')).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('пускает с верным токеном и показывает участника и счётчик вопросов', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    await submitToken(VALID);

    expect(await screen.findByText('owner')).toBeInTheDocument();
    expect(screen.getByText('Открытых вопросов: 2')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Задачи' })).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBe(VALID);
  });

  it('на неверный токен показывает русский текст и не сохраняет его', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    await submitToken('trk_wrong');

    expect(await screen.findByRole('alert')).toHaveTextContent('Токен неизвестен или отозван.');
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
    expect(screen.getByLabelText('Токен участника')).toBeInTheDocument();
  });

  it('не пускает общий агентский токен: за ним нет участника', async () => {
    server.use(bootstrapByToken(bootstrap({ participant: null, open_questions: 0 })));
    renderApp('/login');

    await submitToken(VALID);

    expect(await screen.findByRole('alert')).toHaveTextContent('общий агентский токен');
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });

  it('сообщает, что сервер недоступен, а не молчит', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => Response.error()));
    renderApp('/login');

    await submitToken(VALID);

    expect(await screen.findByRole('alert')).toHaveTextContent('Сервер недоступен');
  });

  it('пустое поле не отправляется', () => {
    renderApp('/login');
    expect(screen.getByRole('button', { name: 'Войти' })).toBeDisabled();
  });

  it('вошедшего на экран входа не пускает', async () => {
    server.use(bootstrapByToken());
    renderApp('/login');

    await submitToken(VALID);
    await waitFor(() => expect(screen.queryByLabelText('Токен участника')).not.toBeInTheDocument());
  });
});
