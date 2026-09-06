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

  it('кадр не переставляет список сам, а предлагает показать новое', async () => {
    const user = userEvent.setup();
    renderApp('/tasks');
    await screen.findByText('DEMO-1');
    const before = listings;

    act(() => {
      liveJournal.send(entry(1025, 'DEMO-1', { type: 'status_changed' }));
    });

    // Список не перечитан: строки на месте, а об изменении сказано полосой.
    expect(await screen.findByText('Изменилось задач: 1')).toBeInTheDocument();
    expect(listings).toBe(before);
    expect(screen.getByText('open')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Показать' }));

    // Значение пришло из перечитанной выдачи, а не из кадра: кэш руками не правится.
    expect(await screen.findByText('done')).toBeInTheDocument();
    expect(listings).toBeGreaterThan(before);
    expect(screen.queryByText(/Изменилось задач/)).not.toBeInTheDocument();
  });

  it('полоса считает задачи, а не кадры', async () => {
    renderApp('/tasks');
    await screen.findByText('DEMO-1');

    act(() => {
      liveJournal.send(entry(1030, 'DEMO-1'));
      liveJournal.send(entry(1031, 'DEMO-1', { type: 'decision' }));
      liveJournal.send(entry(1032, 'DEMO-2'));
    });

    // Три записи, но задачи две: человеку важно, сколько строк изменится.
    expect(await screen.findByText('Изменилось задач: 2')).toBeInTheDocument();
  });

  it('накопленное переживает переход между таблицей и доской', async () => {
    const user = userEvent.setup();
    renderApp('/tasks');
    await screen.findByText('DEMO-1');

    act(() => {
      liveJournal.send(entry(1035, 'DEMO-1', { type: 'status_changed' }));
    });
    expect(await screen.findByText('Изменилось задач: 1')).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: 'Доска' }));

    // Полоса на месте: страница перемонтировалась, а накопленное живёт не в ней.
    expect(await screen.findByText('Изменилось задач: 1')).toBeInTheDocument();
  });

  it('вопрос, адресованный мне, объявляется уведомлением со ссылкой на запись', async () => {
    renderApp('/tasks');
    await screen.findByText('на связи');

    act(() => {
      liveJournal.send(
        entry(1030, 'DEMO-4', {
          type: 'question',
          no: 7,
          title: 'Удалять ли записи дела отменённых задач через год',
          payload: { addressees: ['owner'], blocking: true },
        }),
      );
    });

    const notice = await screen.findByRole('link', { name: 'DEMO-4#7' });
    expect(notice).toHaveAttribute('href', '/tasks/DEMO-4?entry=7');
    // Ключа мало, чтобы решить, бросать ли текущее дело: видно, о чём спросили.
    expect(screen.getByText('Удалять ли записи дела отменённых задач через год')).toBeVisible();
    expect(screen.getByText('блокирующий')).toBeVisible();
  });

  it('вопрос, адресованный не мне, уведомления не даёт', async () => {
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
    // Область объявления есть всегда, а вот карточки в ней быть не должно.
    expect(screen.getByRole('complementary', { name: 'Вопросы ко мне' })).toBeEmptyDOMElement();
  });

  it('два вопроса подряд видны оба: второй не затирает первый', async () => {
    renderApp('/tasks');
    await screen.findByText('на связи');

    act(() => {
      liveJournal.send(
        entry(1032, 'DEMO-4', {
          type: 'question',
          no: 9,
          payload: { addressees: ['owner'], blocking: false },
        }),
      );
      liveJournal.send(
        entry(1033, 'DEMO-3', {
          type: 'question',
          no: 4,
          payload: { addressees: ['owner'], blocking: false },
        }),
      );
    });

    expect(await screen.findByRole('link', { name: 'DEMO-4#9' })).toBeVisible();
    expect(screen.getByRole('link', { name: 'DEMO-3#4' })).toBeVisible();
  });

  it('тот же кадр, приехавший второй раз, второго уведомления не даёт', async () => {
    renderApp('/tasks');
    await screen.findByText('на связи');

    const question = entry(1034, 'DEMO-4', {
      type: 'question',
      no: 11,
      payload: { addressees: ['owner'], blocking: false },
    });

    // Поток продолжается по `Last-Event-ID`, а граница там по включению: после
    // переподключения тот же кадр приезжает снова. Это норма, а не сбой.
    act(() => {
      liveJournal.send(question);
      liveJournal.send(question);
    });

    expect(await screen.findAllByRole('link', { name: 'DEMO-4#11' })).toHaveLength(1);
  });

  it('закрытое человеком уведомление не возвращается повторным кадром', async () => {
    renderApp('/tasks');
    await screen.findByText('на связи');

    const question = entry(1035, 'DEMO-4', {
      type: 'question',
      no: 12,
      payload: { addressees: ['owner'], blocking: false },
    });

    act(() => liveJournal.send(question));
    await screen.findByRole('link', { name: 'DEMO-4#12' });

    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: 'Закрыть уведомление о вопросе DEMO-4#12' }));
    expect(screen.queryByRole('link', { name: 'DEMO-4#12' })).not.toBeInTheDocument();

    // Моргание сети не повод спрашивать заново то, на что человек уже сказал «видел».
    act(() => {
      liveJournal.options?.onLost();
      liveJournal.options?.onOpen();
      liveJournal.send(question);
    });

    await waitFor(() => expect(screen.getByText('на связи')).toBeVisible());
    expect(screen.queryByRole('link', { name: 'DEMO-4#12' })).not.toBeInTheDocument();
  });

  it('до открытия потока индикатор не пугает красным', async () => {
    // Первое открытие — обычное начало работы, а не потеря связи: краснеть на каждой
    // загрузке страницы значит обесценить красный к третьему разу.
    renderApp('/tasks');

    expect(await screen.findByText('на связи')).toBeVisible();
    expect(screen.queryByText('нет связи')).not.toBeInTheDocument();
  });

  it('после обрыва список ждёт просьбы, а не переставляется сам', async () => {
    const user = userEvent.setup();
    renderApp('/tasks');
    await screen.findByText('DEMO-1');

    act(() => liveJournal.options?.onLost());
    expect(await screen.findByText('нет связи')).toBeInTheDocument();

    const before = listings;
    act(() => liveJournal.options?.onOpen());

    expect(await screen.findByText('на связи')).toBeInTheDocument();

    // Что случилось в паузу, интерфейс не знает и знать не может — потому и числа
    // в полосе нет. Строки при этом не тронуты: обрыв случается тогда, когда человек
    // ничего не делал, и переставлять список под ним особенно нечестно.
    expect(
      await screen.findByText('Пока не было связи, список мог измениться'),
    ).toBeInTheDocument();
    expect(listings).toBe(before);

    await user.click(screen.getByRole('button', { name: 'Показать' }));
    await waitFor(() => expect(listings).toBeGreaterThan(before));
  });

  it('в фоновой вкладке кадры копятся, а возврат не переставляет список', async () => {
    const user = userEvent.setup();
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

    // Человек вернулся и смотрит в ту же точку, где был.
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Накопленное не вылилось на экран: список ждёт просьбы, как и при видимой вкладке.
    expect(await screen.findByText('Изменилось задач: 1')).toBeInTheDocument();
    expect(listings).toBe(before);

    await user.click(screen.getByRole('button', { name: 'Показать' }));
    await waitFor(() => expect(listings).toBeGreaterThan(before));
  });

  it('испорченный токен не роняет поток в вечное переподключение, а ведёт на вход', async () => {
    // Токен, из которого не собрать заголовок: поток с ним не откроется никогда,
    // и «нет связи» было бы единственным и притом неверным объяснением.
    setToken(`trk_${String.fromCharCode(1087, 1088, 1080)}`);
    renderApp('/tasks');

    expect(await screen.findByLabelText('Токен участника')).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
    // Соединения не открывалось вовсе: переподключаться нечему.
    expect(liveJournal.connections).toBe(0);
  });

  it('при 401 поток отдаёт сеанс общей обработке входа', async () => {
    renderApp('/tasks');
    await screen.findByText('на связи');

    act(() => liveJournal.options?.onUnauthorized());

    expect(await screen.findByLabelText('Токен участника')).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });
});
