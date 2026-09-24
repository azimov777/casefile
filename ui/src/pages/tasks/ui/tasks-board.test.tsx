import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { API, bootstrap, data, failure, task, taskListing } from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { reachEnd, watched } from '@testing/intersection';
import { renderApp } from '@testing/render';
import { say } from '@testing/say';
import { TASK_COLUMN_PAGE_SIZE, TASK_STATUSES } from '@/entities/task';
import { setToken } from '@/shared/api';

/** Запросы списка за прогон: доска читает столбцами, и считать их приходится. */
let seen: URL[] = [];

beforeEach(() => {
  seen = [];
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
  setToken('trk_test');
});

/**
 * Выдача, разложенная по статусам: по одной задаче на каждое значение перечисления
 * контракта. Набор строится из `TASK_STATUSES`, а не перечисляется здесь: тест доски
 * не должен знать список статусов лучше, чем сгенерированный клиент.
 */
function tasksForEveryStatus() {
  return TASK_STATUSES.map((status, index) => task(`DEMO-${index + 1}`, { status }));
}

/**
 * Подмена списка задач: отвечает по параметрам запроса, как настоящий бэкенд.
 *
 * Общий ответ на все запросы здесь не годится: столбцы различаются только отбором
 * по статусу, и один ответ на всех показал бы каждую задачу в каждом столбце.
 */
function listing(items = tasksForEveryStatus()) {
  return http.get(`${API}/api/v1/tasks`, ({ request }) => {
    const url = new URL(request.url);
    seen.push(url);
    return taskListing(url, items);
  });
}

/** Запросы одного столбца: те, что спрашивали его статус. */
function requestsFor(status: string): URL[] {
  return seen.filter((url) => url.searchParams.getAll('status').includes(status));
}

/** Запросы за карточками: у запроса за одним лишь числом размер страницы — единица. */
function readRequests(): URL[] {
  return seen.filter((url) => url.searchParams.get('limit') !== '1');
}

function column(status: string) {
  return screen.getByRole('region', { name: status });
}

