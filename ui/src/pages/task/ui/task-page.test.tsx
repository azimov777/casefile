import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { act, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { liveJournal } from '@testing/live-journal';
import {
  API,
  answerEntry,
  bootstrap,
  collection,
  data,
  failure,
  questionEntry,
  taskPackage,
  verdictEntry,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { setToken } from '@/shared/api';

/** Адреса всех запросов прогона: по ним видно, что лишних не было. */
let seen: string[] = [];

beforeEach(() => {
  seen = [];
  server.use(http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())));
  setToken('trk_test');
});

function packageOf(key: string, overrides = {}) {
  return http.get(`${API}/api/v1/tasks/${key}`, ({ request }) => {
    seen.push(request.url);
    return data(taskPackage(key, overrides));
  });
}

/** Тела записей: подмена отдаёт ровно то, что попросили номерами. */
function entries(key: string) {
  return http.get(`${API}/api/v1/tasks/${key}/entries`, ({ request }) => {
    seen.push(request.url);
    const nos = new URL(request.url).searchParams.getAll('nos').map(Number);
    return collection(nos.map((no) => verdictEntry(no, key)));
  });
}

function entriesCalls() {
  return seen.filter((url) => url.includes('/entries'));
}

describe('карточка задачи', () => {
  it('рисуется одним запросом пакета, без запросов за телами записей', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));

    renderApp('/tasks/DEMO-6');

    const heading = await screen.findByRole('heading', { name: /DEMO-6/ });
    // Статус ищется в шапке: тот же `in_progress` стоит и у задачи на другом конце связи.
    const header = heading.closest('header') as HTMLElement;
    expect(within(header).getByText('in_progress')).toBeInTheDocument();
    expect(within(header).getByText('заблокирована')).toBeInTheDocument();

    // Признак «заблокирована» подкреплён связью: видно, кто именно держит.
    const links = screen.getByRole('heading', { name: 'Связи' }).closest('section');
    expect(within(links as HTMLElement).getByRole('link', { name: 'DEMO-2' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-2',
    );

    // Сводка четырьмя частями — целиком, без клика.
    const summary = screen.getByRole('heading', { name: 'Последняя сводка' }).closest('section');
    for (const part of ['Сделано', 'Осталось', 'Что мешает', 'Следующий шаг']) {
      expect(within(summary as HTMLElement).getByText(part)).toBeInTheDocument();
    }

    expect(screen.getByText('Записей в деле: 7')).toBeInTheDocument();
    expect(seen).toHaveLength(1);
    expect(entriesCalls()).toEqual([]);
  });

  it('клик по записи описи читает одну запись и показывает её по типу', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));
    renderApp('/tasks/DEMO-6');

    await userEvent
      .setup()
      .click(await screen.findByRole('button', { name: 'Verdict on check 2: failed' }));

    const opened = (await screen.findByText('Проверка 2')).closest('td') as HTMLElement;
    expect(within(opened).getByText('failed')).toBeInTheDocument();
    // Текст проверки берётся из `checks` задачи по номеру: в самой записи его нет,
    // поэтому ищем именно в раскрытой записи, а не в разделе «Обзорные проверки».
    expect(within(opened).getByText('Неприменимый оператор отвечает списком')).toBeInTheDocument();
    // Тело записи — markdown: `details.allowed` уехало в `code`, ключи задач — в ссылки,
    // поэтому текст ищется по содержимому целиком, а не одним узлом.
    expect(opened).toHaveTextContent('details.allowed');
    expect(opened).toHaveTextContent('пуст');

    const calls = entriesCalls();
    expect(calls).toHaveLength(1);
    expect(new URL(calls[0] as string).searchParams.getAll('nos')).toEqual(['6']);
  });

  it('открытый блокирующий вопрос показан целиком, без клика', async () => {
    server.use(
      packageOf('DEMO-4', {
        questions: [questionEntry(5, 'DEMO-4')],
        features: {
          blocked: false,
          open_questions: 1,
          open_blocking_questions: 1,
          last_summary_at: null,
        },
      }),
      entries('DEMO-4'),
    );

    renderApp('/tasks/DEMO-4');

    const questions = (await screen.findByRole('heading', { name: 'Открытые вопросы' })).closest(
      'section',
    );
    expect(within(questions as HTMLElement).getByText('блокирующий')).toBeInTheDocument();
    expect(within(questions as HTMLElement).getByText('owner')).toBeInTheDocument();
    expect(within(questions as HTMLElement).getByText(/Хранение стоит денег/)).toBeInTheDocument();
    expect(entriesCalls()).toEqual([]);
  });

  it('ответ на вопрос из карточки подтверждается на месте, и кадр потока этого не отменяет', async () => {
    // Второе место показа формы, кроме входящей. Проверяется тем же способом и по той
    // же причине: перечитанный пакет приходит без отвеченного вопроса, и подтверждению
    // негде было бы жить, будь оно внутри строки списка.
    let answered = false;
    let release = () => {};
    const posts: string[] = [];

    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-4`, () =>
        data(taskPackage('DEMO-4', { questions: answered ? [] : [questionEntry(4, 'DEMO-4')] })),
      ),
      http.post(`${API}/api/v1/tasks/DEMO-4/entries`, ({ request }) => {
        posts.push(request.url);
        answered = true;
        return new Promise((resolve) => {
          release = () =>
            resolve(data(answerEntry(9, 'DEMO-4', 4, 'Храним вечно: дело неизменяемо.'), 201));
        });
      }),
    );

    const user = userEvent.setup();
    renderApp('/tasks/DEMO-4');

    // На карточке форма раскрыта сразу: сюда приходят, уже решив отвечать.
    await user.type(await screen.findByLabelText('Ответ'), 'Храним вечно: дело неизменяемо.');
    await user.click(screen.getByRole('button', { name: 'Ответить' }));
    await waitFor(() => expect(posts).toHaveLength(1));

    // Кадр обгоняет ответ сервера: пакет перечитан и пришёл уже без вопроса.
    act(() => liveJournal.send({ ...answerEntry(9, 'DEMO-4', 4, 'Храним вечно.'), seq: 1050 }));
    release();

    const receipt = await screen.findByRole('region', { name: 'Ответ на DEMO-4#4 подшит' });
    expect(within(receipt).getByRole('link', { name: 'DEMO-4#9' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-4?entry=9',
    );
    expect(posts).toHaveLength(1);
  });

  it('ссылка на запись в теле раскрывает её, ссылка на задачу ведёт на карточку', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'), packageOf('DEMO-2'));
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    await user.click(await screen.findByRole('button', { name: 'Verdict on check 2: failed' }));
    await screen.findByText('Проверка 2');

    // `DEMO-6#4` в тексте записи — ссылка на запись 4 той же задачи.
    await user.click(screen.getByRole('link', { name: 'DEMO-6#4' }));
    expect(
      await screen.findByText('Список допустимого собирается по типу поля', { selector: 'p' }),
    ).toBeInTheDocument();

    // `DEMO-2` — ссылка на другую задачу.
    await user.click(screen.getAllByRole('link', { name: 'DEMO-2' })[0] as HTMLElement);
    expect(await screen.findByRole('heading', { name: /DEMO-2/ })).toBeInTheDocument();
  });

  it('адрес с номером записи открывает карточку уже раскрытой', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));

    renderApp('/tasks/DEMO-6?entry=6');

    expect(await screen.findByText('Проверка 2')).toBeInTheDocument();
    const calls = entriesCalls();
    expect(calls).toHaveLength(1);
    expect(new URL(calls[0] as string).searchParams.getAll('nos')).toEqual(['6']);
  });

  it('обзорные проверки нумерованы с единицы, как их считает вердикт', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));
    renderApp('/tasks/DEMO-6');

    const checks = (await screen.findByRole('heading', { name: 'Обзорные проверки' })).closest(
      'section',
    );
    const list = within(checks as HTMLElement).getByRole('list');
    expect(list.tagName).toBe('OL');
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(list).toHaveTextContent('Незнакомое поле отвечает списком допустимых');
  });

  it('на несуществующей задаче объясняет по коду и зовёт обратно к списку', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-999`, () =>
        failure('task_not_found', 404, 'Task not found'),
      ),
    );

    renderApp('/tasks/DEMO-999');

    expect(await screen.findByText(/Задачи с таким ключом нет/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Вернуться к списку задач' })).toHaveAttribute(
      'href',
      '/tasks',
    );
  });
});
