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
  heading,
  questionEntry,
  remarkEntry,
  taskDetails,
  taskPackage,
  verdictEntry,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
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
  it('в описи род записи виден знаком, а тип по-прежнему назван словом контракта', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));

    renderApp('/tasks/DEMO-6');
    await screen.findByRole('heading', { name: /DEMO-6/ });

    const kinds = ['created', 'status_changed', 'decision', 'verdict', 'summary'];
    const shapes = kinds.map((type) => {
      const mark = screen.getAllByText(type)[0]?.closest('[data-mark="kind"]');
      expect(mark, `у записи ${type} нет знака рода`).not.toBeNull();
      return (mark as HTMLElement).querySelector('svg')?.innerHTML ?? '';
    });

    // Пять родов — пять разных рисунков: в описи их по двадцать подряд, и без
    // знака `verdict` от `section_changed` отличается только чтением слова.
    expect(new Set(shapes).size).toBe(kinds.length);

    // Идентификатор контракта остаётся на месте: он тот же, что видит агент.
    for (const type of kinds) expect(screen.getAllByText(type)[0]).toBeInTheDocument();
  });

  it('в шапке статус и приоритет названы родом: четыре плашки расслоились', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));

    renderApp('/tasks/DEMO-6');

    const heading = await screen.findByRole('heading', { name: /DEMO-6/ });
    const header = heading.closest('header') as HTMLElement;

    // Знак несёт форму, род значения — текстом рядом: без него диктор читал бы
    // подряд четыре значения и не сказал бы, что из них чем является (решение Д7).
    expect(header).toHaveTextContent('статус in_progress');
    expect(header).toHaveTextContent('приоритет normal');
  });

  it('рисуется одним запросом пакета, без запросов за телами записей', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));

    renderApp('/tasks/DEMO-6');

    const heading = await screen.findByRole('heading', { name: /DEMO-6/ });
    // Статус ищется в шапке: тот же `in_progress` стоит и у задачи на другом конце связи.
    const header = heading.closest('header') as HTMLElement;
    expect(within(header).getByText('in_progress')).toBeInTheDocument();
    expect(within(header).getByText(/^заблокирована/)).toBeInTheDocument();

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
      .click(await screen.findByRole('button', { name: /Обзорная проверка 2/ }));

    // Номер проверки и исход называет строка описи — заголовок собран по фактам.
    const line = screen.getByRole('button', { name: /Обзорная проверка 2/ });
    expect(line).toHaveTextContent('failed');

    // Текст проверки берётся из `checks` задачи по номеру: в самой записи его нет,
    // поэтому ищем именно в раскрытой записи, а не в разделе «Обзорные проверки».
    // Ищем в пределах описи: тот же текст проверки стоит и в разделе «Обзорные
    // проверки» задачи, и поиск по всей странице нашёл бы оба.
    const index = screen.getByRole('table', { name: /Записей в деле/ });
    const opened = (
      await within(index).findByText('Неприменимый оператор отвечает списком')
    ).closest('td') as HTMLElement;
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
    // Адрес называет вопрос — так сюда приводит уведомление и ссылка из входящей,
    // и форма раскрыта сразу, без лишнего клика между «меня спросили» и «отвечаю».
    renderApp('/tasks/DEMO-4?entry=4');

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

    await user.click(await screen.findByRole('button', { name: /Обзорная проверка 2/ }));
    await within(screen.getByRole('table', { name: /Записей в деле/ })).findByText(
      'Неприменимый оператор отвечает списком',
    );

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

    // Таблицы описи ещё нет в первый кадр: пакет только загружается.
    const index = await screen.findByRole('table', { name: /Записей в деле/ });
    expect(
      await within(index).findByText('Неприменимый оператор отвечает списком'),
    ).toBeInTheDocument();
    const calls = entriesCalls();
    expect(calls).toHaveLength(1);
    expect(new URL(calls[0] as string).searchParams.getAll('nos')).toEqual(['6']);
  });

  it('раскрытие записи в описи уходит в адрес, и перезагрузка возвращает её раскрытой', async () => {
    server.use(packageOf('DEMO-4'), entries('DEMO-4'));
    const user = userEvent.setup();
    const { unmount } = renderApp('/tasks/DEMO-4');

    const heading = await screen.findByRole('button', {
      name: /Список допустимого собирается по типу поля/,
    });
    await user.click(heading);

    // Раньше клик и ссылка делали одно и то же двумя разными способами: ссылка
    // меняла адрес, клик — нет, и перезагрузка теряла раскрытое.
    await waitFor(() => expect(address.current).toBe('/tasks/DEMO-4?entry=4'));

    // Перезагрузка по этому адресу: запись раскрыта сразу, без второго клика.
    unmount();
    renderApp('/tasks/DEMO-4?entry=4');
    expect(
      await screen.findByRole('button', { name: /Список допустимого собирается по типу поля/ }),
    ).toHaveAttribute('aria-expanded', 'true');
  });

  it('в длинной описи «К свежей записи» раскрывает последнюю и читает только её', async () => {
    // Опись из двадцати записей: короткая видна целиком, и прыгать по ней незачем.
    const long = Array.from({ length: 20 }, (_, at) =>
      heading(at + 1, 'decision', `Решение номер ${at + 1}`),
    );
    server.use(packageOf('DEMO-4', { index: long }), entries('DEMO-4'));
    const user = userEvent.setup();

    renderApp('/tasks/DEMO-4');
    await screen.findByRole('table', { name: /Записей в деле/ });

    await user.click(screen.getByRole('button', { name: 'К свежей записи' }));

    // Последняя запись описи раскрыта, и её номер уехал в адрес: перезагрузка
    // вернёт человека туда же.
    await waitFor(() => expect(address.current).toBe('/tasks/DEMO-4?entry=20'));
    expect(screen.getByRole('button', { name: /Решение номер 20/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );

    // Прочитана ровно одна запись — двадцатая. Тел с первого по девятнадцатое
    // ради этого перехода никто не спрашивал.
    const calls = entriesCalls();
    expect(calls).toHaveLength(1);
    expect(new URL(calls[0] as string).searchParams.getAll('nos')).toEqual(['20']);
  });

  it('в короткой описи прыжков нет: она и так видна целиком', async () => {
    server.use(packageOf('DEMO-4'), entries('DEMO-4'));

    renderApp('/tasks/DEMO-4');
    await screen.findByRole('table', { name: /Записей в деле/ });

    expect(screen.queryByRole('button', { name: 'К свежей записи' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'В начало описи' })).not.toBeInTheDocument();
  });

  it('закрытие названной записи убирает её номер из адреса', async () => {
    server.use(packageOf('DEMO-4'), entries('DEMO-4'));
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-4?entry=4');

    const heading = await screen.findByRole('button', {
      name: /Список допустимого собирается по типу поля/,
    });
    expect(heading).toHaveAttribute('aria-expanded', 'true');

    await user.click(heading);
    await waitFor(() => expect(address.current).toBe('/tasks/DEMO-4'));
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

  it('в шапке четыре рода значений различаются формой, а не подписью внутри плашки', async () => {
    server.use(packageOf('DEMO-4'));
    renderApp('/tasks/DEMO-4');

    const heading = await screen.findByRole('heading', { name: /DEMO-4/ });
    const header = heading.closest('header') as HTMLElement;

    // Статус и приоритет — знаки со своей формой (решение Д7), и род остаётся
    // слышен диктору.
    expect(header).toHaveTextContent(/статус\s+in_progress/);
    expect(header).toHaveTextContent(/приоритет\s+\S+/);

    // Исполнитель — имя с аватаром, а не плашка: это единственная строка про
    // человека, и плашка уравнивала её со статусом и тегом.
    expect(header).toHaveTextContent(/исполнитель\s+\S+/);

    // Теги — список с общим именем, а не набор плашек, каждая со словом «тег».
    const tags = within(header).getByRole('list', { name: 'Теги' });
    expect(within(tags).getAllByRole('listitem').length).toBeGreaterThan(0);
  });

  it('возможные переходы остаются справкой: ни роли, ни фокуса', async () => {
    server.use(packageOf('DEMO-4'));
    renderApp('/tasks/DEMO-4');

    const transitions = await screen.findByText('done, open, cancelled');
    // Переходы человек не делает (`CONCEPT.md`, 7): это текст, а не кнопки.
    expect(transitions.tagName).toBe('DD');
    expect(transitions.querySelector('button, a, [tabindex]')).toBeNull();
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

describe('порядок чтения карточки', () => {
  it('замечания идут до описи дела, а действие стоит в липкой навигации', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));
    renderApp('/tasks/DEMO-6');
    await screen.findByRole('heading', { name: 'Замечания' });

    // Порядок разметки и есть порядок чтения: Tab и программа чтения с экрана идут
    // по нему, а не по тому, как блоки расставлены на широком экране.
    const order = Array.from(document.querySelectorAll('main section[aria-labelledby]')).map(
      (node) => node.getAttribute('aria-labelledby'),
    );
    expect(order.indexOf('remarks')).toBeLessThan(order.indexOf('case'));
    expect(order.indexOf('summary')).toBeLessThan(order.indexOf('remarks'));

    // Кнопка одна и живёт в навигации: второго пути к форме нет.
    const nav = screen.getByRole('navigation', { name: /Навигация по задаче/ });
    expect(within(nav).getByRole('button', { name: 'Оставить замечание' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Оставить замечание' })).toHaveLength(1);
  });
});

describe('замечание к задаче', () => {
  /** Карточка с замечаниями и подменённой отправкой: считаем, сколько раз её позвали. */
  function withRemarks(overrides = {}) {
    const posts: { key: string | null; body: unknown }[] = [];
    let filed = false;

    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-6`, () =>
        data(
          taskPackage('DEMO-6', {
            remarks: filed ? [remarkEntry(8, 'DEMO-6'), remarkEntry(9, 'DEMO-6', 'Ещё одно')] : [],
            features: {
              blocked: false,
              open_questions: 0,
              open_blocking_questions: 0,
              open_remarks: filed ? 2 : 0,
              last_summary_at: null,
              last_entry_at: null,
            },
            ...overrides,
          }),
        ),
      ),
      http.post(`${API}/api/v1/tasks/DEMO-6/entries`, async ({ request }) => {
        posts.push({ key: request.headers.get('Idempotency-Key'), body: await request.json() });
        filed = true;
        return data(remarkEntry(9, 'DEMO-6', 'Ещё одно'), 201);
      }),
    );

    return posts;
  }

  it('замечание подшивается с карточки, а подтверждение остаётся на экране', async () => {
    const posts = withRemarks();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    // Пока замечаний нет, блок занимает строку и не съедает первый экран.
    expect(await screen.findByText('Неразобранных замечаний нет.')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Оставить замечание' }));
    await user.type(screen.getByLabelText('Замечание'), 'Дыры в нумерации сбивают с толку.');
    await user.click(screen.getByRole('button', { name: 'Оставить замечание' }));

    const receipt = await screen.findByRole('region', { name: 'Замечание к DEMO-6 подшито' });
    expect(within(receipt).getByRole('link', { name: 'DEMO-6#9' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-6?entry=9',
    );

    // Заголовок записи выведен из первой строки текста: второго поля у формы нет.
    expect(posts).toHaveLength(1);
    expect(posts[0]?.key).toMatch(/^[0-9a-f-]{36}$/);
    expect(posts[0]?.body).toEqual({
      type: 'remark',
      title: 'Дыры в нумерации сбивают с толку.',
      body: 'Дыры в нумерации сбивают с толку.',
    });

    // Перечитанный пакет принёс замечания — они видны рядом с подтверждением.
    // Регуляркой: строка замечания собрана из ключа, номера и заголовка, и точное
    // совпадение искало бы её целиком.
    await waitFor(() => expect(screen.getByText(/Ещё одно/)).toBeInTheDocument());
    expect(screen.getByText('замечаний без разбора: 2')).toBeInTheDocument();
  });

  it('кадр живого потока обгоняет ответ сервера — подтверждение всё равно показано', async () => {
    const posts = withRemarks();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    await user.click(await screen.findByRole('button', { name: 'Оставить замечание' }));
    await user.type(screen.getByLabelText('Замечание'), 'Дыры в нумерации сбивают с толку.');
    await user.click(screen.getByRole('button', { name: 'Оставить замечание' }));

    // Кадр о той же записи перечитывает пакет. Форма замечания стоит вне списка,
    // поэтому переживает перечитывание — и своё подтверждение показывает сама.
    act(() => liveJournal.send({ ...remarkEntry(9, 'DEMO-6', 'Ещё одно'), seq: 2050 }));

    expect(
      await screen.findByRole('region', { name: 'Замечание к DEMO-6 подшито' }),
    ).toBeInTheDocument();
    // Второй записи кадр не породил: подшивку делает форма, а поток только перечитывает.
    expect(posts).toHaveLength(1);
  });

  it('на закрытой задаче форма есть, а переходов и правки разделов нет', async () => {
    withRemarks({ task: taskDetails('DEMO-6', { status: 'done' }), transitions: [] });
    renderApp('/tasks/DEMO-6');

    expect(await screen.findByRole('button', { name: 'Оставить замечание' })).toBeInTheDocument();
    // Роль человека не расширяется (`CONCEPT.md`, 7): статусы двигают агенты.
    for (const name of [/перевести/i, /изменить статус/i, /править/i, /редактировать/i]) {
      expect(screen.queryByRole('button', { name })).toBeNull();
    }
    expect(screen.queryByRole('textbox', { name: 'Цель' })).toBeNull();
  });

  it('черновик переживает уход со страницы и отказ отправки', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-6`, () => data(taskPackage('DEMO-6', { remarks: [] }))),
      http.get(`${API}/api/v1/tasks`, () => collection([])),
      http.post(`${API}/api/v1/tasks/DEMO-6/entries`, () => failure('internal_error', 500, 'Boom')),
    );
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    await user.click(await screen.findByRole('button', { name: 'Оставить замечание' }));
    await user.type(screen.getByLabelText('Замечание'), 'Недописанное замечание');

    // Отказ сети текст не уносит: повторять набранное человек не должен.
    await user.click(screen.getByRole('button', { name: 'Оставить замечание' }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText('Замечание')).toHaveValue('Недописанное замечание');

    // Уход на список и возврат — тоже: черновик живёт в хранилище сеанса.
    await user.click(screen.getByRole('link', { name: 'Все задачи' }));
    await screen.findByRole('heading', { name: 'Задачи' });
    renderApp('/tasks/DEMO-6');

    await user.click((await screen.findAllByRole('button', { name: 'Оставить замечание' }))[0]!);
    expect(screen.getAllByLabelText('Замечание')[0]).toHaveValue('Недописанное замечание');
  });
});