describe('доска', () => {
  it('знак статуса стоит в заголовке столбца, а приоритет карточки назван родом', async () => {
    server.use(listing([task('DEMO-9', { status: 'open', priority: 'critical' })]));

    renderApp('/tasks?project=DEMO&view=board');

    // Тот же словарь форм, что в списке и на карточке (решение Д20).
    const open = await screen.findByRole('region', { name: 'open' });
    expect(open).toHaveTextContent(`${say.ui('task.statusLabel')} open`);

    // На карточке подписи для приоритета нет — места нет, — но значение не пропало:
    // оно ушло в доступное имя.
    const card = await within(open).findByRole('article');
    expect(card).toHaveTextContent(`${say.ui('task.priorityLabel')} critical`);
  });

  it('раскладывает задачи по столбцу на каждое значение статуса из контракта', async () => {
    server.use(listing());

    renderApp('/tasks?project=DEMO&view=board');

    await screen.findByRole('region', { name: TASK_STATUSES[0] as string });

    for (const [index, status] of TASK_STATUSES.entries()) {
      const key = `DEMO-${index + 1}`;
      const section = column(status);
      // Свёрнутый столбец карточек не показывает: разворачиваем и проверяем содержимое.
      // Спрашивается именно раскрытие, а не наличие карточки: столбец читает своё
      // сам, и «карточки ещё нет» означает «не дочитали», а не «свёрнут».
      const toggle = within(section).getByRole('button');
      if (toggle.getAttribute('aria-expanded') === 'false') {
        await userEvent.setup().click(toggle);
      }
      // Ссылка на карточке одна, и она на названии: ключ перестал быть единственной
      // мишенью, а вести в задачу стала вся карточка (`task-card.tsx`).
      expect(await within(section).findByRole('link', { name: `Задача ${key}` })).toHaveAttribute(
        'href',
        `/tasks/${key}`,
      );
      expect(within(section).getByText(key)).toBeInTheDocument();
    }
  });

  it('на отрисовку доски уходит по запросу на столбец и один на число выдачи', async () => {
    server.use(listing());

    renderApp('/tasks?project=DEMO&view=board');
    await screen.findByRole('region', { name: 'open' });
    await waitFor(() => expect(seen).toHaveLength(TASK_STATUSES.length + 1));

    // Раскрытый столбец читает карточки, свёрнутый — только своё число, и лишнего
    // запроса нет ни у одного: `done` и `cancelled` свёрнуты по умолчанию.
    for (const status of ['done', 'cancelled']) {
      const asked = requestsFor(status);
      expect(asked).toHaveLength(1);
      expect((asked[0] as URL).searchParams.get('limit')).toBe('1');
    }
    for (const status of ['backlog', 'open', 'in_progress', 'waiting']) {
      const asked = requestsFor(status);
      expect(asked).toHaveLength(1);
      expect((asked[0] as URL).searchParams.get('limit')).toBe(String(TASK_COLUMN_PAGE_SIZE));
    }

    // Число выдачи спрашивается без задач и ровно один раз: столбцам оно неизвестно —
    // свёрнутый не читает вовсе, а сложить шесть чисел значило бы считать за бэкенд.
    const whole = seen.filter((url) => url.searchParams.getAll('status').length === 0);
    expect(whole).toHaveLength(1);
    expect((whole[0] as URL).searchParams.get('limit')).toBe('1');
  });

  it('родителя карточки приносит выдача столбца: запросов столько же, на родителя — ни одного', async () => {
    const asked: string[] = [];
    server.use(
      listing([
        task('DEMO-5', {
          status: 'backlog',
          parent: { key: 'DEMO-2', title: 'Лента журнала теряет записи' },
        }),
        task('DEMO-3', { status: 'open' }),
      ]),
      http.get(`${API}/api/v1/tasks/:key`, ({ request }) => {
        asked.push(request.url);
        return failure('task_not_found', 404);
      }),
    );

    renderApp('/tasks?project=DEMO&view=board');

    const child = await within(column('backlog')).findByRole('article');
    expect(within(child).getByRole('link', { name: /DEMO-2/ })).toHaveAttribute(
      'href',
      '/tasks/DEMO-2',
    );
    const top = await within(column('open')).findByRole('article');
    expect(within(top).getAllByRole('link')).toHaveLength(1);

    // Столько же запросов, сколько до UI-119: по одному на столбец и один на число.
    await waitFor(() => expect(seen).toHaveLength(TASK_STATUSES.length + 1));
    // Карточки читаются с родителями в наборе полей — тем же запросом, что и столбец.
    for (const url of readRequests()) {
      expect(url.searchParams.getAll('fields')).toContain('parent');
    }
    expect(asked).toEqual([]);
  });

  it('закрытые и отменённые свёрнуты и показывают число, клик раскрывает', async () => {
    server.use(listing());
    renderApp('/tasks?project=DEMO&view=board');

    await screen.findByRole('region', { name: 'done' });
    const done = column('done');

    const toggle = within(done).getByRole('button');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    // Число у свёрнутого столбца — от бэкенда, а не от прочитанного: карточек он
    // не читал ни одной.
    await waitFor(() => expect(toggle).toHaveTextContent('1'));
    expect(within(done).queryByRole('link')).not.toBeInTheDocument();

    await userEvent.setup().click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(await within(done).findByRole('link')).toBeInTheDocument();
  });

  it('статус отбора на доску не уходит: столбец спрашивает только свой', async () => {
    server.use(listing());

    renderApp('/tasks?project=DEMO&view=board&status=open&assignee=owner&sort=key');
    await screen.findByRole('region', { name: 'open' });
    await waitFor(() => expect(seen).toHaveLength(TASK_STATUSES.length + 1));

    for (const url of seen) {
      // Ни один запрос не несёт чужого статуса: у столбца стоит его собственный,
      // у числа выдачи — никакого. Условие человека сюда не попадает вовсе, иначе
      // пять столбцов из шести оказались бы пустыми, притворяясь честными.
      expect(url.searchParams.getAll('status').length).toBeLessThanOrEqual(1);
      // Исполнитель — общий фильтр, он действует и на доске.
      expect(url.searchParams.getAll('assignee')).toEqual(['owner']);
      // Порядок тот же, что выбран в таблице: он упорядочивает карточки внутри
      // столбца (UI-130#10), а не подменяется порядком доски.
      expect(url.searchParams.getAll('sort')).toEqual(['key']);
    }
    expect(requestsFor('open')).toHaveLength(1);
  });

  it('переключение в таблицу сохраняет отбор и меняет адрес', async () => {
    server.use(listing());
    renderApp('/tasks?project=DEMO&view=board&assignee=owner');
    await screen.findByRole('region', { name: 'open' });

    const user = userEvent.setup();
    await user.click(screen.getByRole('link', { name: say.tasks('view.table') }));

    expect(await screen.findByRole('table')).toBeInTheDocument();
    const request = seen.at(-1) as URL;
    expect(request.searchParams.getAll('assignee')).toEqual(['owner']);

    // Отбор пережил смену режима: строка состояния называет его чипом.
    expect(screen.getByRole('list', { name: say.tasks('filters.conditions') })).toHaveTextContent(
      say.tasks('filters.condition.assignee', { value: 'owner' }),
    );
  });
});

/** Длинный столбец: страниц в нём заведомо больше двух. */
const LONG = Array.from({ length: TASK_COLUMN_PAGE_SIZE * 2 + 3 }, (_, index) =>
  task(`DEMO-${index + 1}`, { status: 'open' }),
);

