import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { act, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, taskListing, taskPackage } from '@testing/msw/responses';
import { liveJournal } from '@testing/live-journal';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { task } from '@testing/msw/responses';
import { TASK_COLUMN_PAGE_SIZE, TASK_PAGE_SIZE, type TaskStatus } from '@/entities/task';
import { setToken } from '@/shared/api';
import { COALESCE_WINDOW_MS } from './deferred';

/** Сколько раз спрашивали список задач: по этому видно, перечитал ли кадр экран. */
let listings = 0;
/** Каждый запрос выдачи целиком: доска читает столбцами, и различать их приходится. */
let seen: URL[] = [];

beforeEach(() => {
  listings = 0;
  seen = [];
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

    expect(await screen.findByText(say.ui('live.online'))).toBeInTheDocument();
    expect(liveJournal.connections).toBe(1);

    await userEvent
      .setup()
      .click(screen.getByRole('link', { name: new RegExp(say.ui('app.inbox')) }));
    server.use(
      http.get(`${API}/api/v1/questions`, () => collection([])),
      http.get(`${API}/api/v1/remarks`, () => collection([])),
    );

    expect(await screen.findByRole('heading', { name: say.ui('app.inbox') })).toBeInTheDocument();
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
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();
    expect(listings).toBe(before);
    expect(screen.getByText('open')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: say.ui('live.show') }));

    // Значение пришло из перечитанной выдачи, а не из кадра: кэш руками не правится.
    expect(await screen.findByText('done')).toBeInTheDocument();
    expect(listings).toBeGreaterThan(before);
    expect(screen.queryByText(say.ui('live.changed', { count: 1 }))).not.toBeInTheDocument();
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
    expect(await screen.findByText(say.ui('live.changed', { count: 2 }))).toBeInTheDocument();
  });

  it('полоса уходит вместе с таблицей и возвращается с ней же', async () => {
    const user = userEvent.setup();
    renderApp('/tasks');
    await screen.findByText('DEMO-1');

    act(() => {
      liveJournal.send(entry(1035, 'DEMO-1', { type: 'status_changed' }));
    });
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: say.tasks('view.board') }));
    await screen.findByRole('region', { name: 'open' });

    // На доске полосы нет: она обновляется сама, и предлагать ей нечего (UI-72).
    expect(screen.queryByText(say.ui('live.changed', { count: 1 }))).not.toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: say.tasks('view.table') }));

    // Накопленное живёт в модуле, а не в странице: таблица возвращается со своей
    // полосой и своим числом.
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();
  });

  it('вопрос, адресованный мне, объявляется уведомлением со ссылкой на запись', async () => {
    renderApp('/tasks');
    await screen.findByText(say.ui('live.online'));

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
    expect(screen.getByText(say.ui('live.blockingBadge'))).toBeVisible();
  });

  it('вопрос, адресованный не мне, уведомления не даёт', async () => {
    renderApp('/tasks');
    await screen.findByText(say.ui('live.online'));

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
    expect(
      screen.getByRole('complementary', { name: say.ui('live.questionsToMe') }),
    ).toBeEmptyDOMElement();
  });

  it('два вопроса подряд видны оба: второй не затирает первый', async () => {
    renderApp('/tasks');
    await screen.findByText(say.ui('live.online'));

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

  it('закрытое среднее уведомление уходит одно, соседи остаются на своих местах', async () => {
    renderApp('/tasks');
    await screen.findByText(say.ui('live.online'));

    act(() => {
      for (const no of [20, 21, 22]) {
        liveJournal.send(
          entry(1050 + no, 'DEMO-4', {
            type: 'question',
            no,
            payload: { addressees: ['owner'], blocking: false },
          }),
        );
      }
    });

    await screen.findByRole('link', { name: 'DEMO-4#22' });

    await userEvent
      .setup()
      .click(
        screen.getByRole('button', { name: say.ui('live.dismiss', { reference: 'DEMO-4#21' }) }),
      );

    // Стопка редеет по одному: закрытая карточка уходит, соседи остаются на своих
    // местах и в прежнем порядке — уходящий не перепрыгивает в конец выдачи.
    const notice = screen.getByRole('complementary', { name: say.ui('live.questionsToMe') });
    expect(
      within(notice)
        .getAllByRole('link')
        .map((link) => link.textContent),
    ).toEqual(['DEMO-4#20', 'DEMO-4#22']);
  });

  it('тот же кадр, приехавший второй раз, второго уведомления не даёт', async () => {
    renderApp('/tasks');
    await screen.findByText(say.ui('live.online'));

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
    await screen.findByText(say.ui('live.online'));

    const question = entry(1035, 'DEMO-4', {
      type: 'question',
      no: 12,
      payload: { addressees: ['owner'], blocking: false },
    });

    act(() => liveJournal.send(question));
    await screen.findByRole('link', { name: 'DEMO-4#12' });

    await userEvent
      .setup()
      .click(
        screen.getByRole('button', { name: say.ui('live.dismiss', { reference: 'DEMO-4#12' }) }),
      );
    expect(screen.queryByRole('link', { name: 'DEMO-4#12' })).not.toBeInTheDocument();

    // Моргание сети не повод спрашивать заново то, на что человек уже сказал «видел».
    act(() => {
      liveJournal.options?.onLost();
      liveJournal.options?.onOpen();
      liveJournal.send(question);
    });

    await waitFor(() => expect(screen.getByText(say.ui('live.online'))).toBeVisible());
    expect(screen.queryByRole('link', { name: 'DEMO-4#12' })).not.toBeInTheDocument();
  });

  it('до открытия потока индикатор не пугает красным', async () => {
    // Первое открытие — обычное начало работы, а не потеря связи: краснеть на каждой
    // загрузке страницы значит обесценить красный к третьему разу.
    renderApp('/tasks');

    expect(await screen.findByText(say.ui('live.online'))).toBeVisible();
    expect(screen.queryByText(say.ui('live.offline'))).not.toBeInTheDocument();
  });

  it('после обрыва список ждёт просьбы, а не переставляется сам', async () => {
    const user = userEvent.setup();
    renderApp('/tasks');
    await screen.findByText('DEMO-1');

    act(() => liveJournal.options?.onLost());
    expect(await screen.findByText(say.ui('live.offline'))).toBeInTheDocument();

    const before = listings;
    act(() => liveJournal.options?.onOpen());

    expect(await screen.findByText(say.ui('live.online'))).toBeInTheDocument();

    // Что случилось в паузу, интерфейс не знает и знать не может — потому и числа
    // в полосе нет. Строки при этом не тронуты: обрыв случается тогда, когда человек
    // ничего не делал, и переставлять список под ним особенно нечестно.
    expect(await screen.findByText(say.ui('live.changedUnknown'))).toBeInTheDocument();
    expect(listings).toBe(before);

    await user.click(screen.getByRole('button', { name: say.ui('live.show') }));
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
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();
    expect(listings).toBe(before);

    await user.click(screen.getByRole('button', { name: say.ui('live.show') }));
    await waitFor(() => expect(listings).toBeGreaterThan(before));
  });

  it('испорченный токен не роняет поток в вечное переподключение, а ведёт на вход', async () => {
    // Токен, из которого не собрать заголовок: поток с ним не откроется никогда,
    // и «нет связи» было бы единственным и притом неверным объяснением.
    setToken(`trk_${String.fromCharCode(1087, 1088, 1080)}`);
    renderApp('/tasks');

    expect(await screen.findByLabelText(say.login('tokenLabel'))).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
    // Соединения не открывалось вовсе: переподключаться нечему.
    expect(liveJournal.connections).toBe(0);
  });

  it('при 401 поток отдаёт сеанс общей обработке входа', async () => {
    renderApp('/tasks');
    await screen.findByText(say.ui('live.online'));

    act(() => liveJournal.options?.onUnauthorized());

    expect(await screen.findByLabelText(say.login('tokenLabel'))).toBeInTheDocument();
    expect(window.localStorage.getItem('tracker.token')).toBeNull();
  });
});

