import { HttpResponse, http } from 'msw';
import { screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { API, CONFIG, bootstrap, data } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { loadInstallToken, setToken } from '@/shared/api';

/**
 * Страница, падающая при отрисовке. Подменяется целый модуль страницы, а не заводится
 * особый маршрут: так падает настоящая ветка маршрутов внутри настоящей оболочки —
 * ровно то место, где в браузере получался белый экран.
 */
vi.mock('@/pages/tasks', () => ({
  TasksPage: () => {
    throw new Error('boom: cannot read properties of undefined');
  },
}));

/** React печатает своё сообщение о пойманной ошибке; в прогоне это шум, а не сигнал. */
let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
  setToken('trk_test');
});

afterEach(() => {
  consoleError.mockRestore();
});

describe('граница ошибок', () => {
  it('на падении страницы объясняет случившееся и оставляет оболочку живой', async () => {
    renderApp('/tasks');

    expect(await screen.findByRole('heading', { name: say.ui('app.broken.title') }));
    expect(screen.getByRole('button', { name: say.ui('app.broken.reload') })).toBeInTheDocument();

    // Шапка жива: человек уходит со сломанной страницы ссылкой, а не перезагрузкой.
    expect(screen.getByRole('link', { name: say.ui('app.allTasks') })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: say.ui('app.signOut') })).toBeInTheDocument();
  });

  it('при ключе от установки выхода нет и здесь: он один на оба экрана', async () => {
    // Вторая кнопка выхода в этой ветке — то, о чём легко забыть. Её нет: сломанную
    // страницу подменяет собой внутренняя граница, а оболочка вокруг остаётся та же
    // самая, и кнопка в ней ровно одна.
    setToken('trk_test');
    server.use(http.get(CONFIG, () => HttpResponse.json({ token: 'trk_from_the_installation' })));
    await loadInstallToken();
    renderApp('/tasks');

    await screen.findByRole('heading', { name: say.ui('app.broken.title') });

    expect(screen.getByRole('link', { name: say.ui('app.allTasks') })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: say.ui('app.signOut') })).not.toBeInTheDocument();
  });

  it('технический текст исключения уходит в консоль, а не на страницу', async () => {
    renderApp('/tasks');
    await screen.findByRole('heading', { name: say.ui('app.broken.title') });

    expect(screen.queryByText(/boom/)).not.toBeInTheDocument();
    expect(
      consoleError.mock.calls.some((call) =>
        call.some((argument) => argument instanceof Error && argument.message.includes('boom')),
      ),
    ).toBe(true);
  });
});