describe('дочитывание столбца', () => {
  it('столбец рисует первую страницу, а остальное приносит прокрутка', async () => {
    server.use(listing(LONG));

    renderApp('/tasks?project=DEMO&view=board');
    const open = await screen.findByRole('region', { name: 'open' });

    // Сразу после отрисовки в разметке ровно страница, а не вся выдача, — при том
    // что число в заголовке названо полное и честное.
    await waitFor(() =>
      expect(within(open).getAllByRole('article')).toHaveLength(TASK_COLUMN_PAGE_SIZE),
    );
    expect(within(open).getByRole('button')).toHaveTextContent(String(LONG.length));
    expect(requestsFor('open')).toHaveLength(1);

    // Докрутили до конца столбца — пришла следующая страница. Ни одного нажатия.
    await reachEnd();
    await waitFor(() =>
      expect(within(open).getAllByRole('article')).toHaveLength(TASK_COLUMN_PAGE_SIZE * 2),
    );

    await reachEnd();
    await waitFor(() => expect(within(open).getAllByRole('article')).toHaveLength(LONG.length));

    // Столько запросов, сколько страниц: лишних дочитываний нет.
    expect(requestsFor('open')).toHaveLength(3);
    expect((requestsFor('open')[2] as URL).searchParams.get('cursor')).toBe(
      String(TASK_COLUMN_PAGE_SIZE * 2),
    );
  });

  it('дочитанный столбец сторожа снимает: спрашивать больше нечего', async () => {
    server.use(listing([task('DEMO-1', { status: 'open' })]));

    renderApp('/tasks?project=DEMO&view=board');
    const open = await screen.findByRole('region', { name: 'open' });
    await within(open).findByRole('article');

    // Столбец короче страницы — наблюдателя над ним нет вовсе, и сколько бы раз
    // сторож ни показался, запроса не будет: циклу начаться неоткуда.
    expect(watched()).toEqual([]);
    const before = readRequests().length;
    await reachEnd();
    expect(readRequests()).toHaveLength(before);
  });

  it('дочитывание названо словами, а отказ виден и чинится повтором', async () => {
    let attempt = 0;
    server.use(
      http.get(`${API}/api/v1/tasks`, ({ request }) => {
        const url = new URL(request.url);
        seen.push(url);
        if (url.searchParams.get('cursor') === null) return taskListing(url, LONG);
        attempt += 1;
        // Первая попытка дочитать — отказ, вторая (по кнопке) — страница.
        return attempt === 1 ? failure('internal_error', 500) : taskListing(url, LONG);
      }),
    );

    renderApp('/tasks?project=DEMO&view=board');
    const open = await screen.findByRole('region', { name: 'open' });
    await waitFor(() =>
      expect(within(open).getAllByRole('article')).toHaveLength(TASK_COLUMN_PAGE_SIZE),
    );

    await reachEnd();

    // Отказ сказан словами, а не оборванной подгрузкой; прочитанное осталось на месте.
    expect(await within(open).findByText(say.errors('internal_error'))).toBeInTheDocument();
    expect(within(open).getAllByRole('article')).toHaveLength(TASK_COLUMN_PAGE_SIZE);

    // И сторож снят: пока отказ не разобран, столбец сам не спрашивает — иначе
    // отказ и новый запрос гонялись бы друг за другом в каждом кадре.
    expect(watched()).toEqual([]);

    await userEvent
      .setup()
      .click(within(open).getByRole('button', { name: say.ui('query.retry') }));

    await waitFor(() =>
      expect(within(open).getAllByRole('article')).toHaveLength(TASK_COLUMN_PAGE_SIZE * 2),
    );
    expect(within(open).queryByText(say.errors('internal_error'))).not.toBeInTheDocument();
  });

  it('столбец, которого не прочитали вовсе, говорит об этом словами', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks`, ({ request }) => {
        const url = new URL(request.url);
        seen.push(url);
        return url.searchParams.getAll('status').includes('open')
          ? failure('internal_error', 500)
          : taskListing(url, tasksForEveryStatus());
      }),
    );

    renderApp('/tasks?project=DEMO&view=board');
    const open = await screen.findByRole('region', { name: 'open' });

    // Пустой столбец и непрочитанный — разные беды, и путать их нельзя: у первого
    // сказано «Пусто», у второго — что случилось, и рядом кнопка повтора.
    expect(await within(open).findByText(say.errors('internal_error'))).toBeInTheDocument();
    expect(within(open).queryByText(say.tasks('board.empty'))).not.toBeInTheDocument();
    expect(within(open).getByRole('button', { name: say.ui('query.retry') })).toBeInTheDocument();

    // Соседний столбец своё прочитал: отказ одного не гасит доску.
    expect(await within(column('waiting')).findByRole('article')).toBeInTheDocument();
  });
});