/**
 * Доска под живым потоком.
 *
 * Доска — единственный экран списка, который перечитывает себя сам: переезд карточки
 * между столбцами это то, ради чего на неё смотрят (UI-72). Проверяется здесь и цена
 * этого — сколько запросов уходит на пачку кадров, — и то, что таблица от новой ветки
 * не изменилась ни на шаг.
 */
describe('доска под живым потоком', () => {
  /** Задача, которую агент двигает между столбцами прямо во время теста. */
  let moved = false;

  /**
   * Выдача, отвечающая по отбору столбца, как настоящий бэкенд: общий ответ на все
   * запросы показал бы одну и ту же задачу в каждом столбце, и «переехала» было бы
   * не видно.
   */
  function board(): void {
    moved = false;
    server.use(
      http.get(`${API}/api/v1/tasks`, ({ request }) => {
        const url = new URL(request.url);
        seen.push(url);
        return taskListing(url, [
          task('DEMO-1', { status: moved ? 'in_progress' : 'open' }),
          task('DEMO-2', { status: 'waiting' }),
        ]);
      }),
    );
  }

  /** Запросы за карточками столбцов: у запроса за одним лишь числом страница в строку. */
  function columnRequests(): URL[] {
    return seen.filter((url) => url.searchParams.get('limit') === String(TASK_COLUMN_PAGE_SIZE));
  }

  /** Запросы таблицы: её страница в полсотни строк ни с чем не спутать. */
  function tableRequests(): URL[] {
    return seen.filter((url) => url.searchParams.get('limit') === String(TASK_PAGE_SIZE));
  }

  function column(status: TaskStatus) {
    return screen.getByRole('region', { name: status });
  }

  /**
   * Пауза, внутри которой React волен дорисовывать. Голое ожидание таймера этого права
   * не даёт: перерисовка от пришедшего ответа случилась бы вне `act`, и предупреждение
   * о ней читалось бы как ошибка теста, которой нет.
   */
  async function idle(ms: number): Promise<void> {
    await act(async () => {
      await new Promise((done) => setTimeout(done, ms));
    });
  }

  /** Полоса обновлений. По имени: роль `status` носит и индикатор связи в шапке. */
  function bar() {
    return screen.queryByRole('status', { name: say.ui('live.updates') });
  }

  async function openBoard(): Promise<void> {
    board();
    renderApp('/tasks?queue=DEMO&view=board');
    await screen.findByRole('region', { name: 'open' });
    await within(column('open')).findByRole('article');
    await waitFor(() => expect(columnRequests()).toHaveLength(4));
  }

  it('кадр при видимой вкладке сам переносит карточку в её столбец, и полосы нет', async () => {
    await openBoard();
    expect(within(column('in_progress')).queryByRole('article')).not.toBeInTheDocument();

    // Агент двинул задачу: следующее чтение выдачи покажет её уже в другом столбце.
    moved = true;
    act(() => {
      liveJournal.send(entry(1060, 'DEMO-1', { type: 'status_changed' }));
    });

    // Ни одного нажатия: карточка переехала сама. Ждать приходится дольше обычного —
    // на окно склейки (`COALESCE_WINDOW_MS`), и это его цена, названная вслух.
    expect(
      await within(column('in_progress')).findByRole('article', undefined, { timeout: 5_000 }),
    ).toHaveTextContent('DEMO-1');
    expect(within(column('open')).queryByRole('article')).not.toBeInTheDocument();

    // Полосы на доске нет ни при каком потоке кадров: предлагать показать то, что уже
    // показано, значит врать про состояние экрана.
    expect(bar()).not.toBeInTheDocument();
  });

  it('пачка кадров стоит одного перечитывания, а не десяти', async () => {
    await openBoard();
    const before = columnRequests().length;

    // Десять записей за секунду — обычный заход агента по задаче. Идут вразбивку,
    // а не разом: склейка обязана пережить паузы внутри пачки.
    for (let frame = 0; frame < 10; frame += 1) {
      act(() => {
        liveJournal.send(entry(1070 + frame, 'DEMO-1', { type: 'attempt' }));
      });
      await idle(40);
    }

    await waitFor(() => expect(columnRequests().length).toBeGreaterThan(before), {
      timeout: 5_000,
    });
    // По запросу на раскрытый столбец — четыре, а не сорок: окно склейки одно на пачку.
    expect(columnRequests()).toHaveLength(before + 4);

    // И оно не открывается второй раз само по себе: покой ничего не читает.
    await idle(COALESCE_WINDOW_MS * 1.5);
    expect(columnRequests()).toHaveLength(before + 4);
  });

  it('отключённый запрос таблицы обновление доски не будит', async () => {
    await openBoard();

    act(() => {
      liveJournal.send(entry(1080, 'DEMO-1', { type: 'note' }));
    });
    await waitFor(() => expect(columnRequests()).toHaveLength(8), { timeout: 5_000 });

    // При открытой доске табличный запрос выключен (`enabled: !board`), и его ключ
    // вообще не инвалидируется: он ждёт просьбы человека, а просить на доске негде.
    expect(tableRequests()).toEqual([]);
  });

  it('запросы доски при открытой таблице не будятся: столбцов на экране нет', async () => {
    await openBoard();
    const before = columnRequests().length;

    await userEvent.setup().click(screen.getByRole('link', { name: say.tasks('view.table') }));
    await screen.findByRole('table');

    act(() => {
      liveJournal.send(entry(1090, 'DEMO-1', { type: 'note' }));
    });
    await waitFor(() => expect(bar()).toBeInTheDocument());

    // Окно склейки закрылось, ключи доски помечены устаревшими — но её запросов
    // на экране нет, и в сеть не уходит ничего. Таблица при этом ждёт нажатия.
    await idle(COALESCE_WINDOW_MS * 1.5);
    expect(columnRequests()).toHaveLength(before);
    expect(bar()).toHaveTextContent(say.ui('live.changed', { count: 1 }));
  });

  it('в фоновой вкладке доска молчит, а возврат приносит накопленное разом', async () => {
    await openBoard();
    const before = columnRequests().length;

    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    moved = true;
    act(() => {
      for (const frame of [1100, 1101, 1102]) {
        liveJournal.send(entry(frame, 'DEMO-1', { type: 'status_changed' }));
      }
    });

    // Невидимая вкладка не перечитывает ничего: живость нужна тому, кто смотрит.
    await idle(COALESCE_WINDOW_MS * 1.5);
    expect(columnRequests()).toHaveLength(before);

    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });

    // Накопленное вылилось одним перечитыванием — по запросу на столбец, а не по три.
    expect(
      await within(column('in_progress')).findByRole('article', undefined, { timeout: 5_000 }),
    ).toHaveTextContent('DEMO-1');
    expect(columnRequests()).toHaveLength(before + 4);
    expect(bar()).not.toBeInTheDocument();
  });

  it('переподключение после обрыва обновляет доску само', async () => {
    await openBoard();
    const before = columnRequests().length;

    act(() => liveJournal.options?.onLost());
    expect(await screen.findByText(say.ui('live.offline'))).toBeInTheDocument();

    // За время обрыва могло случиться что угодно, и кадров об этом не будет вовсе:
    // доска перечитывает своё сама, а полосе с выдуманным числом здесь места нет.
    moved = true;
    act(() => liveJournal.options?.onOpen());

    expect(
      await within(column('in_progress')).findByRole('article', undefined, { timeout: 5_000 }),
    ).toHaveTextContent('DEMO-1');
    expect(columnRequests()).toHaveLength(before + 4);
    expect(bar()).not.toBeInTheDocument();
  });
});
