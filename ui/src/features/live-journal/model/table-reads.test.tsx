import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { act, screen, waitFor, within } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  failure,
  projectDetail,
  task,
  taskListing,
  taskPackage,
} from '@testing/msw/responses';
import { liveJournal } from '@testing/live-journal';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { TASK_PAGE_SIZE, taskKeys, type Task, type TaskStatus } from '@/entities/task';
import { setToken } from '@/shared/api';
import { holdForRequest, requestedIsVague, requestedTaskCount } from './deferred';
import { watchTableReads } from './table-reads';

/** Кадр журнала: запись дела с её сквозным номером, как её отдаёт поток. */
function entry(seq: number, taskKey: string, type = 'status_changed') {
  return {
    id: '44444444-4444-4444-4444-444444444444',
    seq,
    no: seq,
    task_key: taskKey,
    author: { kind: 'agent', signature: 'demo_agent' },
    title: 'Запись из потока',
    body: '',
    created_at: '2026-09-01T10:00:00Z',
    type,
    payload: {},
  };
}

/**
 * Ответ, который приходит тогда, когда скажет тест: так видно, что делает полоса,
 * пока запрос таблицы в пути.
 */
function gate<T>(value: T) {
  let open!: () => void;
  let fail!: () => void;
  const promise = new Promise<T>((resolve, reject) => {
    open = () => resolve(value);
    fail = () => reject(new Error('Бэкенд не ответил'));
  });
  return { promise, open, fail };
}

/**
 * Слежение за чтениями таблицы — на голом кэше, без экрана: здесь подаются условия,
 * которых страница сама не создаст (два чтения разных ключей сразу, ручная запись
 * в кэш), и видно, что именно снимает полосу и когда.
 */
