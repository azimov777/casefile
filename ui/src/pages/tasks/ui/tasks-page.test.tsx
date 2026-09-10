import { delay, http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, data, failure, task, taskPackage, taskPage } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { setToken } from '@/shared/api';
import { TASK_PAGE_SIZE } from '@/entities/task';

/** Адреса всех запросов прогона: по ним проверяется, что лишних не было. */
let seen: string[] = [];

beforeEach(() => {
  seen = [];
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
});

function listing(respond: (url: URL) => Response) {
  return http.get(`${API}/api/v1/tasks`, ({ request }) => {
    seen.push(request.url);
    return respond(new URL(request.url));
  });
}

function open(path: string) {
  setToken('trk_test');
  return renderApp(path);
}

/**
 * Раскрывает форму отбора: свёрнута по умолчанию, поэтому её поля до этого клика
 * не существуют вовсе — ровно так же, как их не видит человек.
 */
async function expandFilters(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Изменить отбор' }));
}

/** Последний запрос списка. Его отсутствие — ошибка теста, а не проверяемое состояние. */
function lastRequest(): URL {
  const url = seen.at(-1);
  if (url === undefined) throw new Error('Запросов к списку задач не было');
  return new URL(url);
}

describe('список задач', () => {
  it('свёрнутый отбор показывает условия чипами, и чип снимается на месте', async () => {
    const user = userEvent.setup();
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?queue=DEMO&status=open&status=in_progress');
    await screen.findByText('DEMO-3');

    const conditions = screen.getByRole('list', { name: 'Условия отбора' });
    // Очередь среди чипов не значится: она место, а не условие (UI-38).
    expect(within(conditions).getAllByRole('listitem')).toHaveLength(1);
    expect(conditions).toHaveTextContent('статус open, in_progress');

    // Доступное имя называет условие целиком: «крестик» сам по себе диктору
    // ничего не говорит, а условий в строке несколько.
    await user.click(
      screen.getByRole('button', { name: 'Убрать условие: статус open, in_progress' }),
    );

    expect(address.current).toContain('queue=DEMO');
    expect(address.current).not.toContain('status=');
  });

  it('без условий чипов нет, а на их месте честная фраза', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks');
    await screen.findByText('DEMO-3');

    const conditions = screen.getByRole('list', { name: 'Условия отбора' });
    expect(conditions).toHaveTextContent('показаны все задачи');
    expect(within(conditions).queryByRole('button')).not.toBeInTheDocument();
  });

  it('заполненный запрос оставляет один чип: остальное он всё равно отменяет', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?queue=DEMO&blocked=true&query=status%3A+open');
    await screen.findByText('DEMO-3');

    const conditions = screen.getByRole('list', { name: 'Условия отбора' });
    const items = within(conditions).getAllByRole('listitem');
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent('запрос: status: open');
  });

  it('смена отбора объявляется вслух, без перевода фокуса', async () => {
    server.use(listing(() => taskPage([task('DEMO-3'), task('DEMO-4')])));

    open('/tasks?queue=DEMO');

    // Область постоянная, а не появляется вместе с текстом: `aria-live` объявляет
    // только то, что пришло внутрь уже существующего контейнера.
    await waitFor(() => {
      expect(document.querySelector('[aria-live="polite"]')).toHaveTextContent('Найдено задач: 2');
    });
  });

  it('старая ссылка со снятым условием открывает список без него, а не падает', async () => {
    server.use(listing(() => taskPage([task('DEMO-8')])));

    // `tags` сняты вместе с полем задачи (UI-41), но разосланные ссылки остались.
    // Неизвестное значение в адресе отбрасывается тем же правилом, что и опечатка:
    // человек видит список очереди, а не пустоту и не сломанный экран.
    open('/tasks?queue=DEMO&tags=frontend&priority=high');

    await screen.findByText('DEMO-8');
    const request = lastRequest();
    expect(request.searchParams.getAll('tags')).toEqual([]);
    expect(request.searchParams.getAll('priority')).toEqual(['high']);

    const conditions = screen.getByRole('list', { name: 'Условия отбора' });
    expect(conditions).toHaveTextContent('приоритет high');
    expect(conditions).not.toHaveTextContent(/тег/i);
  });

  it('признаки строки — три разных знака, и каждый называет себя по-русски', async () => {
    server.use(
      listing(() =>
        taskPage([
          task('DEMO-9', {
            features: {
              blocked: true,
              open_questions: 2,
              open_blocking_questions: 0,
              open_remarks: 3,
              last_summary_at: null,
              last_entry_at: null,
            },
          }),
        ]),
      ),
    );

    open('/tasks?queue=DEMO');

    const row = await screen.findByRole('row', { name: /DEMO-9/ });
    const marks = within(row)
      .getAllByTitle(/./)
      .filter((node) => node.dataset.mark === 'feature');

    expect(marks).toHaveLength(3);
    expect(row).toHaveTextContent(/заблокирована/);
    expect(row).toHaveTextContent('вопросов без ответа: 2');
    expect(row).toHaveTextContent('замечаний без разбора: 3');

    // Различие держится не только цветом: у каждого знака свой рисунок.
    const shapes = marks.map((node) => node.querySelector('svg')?.innerHTML ?? '');
    expect(new Set(shapes).size).toBe(3);
  });

  it('статус и приоритет в строке названы родом: знак читается и глазом, и диктором', async () => {
    server.use(
      listing(() => taskPage([task('DEMO-4', { status: 'in_progress', priority: 'critical' })])),
    );

    open('/tasks?queue=DEMO');

    const row = await screen.findByRole('row', { name: /DEMO-4/ });
    // Знак несёт форму, а род значения — текстом рядом: иначе диктор прочёл бы
    // «in_progress critical» и не сказал бы, что из этого чем является.
    expect(row).toHaveTextContent('статус in_progress');
    expect(row).toHaveTextContent('приоритет critical');
  });

  it('ожидание видно в строке своим знаком, а отбор по нему собирает очередь человека', async () => {
    const user = userEvent.setup();
    server.use(
      listing(() =>
        taskPage([
          task('DEMO-5', { status: 'waiting' }),
          task('DEMO-6', { status: 'in_progress' }),
        ]),
      ),
    );

    open('/tasks?queue=DEMO');

    const waiting = await screen.findByRole('row', { name: /DEMO-5/ });
    expect(waiting).toHaveTextContent('статус waiting');

    // Форма, а не только цвет: ожидание не повторяет работу рисунком — на
    // чёрно-белом экране рисунок остаётся единственным различием между ними.
    const shapeOf = (row: HTMLElement) =>
      row.querySelector('[data-mark="status"] svg')?.innerHTML ?? '';
    const working = screen.getByRole('row', { name: /DEMO-6/ });
    expect(shapeOf(waiting)).not.toBe(shapeOf(working));
    expect(shapeOf(waiting)).not.toBe('');

    // «Что ждёт меня» — одно действие: флажок уходит в адрес, в запрос и обратно чипом.
    await expandFilters(user);
    await user.click(screen.getByRole('checkbox', { name: 'waiting' }));

    await waitFor(() => {
      expect(lastRequest().searchParams.getAll('status')).toEqual(['waiting']);
    });
    expect(address.current).toContain('status=waiting');
    expect(screen.getByRole('list', { name: 'Условия отбора' })).toHaveTextContent(
      'статус waiting',
    );
  });

  it('в задачу ведёт вся строка: клик по ячейке без ссылок уходит в её задачу', async () => {
    const user = userEvent.setup();
    server.use(
      listing(() => taskPage([task('DEMO-3'), task('DEMO-4')])),
      // Переход настоящий, значит карточка спросит свой пакет: без подмены прогон
      // писал бы в вывод жалобу на неперехваченный запрос.
      http.get(`${API}/api/v1/tasks/DEMO-4`, () => data(taskPackage('DEMO-4'))),
    );

    open('/tasks?queue=DEMO');

    const row = await screen.findByRole('row', { name: /DEMO-4/ });
    // Знак приоритета: ссылок и кнопок в этой ячейке нет. До UI-39 сюда попадала
    // растяжка псевдоэлементом, и проверить её можно было только в браузере —
    // а в WebKit она вдобавок накрывала весь экран. Обработчик строки проверяется
    // где угодно, потому и стоит здесь, рядом с остальными разборами строки.
    await user.click(within(row).getByText('normal'));

    await waitFor(() => {
      expect(address.current).toBe('/tasks/DEMO-4');
    });
  });

  it('рисует признаки из строки выдачи, не спрашивая задачу отдельно', async () => {
    server.use(
      listing(() =>
        taskPage([
          task('DEMO-4', {
            status: 'open',
            assignee: 'demo_agent',
            features: {
              blocked: false,
              open_questions: 1,
              open_blocking_questions: 1,
              open_remarks: 0,
              last_summary_at: '2026-09-01T09:00:00Z',
              last_entry_at: '2026-09-01T09:00:00Z',
            },
          }),
          task('DEMO-6', {
            status: 'in_progress',
            priority: 'high',
            features: {
              blocked: true,
              open_questions: 0,
              open_blocking_questions: 0,
              open_remarks: 0,
              last_summary_at: null,
              last_entry_at: null,
            },
          }),
        ]),
      ),
    );

    open('/tasks?queue=DEMO&status=open');

    const blocked = (await screen.findByText('DEMO-6')).closest('tr');
    expect(blocked).not.toBeNull();
    expect(within(blocked as HTMLElement).getByText(/^заблокирована/)).toBeInTheDocument();
    // Время в строке одно — активность в деле; у задачи без записей она названа словами.
    expect(within(blocked as HTMLElement).getByText('в деле пусто')).toBeInTheDocument();
    expect(within(blocked as HTMLElement).queryByText(/сводка/)).toBeNull();

    const waiting = screen.getByText('DEMO-4').closest('tr');
    // Блокирующий вопрос — не отдельный знак, а состояние знака вопросов: четвёртый
    // значок рядом с третьим перестаёт читаться, а различие «вопрос есть» и «вопрос
    // держит работу» важнее ещё одного числа.
    expect(
      within(waiting as HTMLElement).getByText('вопросов без ответа: 1, из них блокирующих: 1'),
    ).toBeInTheDocument();

    // Один запрос на страницу списка и ни одного на строку.
    expect(seen).toHaveLength(1);
    expect(seen.filter((url) => /\/api\/v1\/tasks\/[^?]/.test(url))).toEqual([]);
  });

  it('отправляет условия из адреса структурными параметрами', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?queue=DEMO&status=open&status=in_progress&priority=high&blocked=true');
    await screen.findByText('DEMO-3');

    const request = lastRequest();
    expect(request.searchParams.getAll('queue')).toEqual(['DEMO']);
    expect(request.searchParams.getAll('status')).toEqual(['open', 'in_progress']);
    expect(request.searchParams.getAll('priority')).toEqual(['high']);
    expect(request.searchParams.get('blocked')).toBe('true');
    expect(request.searchParams.get('query')).toBeNull();
  });

  it('восстанавливает форму из адреса', async () => {
    const user = userEvent.setup();
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?queue=DEMO&status=open&assignee=owner');
    await screen.findByText('DEMO-3');
    await expandFilters(user);

    expect(screen.getByRole('checkbox', { name: 'open' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'in_progress' })).not.toBeChecked();
    expect(screen.getByLabelText('Исполнитель')).toHaveValue('owner');
  });

  it('пока грузит, говорит об этом словами', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks`, async ({ request }) => {
        seen.push(request.url);
        await delay(30);
        return taskPage([task('DEMO-3')]);
      }),
    );

    open('/tasks');

    expect(await screen.findByText('Загружаем задачи…')).toBeInTheDocument();
    expect(await screen.findByText('DEMO-3')).toBeInTheDocument();
  });

  it('пустую выдачу объясняет и даёт сбросить условия, не унося из очереди', async () => {
    const user = userEvent.setup();
    server.use(listing(() => taskPage([])));

    open('/tasks?queue=DEMO&status=done');

    expect(await screen.findByText('Задач по этим условиям нет')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));

    // Сброс снимает условия, но не место: человек остаётся в очереди, в которую
    // пришёл, — «уйти отсюда» делается в боковой панели (UI-38).
    const last = lastRequest();
    expect(last.searchParams.getAll('queue')).toEqual(['DEMO']);
    expect(last.searchParams.getAll('status')).toEqual([]);
    expect(address.current).toBe('/tasks?queue=DEMO');
  });

  it('отказ бэкенда объясняет по коду, а не английской фразой', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks`, () => failure('internal_error', 500, 'Unexpected error')),
    );

    open('/tasks');

    expect(await screen.findByRole('alert')).toHaveTextContent('Внутренняя ошибка сервера.');
  });

  it('недоступный сервер называет сервером, а не пустой таблицей', async () => {
    server.use(http.get(`${API}/api/v1/tasks`, () => Response.error()));

    open('/tasks');

    expect(await screen.findByRole('alert')).toHaveTextContent('Сервер недоступен');
  });
});

