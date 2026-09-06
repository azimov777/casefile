import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { setToken } from '@/shared/api';

beforeEach(() => {
  // Список задач под шапкой ходит за своей страницей: без обработчика подмена
  // ругалась бы на неперехваченный запрос.
  server.use(http.get(`${API}/api/v1/tasks`, () => collection([])));
  setToken('trk_test');
});

/** Отказывает столько раз, сколько сказано, потом отвечает как обычно. */
function flakyBootstrap(failures: number) {
  let left = failures;
  return http.get(`${API}/api/v1/bootstrap`, () => {
    if (left > 0) {
      left -= 1;
      return failure('database_unavailable', 503, 'Database is not available');
    }
    return data(bootstrap());
  });
}

describe('шапка', () => {
  it('на отказе показывает текст по коду и наполняется по кнопке «Повторить»', async () => {
    server.use(flakyBootstrap(1));
    renderApp('/tasks');

    expect(await screen.findByRole('alert')).toHaveTextContent('База данных недоступна.');
    expect(screen.queryByText('owner')).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: 'Повторить' }));

    // Повтор — это `refetch`, а не перезагрузка: страница под шапкой остаётся той же.
    expect(await screen.findByText('owner')).toBeInTheDocument();
    expect(screen.getByText('Открытых вопросов: 2')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Повторить' })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Задачи' })).toBeInTheDocument();
  });

  it('счётчик вопросов ведёт во входящую и называет себя по-разному при нуле и не нуле', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
    renderApp('/tasks');

    // Счётчик был единственным местом, где человек узнавал о вопросах, и никуда
    // не вёл: увидеть, что тебя спрашивают, и попасть к вопросу — разные усилия.
    const waiting = await screen.findByRole('link', { name: 'Открытых вопросов: 2' });
    expect(waiting).toHaveAttribute('href', '/questions');
  });

  it('при нуле вопросов счётчик называется иначе и не требует внимания', async () => {
    server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap({ open_questions: 0 }))));
    renderApp('/tasks');

    const quiet = await screen.findByRole('link', { name: 'Открытых вопросов нет' });
    expect(quiet).toHaveAttribute('href', '/questions');
    expect(screen.queryByRole('link', { name: /Открытых вопросов: / })).not.toBeInTheDocument();
  });

  it('неизвестный код показывает фразу бэкенда и сам код', async () => {
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () =>
        failure('brand_new_code', 500, 'Something odd happened'),
      ),
    );
    renderApp('/tasks');

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Something odd happened (brand_new_code)',
    );
  });
});