describe('чтение таблицы снимает накопленное полосой', () => {
  const TABLE = taskKeys.table;
  let client: QueryClient;
  let stop: () => void;

  beforeEach(() => {
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    stop = watchTableReads(client);
  });

  afterEach(() => {
    stop();
    client.clear();
  });

  function read(params: Record<string, unknown>, answer: Promise<unknown>) {
    return client.fetchQuery({ queryKey: taskKeys.list(params), queryFn: () => answer });
  }

  it('забирает накопленное в начале чтения, а кадр из пути оставляет полосе', async () => {
    holdForRequest([TABLE], 'DEMO-1');
    const answer = gate({ items: [] });
    const reading = read({}, answer.promise);

    // Ответа ещё нет, а полоса уже молчит: всё, что пришло до запроса, он принесёт.
    expect(requestedTaskCount()).toBe(0);

    // Кадр пришёл, пока запрос в пути: сервер мог прочитать выдачу раньше записи.
    holdForRequest([TABLE], 'DEMO-2');
    answer.open();
    await reading;

    // Лёгший ответ забыл только то, что было до его начала.
    expect(requestedTaskCount()).toBe(1);
  });

  it('отказ чтения возвращает забранное вместе с пришедшим за время чтения', async () => {
    holdForRequest([TABLE], 'DEMO-1');
    const answer = gate({ items: [] });
    const reading = read({}, answer.promise);
    holdForRequest([TABLE], 'DEMO-1');
    holdForRequest([TABLE], 'DEMO-2');

    answer.fail();
    await expect(reading).rejects.toThrow();

    // Строки на экране остались прежними — полоса снова говорит обо всём, что они
    // не видели, и считает задачи, а не кадры.
    expect(requestedTaskCount()).toBe(2);
  });

  it('пока в пути другое чтение таблицы, лёгший ответ забранного не забывает', async () => {
    holdForRequest([TABLE], 'DEMO-1');
    const first = gate({ items: [] });
    const firstRead = read({}, first.promise);

    // Отбор сменили посреди чтения: второй ключ таблицы читается рядом с первым.
    holdForRequest([TABLE], 'DEMO-2');
    const second = gate({ items: [] });
    const secondRead = read({ project: ['DEMO'] }, second.promise);
    expect(requestedTaskCount()).toBe(0);

    first.open();
    await firstRead;
    second.fail();
    await expect(secondRead).rejects.toThrow();

    // Первый ответ ничего не забыл: второй кадр мог не попасть в него, а второе
    // чтение не дошло. Полоса говорит об обоих — лишнее предложение, а не потеря.
    expect(requestedTaskCount()).toBe(2);
  });

  it('когда все чтения таблицы легли, забранное забыто и отказ следующего его не вернёт', async () => {
    holdForRequest([TABLE], 'DEMO-1');
    const first = gate({ items: [] });
    const second = gate({ items: [] });
    const reads = [read({}, first.promise), read({ project: ['DEMO'] }, second.promise)];
    first.open();
    second.open();
    await Promise.all(reads);
    expect(requestedTaskCount()).toBe(0);

    const third = gate({ items: [] });
    const failing = read({ page: 2 }, third.promise);
    third.fail();
    await expect(failing).rejects.toThrow();
    expect(requestedTaskCount()).toBe(0);
  });

  it('«изменилось неизвестно что» подчиняется тому же правилу', async () => {
    // Так приходит переподключение: задачи не названы.
    holdForRequest([TABLE], null);
    expect(requestedIsVague()).toBe(true);

    const failed = gate({ items: [] });
    const failing = read({}, failed.promise);
    expect(requestedIsVague()).toBe(false);
    failed.fail();
    await expect(failing).rejects.toThrow();
    expect(requestedIsVague()).toBe(true);

    const landed = gate({ items: [] });
    const reading = read({}, landed.promise);
    landed.open();
    await reading;
    expect(requestedIsVague()).toBe(false);
  });

  it('чтения не таблицы и ручная запись в кэш полосу не трогают', async () => {
    holdForRequest([TABLE], 'DEMO-1');

    await client.fetchQuery({ queryKey: ['task', 'DEMO-1'], queryFn: () => ({ key: 'DEMO-1' }) });
    await client.fetchQuery({
      queryKey: taskKeys.column({ status: ['open'] }),
      queryFn: () => ({ items: [] }),
    });
    // Ручная запись — не чтение: этих строк сервер не отдавал.
    client.setQueryData(taskKeys.list({}), { items: [] });

    expect(requestedTaskCount()).toBe(1);
  });
});

/**
 * Таблица на прибытии: приход с доски и из карточки, смена отбора, «Показать» — и то,
 * что пришло, пока запрос таблицы в пути.
 *
 * Выдача здесь живая: агент меняет статус задачи на «сервере» и следом шлёт кадр —
 * так и работает бэкенд, отдающий кадр из уже подшитой записи. Ответ снимается в тот
 * миг, когда запрос дошёл до сервера, а не когда вернулся: запись, подшитая, пока
 * ответ в пути, в него не попадает.
 */
