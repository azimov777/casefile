import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { act, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, taskPackage } from '@testing/msw/responses';
import { liveJournal } from '@testing/live-journal';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { task } from '@testing/msw/responses';
import { setToken } from '@/shared/api';

/** Сколько раз спрашивали список задач: по этому видно, перечитал ли кадр экран. */
let listings = 0;

beforeEach(() => {
  listings = 0;
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/tasks`, () => {
      listings += 1;
      return collection([task('DEMO-1', { status: listings > 1 ? 'done' : 'open' })]);
    }),
    http.get(`${API}/api/v1/tasks/DEMO-1`, () => data(taskPackage('DEMO-1'))),
  );
  setToken('trk_test');
});

/** Кадр журнала: запись дела с её сквозным номером, как её отдаёт поток. */
function entry(seq: number, taskKey: string, overrides: Record<string, unknown> = {}) {
  return {
    id: '44444444-4444-4444-4444-444444444444',
    seq,
    no: seq,
    task_key: taskKey,
    author: { kind: 'agent', signature: 'demo_agent' },
    title: 'Запись из потока',
    body: '',
    created_at: '2026-09-01T10:00:00Z',
    type: 'note',
    payload: {},
    ...overrides,
  };
}

describe('живой поток', () => {
  it('открывает одно соединение на вкладку и держит его при переходах', async () => {
    renderApp('/tasks');

    expect(await screen.findByText('на связи')).toBeInTheDocument();
    expect(liveJournal.connections).toBe(1);

    await userEvent.setup().click(screen.getByRole('link', { name: 'Вопросы' }));
    server.use(http.get(`${API}/api/v1/questions`, () => collection([])));

    expect(await screen.findByRole('heading', { name: 'Открытые вопросы' })).toBeInTheDocument();
    // Переход между экранами не стоит нового соединения: поток живёт в оболочке.
    expect(liveJournal.connections).toBe(1);
    expect(liveJournal.closed).toBe(0);
  });

  it('по кадру перечитывает показанное, а не правит кэш руками', async () => {
    renderApp('/tasks');
    await screen.findByText('DEMO-1');
    const before = listings;

    act(() => {
      liveJournal.send(entry(1025, 'DEMO-1', { type: 'status_changed' }));
    });

    // Строка обновилась сама: значение пришло из перечитанной выдачи, а не из кадра.
    expect(await screen.findByText('done')).toBeInTheDocument();
    expect(listings).toBeGreaterThan(before);
  });

  it('вопрос, адресованный мне, объявляется в шапке ссылкой на запись', async () => {
    renderApp('/tasks');
    await screen.findByText('на связи');

    act(() => {
      liveJournal.send(
        entry(1030, 'DEMO-4', {
          type: 'question',
          no: 7,
          payload: { addressees: ['owner'], blocking: true },
        }),
      );
    });

    const notice = await screen.findByRole('link', { name: 'Вам вопрос: DEMO-4#7' });
    expect(notice).toHaveAttribute('href', '/tasks/DEMO-4?entry=7');
  });

  it('вопрос, адресованный не мне, в шапке не появляется', async () => {
    renderApp('/tasks');
    await screen.findByText('на связи');

    act(() => {
      liveJournal.send(
        entry(1031, 'DEMO-4', {
          type: 'question',
          no: 8,
          payload: { addressees: ['demo_agent'], blocking: false },
        }),
      );
    });

    await waitFor(() => expect(liveJournal.options).not.toBeNull());
    expect(screen.queryByText(/Вам вопрос/)).not.toBeInTheDocument();
  });

  it('обрыв виден в шапке, а восстановление перечитывает показанное', async () => {
    renderApp('/tasks');
    await screen.findByText('DEMO-1');

    act(() => liveJournal.options?.onLost());
    expect(await screen.findByText('нет связи')).toBeInTheDocument();

    const before = listings;
    act(() => liveJournal.options?.onOpen());

    // Что случилось в паузу, интерфейс не знает и знать не может: он перечитывает всё,
    // на что человек смотрит, вместо того чтобы догонять пропущенные кадры.
    expect(await screen.findByText('на связи')).toBeInTheDocument();
    await waitFor(() => expect(listings).toBeGreaterThan(before));
  });

  it('в фоновой вкладке кадры копятся и применяются при возврате', async () => {
    renderApp('/tasks');
    await screen.findByText('DEMO-1');
    const before = listings;

    // Вкладка ушла в фон.
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });

    act(() => {
      liveJournal.send(entry(1040, 'DEMO-1', { type: 'status_changed' }));
    });
    await waitFor(() => expect(liveJournal.options).not.toBeNull());
    expect(listings).toBe(before);

    // Человек вернулся.
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(listings).toBeGreaterThan(before));
  });

  it('при 401 поток отдаёт сеанс общей обработке входа', async () => {
    renderApp('/tasks');
    await screen.findByText('на связи');

    act(() => liveJournal.options?.onUnauthorized());

    expect(await screen.findByLabelText('Токен участника')).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });
});