describe('свёрнутый отбор', () => {
  it('называет все включённые условия и ни одно не прячет за счётчиком', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?queue=DEMO&status=open&status=in_progress&assignee=owner&text=токен');
    await screen.findByText('DEMO-3');

    // Форма закрыта: на первом экране списка стоят задачи, а не поля отбора.
    expect(screen.queryByLabelText('Исполнитель')).toBeNull();

    const conditions = screen.getByRole('list', { name: 'Условия отбора' });
    expect(
      within(conditions)
        .getAllByRole('listitem')
        .map((item) => item.textContent?.replace('Убрать условие: ', '')),
    ).toEqual(['статус open, in_progress', 'исполнитель owner', 'текст «токен»']);
  });

  it('без условий говорит, что показаны все задачи, и не предлагает сброс', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks');
    await screen.findByText('DEMO-3');

    expect(screen.getByText('показаны все задачи')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Сбросить' })).toBeNull();
  });

  it('выбор человека помнится между визитами', async () => {
    const user = userEvent.setup();
    server.use(listing(() => taskPage([task('DEMO-3')])));

    const first = open('/tasks');
    await screen.findByText('DEMO-3');
    await expandFilters(user);
    expect(screen.getByLabelText('Исполнитель')).toBeInTheDocument();
    first.unmount();

    open('/tasks');
    await screen.findByText('DEMO-3');
    expect(screen.getByLabelText('Исполнитель')).toBeInTheDocument();
  });

  it('отказ разбора раскрывает форму сам: опечатка сделана в поле, которого не видно', async () => {
    server.use(
      listing((url) =>
        url.searchParams.has('query')
          ? failure('invalid_search_query', 422, 'Cannot parse', { position: 8 })
          : taskPage([task('DEMO-3')]),
      ),
    );

    open('/tasks?query=status: opne');

    expect(await screen.findByRole('alert')).toHaveTextContent('Ошибка в символе 9');
    expect(screen.getByLabelText('Запрос на языке бэкенда')).toHaveValue('status: opne');
  });
});