describe('полоса над таблицей считает с последнего чтения таблицы', () => {
  let rows: Task[] = [];
  let seen: URL[] = [];
  /** Следующий ответ таблицы ждёт, пока тест его не отпустит. */
  let held: Promise<void> | null = null;
  /** Таблица отвечает отказом: бэкенд лёг. */
  let broken = false;

  function isTable(url: URL): boolean {
    return url.searchParams.get('limit') === String(TASK_PAGE_SIZE);
  }

  beforeEach(() => {
    rows = [task('DEMO-1', { status: 'open' }), task('DEMO-2', { status: 'waiting' })];
    seen = [];
    held = null;
    broken = false;
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/tasks`, async ({ request }) => {
        const url = new URL(request.url);
        seen.push(url);
        const snapshot = rows.map((row) => ({ ...row }));
        if (isTable(url) && broken) return failure('internal_error', 500);
        if (isTable(url) && held !== null) {
          const wait = held;
          held = null;
          await wait;
        }
        return taskListing(url, snapshot);
      }),
      http.get(`${API}/api/v1/tasks/DEMO-1`, () => data(taskPackage('DEMO-1'))),
      http.get(`${API}/api/v1/tasks/DEMO-1/entries`, () => collection([])),
      http.get(`${API}/api/v1/projects/DEMO`, () => data(projectDetail('DEMO'))),
    );
    setToken('trk_test');
  });

  function tableRequests(): URL[] {
    return seen.filter(isTable);
  }

  /** Агент подшил запись, и статус задачи сменился: сперва на сервере, потом кадр. */
  function agentMoves(seq: number, key: string, status: TaskStatus): void {
    rows = rows.map((row) => (row.key === key ? { ...row, status } : row));
    act(() => {
      liveJournal.send(entry(seq, key));
    });
  }

  function holdTable(): () => void {
    let open!: () => void;
    held = new Promise<void>((resolve) => {
      open = resolve;
    });
    return () => act(() => open());
  }

  /** Строка таблицы по ключу задачи. */
  function row(key: string): HTMLElement {
    const header = screen.getByRole('rowheader', { name: key });
    return header.closest('tr') as HTMLElement;
  }

  /** Полоса обновлений. По имени: роль `status` носит и индикатор связи в шапке. */
  function bar() {
    return screen.queryByRole('status', { name: say.ui('live.updates') });
  }

  /**
   * Появлялась ли полоса хоть на одну отрисовку. Её отсутствие в конце шага мало что
   * значит: полоса, мелькнувшая на приходе и тут же ушедшая, — это и есть враньё про
   * экран, только короткое.
   *
   * Смотрятся и вставленные, и **снятые** узлы. Наблюдатель зовётся после того, как
   * React дорисовал всё, эффекты тоже: полоса, пришедшая внутри целиком вставленной
   * страницы (возврат из карточки), к этому времени из неё уже вынута, и в поддереве
   * вставленного её не найти. Снятым же узел бывает, только если побывал в документе.
   */
  function watchBar(): () => boolean {
    const name = say.ui('live.updates');
    let appeared = false;
    const inspect = (records: MutationRecord[]) => {
      for (const record of records) {
        for (const node of [...record.addedNodes, ...record.removedNodes]) {
          if (!(node instanceof Element)) continue;
          const found = [node, ...node.querySelectorAll('[aria-label]')];
          if (found.some((element) => element.getAttribute('aria-label') === name)) {
            appeared = true;
          }
        }
      }
    };
    const observer = new MutationObserver(inspect);
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      inspect(observer.takeRecords());
      observer.disconnect();
      return appeared;
    };
  }

  async function openBoard(): Promise<void> {
    renderApp('/tasks?project=DEMO&view=board');
    await within(await screen.findByRole('region', { name: 'open' })).findByRole('article');
  }

  it('с доски в таблицу после кадра: полосы нет, запрос таблицы один', async () => {
    const user = userEvent.setup();
    await openBoard();

    agentMoves(1101, 'DEMO-1', 'in_progress');
    // Человек смотрел, как карточка переехала сама: доска догоняет окном склейки.
    expect(
      await within(screen.getByRole('region', { name: 'in_progress' })).findByRole(
        'article',
        undefined,
        { timeout: 5_000 },
      ),
    ).toHaveTextContent('DEMO-1');

    const appeared = watchBar();
    await user.click(screen.getByRole('link', { name: say.tasks('view.table') }));
    expect(await within(await screen.findByRole('table')).findByText('in_progress')).toBeVisible();

    // Одно чтение на прибытие — и полоса над ним не показалась ни на одну отрисовку.
    expect(tableRequests()).toHaveLength(1);
    expect(appeared()).toBe(false);
    expect(bar()).not.toBeInTheDocument();

    // А то, что случилось после прихода, полоса предлагает, как прежде.
    agentMoves(1102, 'DEMO-2', 'open');
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();
    expect(within(row('DEMO-2')).getByText('waiting')).toBeInTheDocument();
    expect(tableRequests()).toHaveLength(1);
  });

  it('из карточки в таблицу после кадров: полосы нет, запрос таблицы один', async () => {
    const user = userEvent.setup();
    renderApp('/tasks?project=DEMO');
    await screen.findByRole('rowheader', { name: 'DEMO-1' });

    // Первый кадр застал человека на таблице — полоса была.
    agentMoves(1111, 'DEMO-2', 'open');
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Задача DEMO-1' }));
    await screen.findByRole('heading', { name: /DEMO-1/ });
    // Второй — на карточке.
    agentMoves(1112, 'DEMO-1', 'in_progress');
    const before = tableRequests().length;

    const appeared = watchBar();
    await user.click(screen.getByRole('link', { name: say.ui('task.nav.backFiltered') }));
    expect(await within(await screen.findByRole('table')).findByText('in_progress')).toBeVisible();

    expect(tableRequests()).toHaveLength(before + 1);
    expect(within(row('DEMO-2')).getByText('open')).toBeInTheDocument();
    expect(appeared()).toBe(false);
    expect(bar()).not.toBeInTheDocument();
  });

  it('кадр, пришедший, пока запрос таблицы в пути, остаётся в полосе', async () => {
    const user = userEvent.setup();
    await openBoard();
    agentMoves(1121, 'DEMO-1', 'in_progress');

    const release = holdTable();
    await user.click(screen.getByRole('link', { name: say.tasks('view.table') }));
    // Запрос дошёл до сервера, выдача снята — ответ ещё в пути.
    await waitFor(() => expect(tableRequests()).toHaveLength(1));

    agentMoves(1122, 'DEMO-2', 'open');
    // Пока таблица читается, полоса молчит: предлагать нечего, строки вот-вот придут.
    expect(bar()).not.toBeInTheDocument();

    release();
    expect(await within(await screen.findByRole('table')).findByText('in_progress')).toBeVisible();

    // Ответ снят до второй записи: `DEMO-2` в нём ещё `waiting`, и полоса говорит
    // ровно о ней. Первый кадр — в ответе, и его полоса не считает: задача одна.
    expect(within(row('DEMO-2')).getByText('waiting')).toBeInTheDocument();
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: say.ui('live.show') }));
    expect(await within(row('DEMO-2')).findByText('open')).toBeInTheDocument();
    expect(bar()).not.toBeInTheDocument();
    expect(tableRequests()).toHaveLength(2);
  });

  it('кадр во время чтения по «Показать» тоже остаётся в полосе', async () => {
    const user = userEvent.setup();
    renderApp('/tasks?project=DEMO');
    await screen.findByRole('rowheader', { name: 'DEMO-1' });

    agentMoves(1131, 'DEMO-1', 'in_progress');
    await screen.findByText(say.ui('live.changed', { count: 1 }));

    const release = holdTable();
    await user.click(screen.getByRole('button', { name: say.ui('live.show') }));
    await waitFor(() => expect(tableRequests()).toHaveLength(2));
    agentMoves(1132, 'DEMO-2', 'open');
    expect(bar()).not.toBeInTheDocument();

    release();
    expect(await within(row('DEMO-1')).findByText('in_progress')).toBeInTheDocument();
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();
    expect(within(row('DEMO-2')).getByText('waiting')).toBeInTheDocument();
  });

  it('чтение после обрыва снимает «неизвестно что», а обрыв посреди чтения его оставляет', async () => {
    const user = userEvent.setup();
    await openBoard();

    act(() => {
      liveJournal.options?.onLost();
      liveJournal.options?.onOpen();
    });
    await screen.findByText(say.ui('live.online'));

    const appeared = watchBar();
    await user.click(screen.getByRole('link', { name: say.tasks('view.table') }));
    await screen.findByRole('table');
    await waitFor(() => expect(tableRequests()).toHaveLength(1));
    expect(appeared()).toBe(false);

    // Второй приход — и связь рвётся, пока ответ в пути.
    await user.click(screen.getByRole('link', { name: say.tasks('view.board') }));
    await screen.findByRole('region', { name: 'open' });
    const release = holdTable();
    await user.click(screen.getByRole('link', { name: say.tasks('view.table') }));
    await waitFor(() => expect(tableRequests()).toHaveLength(2));

    act(() => {
      liveJournal.options?.onLost();
      liveJournal.options?.onOpen();
    });
    release();

    // Что случилось в паузу, ответ мог и не принести: полоса говорит об этом словами.
    expect(await screen.findByText(say.ui('live.changedUnknown'))).toBeInTheDocument();
  });

  it('отказ чтения на прибытии возвращает накопленное в полосу', async () => {
    const user = userEvent.setup();
    await openBoard();
    agentMoves(1141, 'DEMO-1', 'in_progress');

    broken = true;
    await user.click(screen.getByRole('link', { name: say.tasks('view.table') }));
    await waitFor(() => expect(tableRequests()).toHaveLength(1));

    // Чтение не дошло — кадр не забыт: таблица его не видела.
    expect(await screen.findByText(say.ui('live.changed', { count: 1 }))).toBeInTheDocument();

    broken = false;
    await user.click(screen.getByRole('button', { name: say.ui('live.show') }));
    expect(await within(await screen.findByRole('table')).findByText('in_progress')).toBeVisible();
    expect(bar()).not.toBeInTheDocument();
  });

  it('смена отбора — тоже чтение таблицы, и полоса над ним гаснет', async () => {
    const user = userEvent.setup();
    renderApp('/tasks');
    await screen.findByRole('rowheader', { name: 'DEMO-1' });

    agentMoves(1151, 'DEMO-1', 'in_progress');
    await screen.findByText(say.ui('live.changed', { count: 1 }));

    const sections = screen.getByRole('navigation', { name: say.ui('app.sections') });
    await user.click(within(sections).getByRole('link', { name: /^DEMO/ }));

    expect(await within(row('DEMO-1')).findByText('in_progress')).toBeInTheDocument();
    expect(tableRequests()).toHaveLength(2);
    expect(bar()).not.toBeInTheDocument();
  });

  /*
   * Место полосы схлопывается движением, и узел полосы доживает выход (UI-101). Правило
   * ухода от этого не сдвигается: счёт забрало начало чтения в тот же миг, а уходящая
   * полоса инертна — «Показать» в ней не нажать — и говорит то, что говорила, а не
   * «список мог измениться» другой ширины. Что она при этом невидима, jsdom не скажет:
   * стилей в нём нет, и это меряет сквозной сценарий по кадрам (`e2e/live-list.spec.ts`).
   */
  it('уходящая полоса доживает выход инертной и с прежним числом', async () => {
    // Длительность выхода задаётся так же, как её задаёт тема, — свойством на корне:
    // без токена задержка нулевая, и узел уходит сразу (`shared/lib/exit-hold.ts`).
    document.documentElement.style.setProperty('--motion-fast', '120ms');
    try {
      const user = userEvent.setup();
      renderApp('/tasks?project=DEMO');
      await screen.findByRole('rowheader', { name: 'DEMO-1' });

      agentMoves(1161, 'DEMO-1', 'in_progress');
      await screen.findByText(say.ui('live.changed', { count: 1 }));
      const node = screen.getByRole('status', { name: say.ui('live.updates') });
      expect(node).not.toHaveAttribute('inert');

      await user.click(within(node).getByRole('button', { name: say.ui('live.show') }));

      expect(requestedTaskCount()).toBe(0);
      expect(node).toBeInTheDocument();
      expect(node).toHaveAttribute('inert');
      expect(node).toHaveTextContent(say.ui('live.changed', { count: 1 }));

      // И снимается, когда выход кончился.
      await waitFor(() => expect(node).not.toBeInTheDocument());
      expect(await within(row('DEMO-1')).findByText('in_progress')).toBeInTheDocument();
    } finally {
      document.documentElement.style.removeProperty('--motion-fast');
    }
  });
});
