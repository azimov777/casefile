import { delay, http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, collection, data, failure, task } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { setToken } from '@/shared/api';

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
  it('статус и приоритет в строке названы родом: знак читается и глазом, и диктором', async () => {
    server.use(
      listing(() => collection([task('DEMO-4', { status: 'in_progress', priority: 'critical' })])),
    );

    open('/tasks?queue=DEMO');

    const row = await screen.findByRole('row', { name: /DEMO-4/ });
    // Знак несёт форму, а род значения — текстом рядом: иначе диктор прочёл бы
    // «in_progress critical» и не сказал бы, что из этого чем является.
    expect(row).toHaveTextContent('статус in_progress');
    expect(row).toHaveTextContent('приоритет critical');
  });

  it('рисует признаки из строки выдачи, не спрашивая задачу отдельно', async () => {
    server.use(
      listing(() =>
        collection([
          task('DEMO-4', {
            status: 'open',
            assignee: 'demo_agent',
            tags: ['retention'],
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
    expect(within(blocked as HTMLElement).getByText('заблокирована')).toBeInTheDocument();
    // Время в строке одно — активность в деле; у задачи без записей она названа словами.
    expect(within(blocked as HTMLElement).getByText('в деле пусто')).toBeInTheDocument();
    expect(within(blocked as HTMLElement).queryByText(/сводка/)).toBeNull();

    const waiting = screen.getByText('DEMO-4').closest('tr');
    expect(within(waiting as HTMLElement).getByText('блокирующих 1')).toBeInTheDocument();
    expect(within(waiting as HTMLElement).getByText('вопросов 1')).toBeInTheDocument();

    // Один запрос на страницу списка и ни одного на строку.
    expect(seen).toHaveLength(1);
    expect(seen.filter((url) => /\/api\/v1\/tasks\/[^?]/.test(url))).toEqual([]);
  });

  it('отправляет условия из адреса структурными параметрами', async () => {
    server.use(listing(() => collection([task('DEMO-3')])));

    open('/tasks?queue=DEMO&status=open&status=in_progress&priority=high&tags=docs&blocked=true');
    await screen.findByText('DEMO-3');

    const request = lastRequest();
    expect(request.searchParams.getAll('queue')).toEqual(['DEMO']);
    expect(request.searchParams.getAll('status')).toEqual(['open', 'in_progress']);
    expect(request.searchParams.getAll('priority')).toEqual(['high']);
    expect(request.searchParams.getAll('tags')).toEqual(['docs']);
    expect(request.searchParams.get('blocked')).toBe('true');
    expect(request.searchParams.get('query')).toBeNull();
  });

  it('восстанавливает форму из адреса', async () => {
    const user = userEvent.setup();
    server.use(listing(() => collection([task('DEMO-3')])));

    open('/tasks?queue=DEMO&status=open&assignee=owner');
    await screen.findByText('DEMO-3');
    await expandFilters(user);

    expect(screen.getByLabelText('Очередь')).toHaveValue('DEMO');
    expect(screen.getByRole('checkbox', { name: 'open' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'in_progress' })).not.toBeChecked();
    expect(screen.getByLabelText('Исполнитель')).toHaveValue('owner');
  });

  it('пока грузит, говорит об этом словами', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks`, async ({ request }) => {
        seen.push(request.url);
        await delay(30);
        return collection([task('DEMO-3')]);
      }),
    );

    open('/tasks');

    expect(await screen.findByText('Загружаем задачи…')).toBeInTheDocument();
    expect(await screen.findByText('DEMO-3')).toBeInTheDocument();
  });

  it('пустую выдачу объясняет и даёт сбросить условия', async () => {
    const user = userEvent.setup();
    server.use(listing(() => collection([])));

    open('/tasks?queue=DEMO&status=done');

    expect(await screen.findByText('Задач по этим условиям нет')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Сбросить фильтры' }));

    const last = lastRequest();
    expect(last.searchParams.get('queue')).toBeNull();
    expect(last.searchParams.getAll('status')).toEqual([]);
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
    server.use(listing(() => collection([task('DEMO-3')])));

    open(
      '/tasks?queue=DEMO&status=open&status=in_progress&assignee=owner&tags=frontend&tags=ux&query=status: done',
    );
    await screen.findByText('DEMO-3');

    // Форма закрыта: на первом экране списка стоят задачи, а не поля отбора.
    expect(screen.queryByLabelText('Исполнитель')).toBeNull();

    const conditions = screen.getByRole('list', { name: 'Условия отбора' });
    expect(
      within(conditions)
        .getAllByRole('listitem')
        .map((item) => item.textContent),
    ).toEqual([
      'очередь DEMO',
      'статус open, in_progress',
      'исполнитель owner',
      'теги frontend, ux',
      'запрос: status: done',
    ]);

    // Заполненный запрос отменяет структурный отбор: условия названы, но помечены
    // нерабочими — и это сказано на них самих, а не отдельной строкой, которая
    // сдвинула бы таблицу вниз.
    expect(within(conditions).getAllByTitle(/Не действует/)).toHaveLength(4);
  });

  it('без условий говорит, что показаны все задачи, и не предлагает сброс', async () => {
    server.use(listing(() => collection([task('DEMO-3')])));

    open('/tasks');
    await screen.findByText('DEMO-3');

    expect(screen.getByText('показаны все задачи')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Сбросить' })).toBeNull();
  });

  it('выбор человека помнится между визитами', async () => {
    const user = userEvent.setup();
    server.use(listing(() => collection([task('DEMO-3')])));

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
          : collection([task('DEMO-3')]),
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
          : collection([task('DEMO-3')]),
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
    server.use(listing(() => collection([task('DEMO-3')])));

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
    server.use(listing(() => collection([task('DEMO-1', { status: 'done' })])));

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
  it('смена сортировки перезапрашивает список новым ключом', async () => {
    const user = userEvent.setup();
    server.use(listing(() => collection([task('DEMO-3')])));

    open('/tasks');
    await screen.findByText('DEMO-3');

    await user.selectOptions(screen.getByLabelText('Сортировка'), '-priority');

    expect(lastRequest().searchParams.getAll('sort')).toEqual(['-priority']);
  });

  it('«ещё» листает по курсору из meta', async () => {
    const user = userEvent.setup();
    server.use(
      listing((url) =>
        url.searchParams.get('cursor') === 'page-2'
          ? collection([task('DEMO-7')])
          : collection([task('DEMO-3')], { has_more: true, next_cursor: 'page-2' }),
      ),
    );

    open('/tasks');
    await screen.findByText('DEMO-3');

    await user.click(screen.getByRole('button', { name: 'Ещё' }));

    expect(await screen.findByText('DEMO-7')).toBeInTheDocument();
    expect(lastRequest().searchParams.get('cursor')).toBe('page-2');
    expect(screen.getByRole('button', { name: 'В начало списка' })).toBeInTheDocument();
  });

  it('на последней странице кнопки «ещё» нет', async () => {
    server.use(listing(() => collection([task('DEMO-3')])));

    open('/tasks');
    await screen.findByText('DEMO-3');

    expect(screen.queryByRole('button', { name: 'Ещё' })).not.toBeInTheDocument();
    expect(screen.getByText('Это последняя страница.')).toBeInTheDocument();
  });
});

describe('отбор по замечаниям', () => {
  it('флажок «есть неразобранные замечания» уходит в адрес и в запрос', async () => {
    const asked: URL[] = [];
    server.use(
      http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
      http.get(`${API}/api/v1/tasks`, ({ request }) => {
        asked.push(new URL(request.url));
        return collection([task('DEMO-1')]);
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