describe('поле запроса на языке бэкенда', () => {
  it('показывает позицию и допустимые значения, не очищая таблицу', async () => {
    const user = userEvent.setup();
    server.use(
      listing((url) =>
        url.searchParams.has('query')
          ? failure('search_value_invalid', 422, 'Search value is invalid', {
              field: 'status',
              position: 8,
              value: 'opne',
              allowed: ['backlog', 'open', 'in_progress'],
            })
          : taskPage([task('DEMO-3')]),
      ),
    );

    open('/tasks');
    await screen.findByText('DEMO-3');
    await expandFilters(user);

    await user.type(screen.getByLabelText('Запрос на языке бэкенда'), 'status: opne');
    await user.click(screen.getByRole('button', { name: 'Применить' }));

    const problem = await screen.findByRole('alert');
    expect(problem).toHaveTextContent('Значение условия отбора недопустимо.');
    expect(problem).toHaveTextContent('Ошибка в символе 9');
    expect(problem).toHaveTextContent('Допустимо: backlog, open, in_progress');

    // Таблица остаётся: человек правит запрос, глядя на то, что нашлось до опечатки.
    expect(screen.getByText('DEMO-3')).toBeInTheDocument();
    expect(screen.getByText(/Показаны строки предыдущего отбора/)).toBeInTheDocument();
  });

  it('пока не применён, называет себя черновиком и применяется по Enter', async () => {
    const user = userEvent.setup();
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks');
    await screen.findByText('DEMO-3');
    await expandFilters(user);

    // Применять нечего — кнопка выключена, и это видно до всякого ввода.
    expect(screen.getByRole('button', { name: 'Применить' })).toBeDisabled();

    await user.type(screen.getByLabelText(/Запрос на языке бэкенда/), 'status: done');
    expect(screen.getByText('не применено, Enter применит')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Применить' })).toBeEnabled();

    await user.keyboard('{Enter}');

    expect(lastRequest().searchParams.get('query')).toBe('status: done');
    expect(screen.queryByText('не применено, Enter применит')).toBeNull();
  });

  it('заполненный запрос отменяет структурные условия', async () => {
    const user = userEvent.setup();
    server.use(listing(() => taskPage([task('DEMO-1', { status: 'done' })])));

    open('/tasks?queue=DEMO&status=open');
    await screen.findByText('DEMO-1');
    await expandFilters(user);

    await user.type(screen.getByLabelText('Запрос на языке бэкенда'), 'status: done');
    await user.click(screen.getByRole('button', { name: 'Применить' }));

    const last = lastRequest();
    expect(last.searchParams.get('query')).toBe('status: done');
    expect(last.searchParams.getAll('status')).toEqual([]);
    expect(last.searchParams.getAll('queue')).toEqual([]);
  });
});

describe('порядок и страницы', () => {
  it('порядок берётся из адреса и уезжает в запрос тем же ключом', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?sort=-priority');
    await screen.findByText('DEMO-3');

    // Список сортировки — компонент Radix, и открыть его в jsdom нельзя: вёрстки нет,
    // а он опирается на неё (`docs/notes/testing.md`). Здесь проверяется то, что от
    // страницы и зависит: порядок читается из адреса, показан человеку и уходит в
    // запрос. Сам выбор значения клавиатурой проверяет `e2e/filters.spec.ts`.
    expect(screen.getByRole('combobox', { name: 'Сортировка' })).toHaveTextContent(
      'сначала важные',
    );
    expect(lastRequest().searchParams.getAll('sort')).toEqual(['-priority']);
  });

  /**
   * Выдача из `total` задач, нарезанная по страницам смещением из запроса, — ровно так,
   * как её отдаёт бэкенд (TRK-41): `offset` пропускает строки, `total` не зависит от
   * страницы, а за концом выдачи приходит пустой кусок с тем же `total`.
   */
  function paged(total: number) {
    return listing((url) => {
      const offset = Number(url.searchParams.get('offset') ?? '0');
      const keys = Array.from({ length: total }, (_, index) => `DEMO-${index + 1}`);
      const chunk = keys.slice(offset, offset + TASK_PAGE_SIZE);

      return taskPage(
        chunk.map((key) => task(key)),
        { total, has_more: offset + TASK_PAGE_SIZE < total },
      );
    });
  }

  it('ряд страниц уводит на другую страницу выдачи: меняются и строки, и адрес', async () => {
    const user = userEvent.setup();
    server.use(paged(120));

    open('/tasks');
    await screen.findByText('DEMO-1');

    // Число у заголовка — вся выдача по отбору, а не строки этой страницы.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('120');
    expect(screen.getByText('Страница 1 из 3')).toBeInTheDocument();

    await user.click(screen.getByRole('link', { name: 'Страница 2' }));

    expect(await screen.findByText('DEMO-51')).toBeInTheDocument();
    expect(screen.queryByText('DEMO-1')).not.toBeInTheDocument();
    // Смещение считается из номера страницы и размера страницы, и больше ничего
    // в запросе не меняется: курсора рядом нет — бэкенд отверг бы оба сразу.
    expect(lastRequest().searchParams.get('offset')).toBe('50');
    expect(lastRequest().searchParams.get('cursor')).toBeNull();
    expect(address.current).toBe('/tasks?page=2');
  });

  it('открытая страница названа диктору, и ходить по ряду можно клавиатурой', async () => {
    const user = userEvent.setup();
    server.use(paged(120));

    open('/tasks?page=2');
    await screen.findByText('DEMO-51');

    expect(screen.getByRole('link', { name: 'Страница 2' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: 'Страница 1' })).not.toHaveAttribute('aria-current');

    // Табуляция доводит до ряда, Enter уводит на страницу: ряд собран ссылками,
    // а не кнопками с обработчиком.
    screen.getByRole('link', { name: 'Предыдущая страница' }).focus();
    await user.keyboard('{Enter}');

    expect(await screen.findByText('DEMO-1')).toBeInTheDocument();
    expect(address.current).toBe('/tasks');
  });

  it('на первой и последней странице шаг за край не ссылка, а глухая ступень', async () => {
    server.use(paged(120));

    open('/tasks');
    await screen.findByText('DEMO-1');

    // Ссылки нет — вести некуда; на её месте запрещённая кнопка, а не приглушённая
    // ссылка: имя на `a` без `href` диктору не полагается вовсе.
    expect(screen.queryByRole('link', { name: 'Предыдущая страница' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Предыдущая страница' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Следующая страница' })).toBeInTheDocument();
  });

  it('кнопки «Ещё» в табличном пути нет: способ листать один', async () => {
    server.use(paged(120));

    open('/tasks');
    await screen.findByText('DEMO-1');

    expect(screen.queryByRole('button', { name: 'Ещё' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'В начало списка' })).toBeNull();
    expect(screen.queryByText('Это последняя страница.')).toBeNull();
  });

  it('единственная страница ряда не рисует: листать нечего', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks');
    await screen.findByText('DEMO-3');

    expect(screen.queryByRole('navigation', { name: 'Страницы выдачи' })).toBeNull();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('1');
  });

  it('пустая выдача не обещает ни страниц, ни задач', async () => {
    server.use(listing(() => taskPage([], { total: 0 })));

    open('/tasks?queue=DEMO&status=done');

    expect(await screen.findByText('Задач по этим условиям нет')).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Страницы выдачи' })).toBeNull();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('0');
  });

  it('ссылка на страницу за концом выдачи объясняется и возвращает рядом', async () => {
    const user = userEvent.setup();
    server.use(paged(120));

    open('/tasks?page=9');

    // Бэкенд отвечает пустой страницей и прежним `total`: задачи есть, просто не здесь,
    // и лечится это не сбросом отбора, а возвратом на существующую страницу.
    expect(await screen.findByText(/по этим условиям их 120/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Сбросить фильтры' })).toBeNull();
    expect(screen.getByText('Страниц: 3')).toBeInTheDocument();

    // Шаг назад отсюда ведёт на последнюю существующую страницу, а не на соседний
    // по счёту номер: из пустоты в пустоту вести некуда.
    expect(screen.getByRole('link', { name: 'Предыдущая страница' })).toHaveAttribute(
      'href',
      '/tasks?page=3',
    );
    expect(screen.getByRole('button', { name: 'Следующая страница' })).toBeDisabled();

    await user.click(screen.getByRole('link', { name: 'Страница 3' }));

    expect(await screen.findByText('DEMO-101')).toBeInTheDocument();
    expect(address.current).toBe('/tasks?page=3');
  });

  it('без общего числа номеров нет, но «дальше» остаётся честным', async () => {
    const user = userEvent.setup();
    server.use(
      listing((url) =>
        url.searchParams.get('offset') === '50'
          ? taskPage([task('DEMO-77')], { total: null })
          : taskPage([task('DEMO-3')], { total: null, has_more: true }),
      ),
    );

    open('/tasks');
    await screen.findByText('DEMO-3');

    // Номер страницы известен — он в адресе; сколько их всего, не знает никто,
    // и выдумывать это число нельзя.
    expect(screen.getByText('Страница 1')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Страница 2' })).toBeNull();

    await user.click(screen.getByRole('link', { name: 'Следующая страница' }));

    expect(await screen.findByText('DEMO-77')).toBeInTheDocument();
    expect(address.current).toBe('/tasks?page=2');
    expect(screen.getByText('Страница 2')).toBeInTheDocument();
  });

  it('старая ссылка с курсором открывает список с начала, а не падает', async () => {
    server.use(paged(120));

    // Курсор в адресе таблицы больше ничего не значит: страница адресуется номером,
    // а прислать бэкенду оба адреса сразу — `422 cursor_with_offset`.
    open('/tasks?queue=DEMO&cursor=eyJrIjogIkRFTU8tNTEifQ');

    await screen.findByText('DEMO-1');
    expect(lastRequest().searchParams.get('cursor')).toBeNull();
    expect(lastRequest().searchParams.get('offset')).toBeNull();
  });

  it('смена условий возвращает на первую страницу: страницы 3 в новой выдаче может не быть', async () => {
    const user = userEvent.setup();
    server.use(paged(120));

    open('/tasks?page=3');
    await screen.findByText('DEMO-101');

    await expandFilters(user);
    await user.click(screen.getByRole('checkbox', { name: 'open' }));

    await waitFor(() => {
      expect(lastRequest().searchParams.get('offset')).toBeNull();
    });
    expect(address.current).toBe('/tasks?status=open');
  });
});

describe('отбор по замечаниям', () => {
  it('флажок «есть неразобранные замечания» уходит в адрес и в запрос', async () => {
    const asked: URL[] = [];
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/tasks`, ({ request }) => {
        asked.push(new URL(request.url));
        return taskPage([task('DEMO-1')]);
      }),
    );
    const user = userEvent.setup();
    open('/tasks');

    await screen.findByText('DEMO-1');
    await expandFilters(user);
    await user.click(screen.getByLabelText('есть неразобранные замечания'));

    // Отбор живёт в адресе: перезагрузка и присланная ссылка покажут то же самое.
    await waitFor(() => expect(address.current).toContain('remarks=true'));
    await waitFor(() => expect(asked.at(-1)?.searchParams.get('query')).toBe('open_remarks: > 0'));
    expect(screen.getByLabelText('есть неразобранные замечания')).toBeChecked();
  });
});

describe('переключение вида', () => {
  it('переносит на доску весь отбор, а не только адрес раздела', async () => {
    const user = userEvent.setup();
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?queue=DEMO&status=open&priority=high&assignee=owner&sort=key');
    await screen.findByText('DEMO-3');

    await user.click(screen.getByRole('link', { name: 'Доска' }));

    // Раньше отсюда уходили на голое `/tasks?view=board`: очередь и всё остальное
    // молча оставались позади, и человек видел чужую выдачу.
    await waitFor(() => expect(address.current).toContain('view=board'));
    expect(address.current).toContain('queue=DEMO');
    expect(address.current).toContain('priority=high');
    expect(address.current).toContain('assignee=owner');
    expect(address.current).toContain('sort=key');

    const request = lastRequest();
    expect(request.searchParams.getAll('queue')).toEqual(['DEMO']);
    expect(request.searchParams.getAll('priority')).toEqual(['high']);
  });

  it('возврат в таблицу отдаёт тот же отбор обратно', async () => {
    const user = userEvent.setup();
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?view=board&queue=DEMO&priority=high');
    await screen.findByText('DEMO-3');

    await user.click(screen.getByRole('link', { name: 'Таблица' }));

    await waitFor(() => expect(address.current).toBe('/tasks?queue=DEMO&priority=high'));
  });

  it('текущий вид назван текущим, и переключатель на странице один', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?view=board&queue=DEMO');
    await screen.findByText('DEMO-3');

    expect(screen.getByRole('link', { name: 'Доска' })).toHaveAttribute('aria-current', 'true');
    expect(screen.getByRole('link', { name: 'Таблица' })).not.toHaveAttribute('aria-current');
    // Второй точки переключения нет: в шапке доска больше не раздел.
    expect(screen.getAllByRole('link', { name: 'Доска' })).toHaveLength(1);
  });

  it('верхняя полоса называет место: очередь и раздел', async () => {
    server.use(listing(() => taskPage([task('DEMO-3')])));

    open('/tasks?view=board&queue=DEMO&priority=high');
    await screen.findByText('DEMO-3');

    expect(screen.getByLabelText('Где я')).toHaveTextContent('DEMO/Задачи');
  });

  it('внутри задачи место называет её очередь и ключ, а вида не показывает', async () => {
    server.use(
      listing(() => taskPage([task('DEMO-3')])),
      http.get(`${API}/api/v1/tasks/DEMO-3`, () => data(taskPackage('DEMO-3'))),
    );

    open('/tasks/DEMO-3?entry=4');
    await screen.findAllByText('DEMO-3');

    // Очередь прочитана из ключа задачи: отдельного запроса ради неё нет.
    expect(screen.getByLabelText('Где я')).toHaveTextContent('DEMO/DEMO-3');
    // Переключать нечего: вид есть только у списка.
    expect(screen.queryByRole('link', { name: 'Доска' })).not.toBeInTheDocument();
  });
});
