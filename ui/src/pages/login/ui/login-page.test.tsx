import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';

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
