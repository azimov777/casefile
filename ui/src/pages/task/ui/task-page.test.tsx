import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { act, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
import { say } from '@testing/say';
import type { TaskLink } from '@/entities/task';
import { setToken, type components } from '@/shared/api';
import { currentLanguage } from '@/shared/i18n';
import { exactTime } from '@/shared/lib';

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
    // С UI-143 род назван видимой подписью `dt` полосы свойств, а не скрытым текстом.
    const valueOf = (label: string) =>
      within(header)
        .getAllByRole('term')
        .find((term) => term.textContent === label)?.nextElementSibling?.textContent;
    expect(valueOf(say.task('header.status'))).toBe('in_progress');
    expect(valueOf(say.task('header.priority'))).toBe('normal');
  });

  it('точное время создания открывается нажатием, без наведения, и тем же нажатием прячется (UI-153)', async () => {
    const user = userEvent.setup();
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));

    renderApp('/tasks/DEMO-6');
    const heading = await screen.findByRole('heading', { name: /DEMO-6/ });
    const header = heading.closest('header') as HTMLElement;

    // Время создания — кнопка в своей строке шапки: на телефоне наведения нет, и
    // подсказка `title` одна до точного времени не довела бы.
    const created = within(header).getByText(say.task('header.created'))
      .parentElement as HTMLElement;
    const time = within(created).getByRole('button');
    const stamp = (time.querySelector('time') as HTMLElement).getAttribute('dateTime') as string;
    const exact = exactTime(stamp, currentLanguage());
    expect(exact).not.toBe('');
    expect(time).toHaveAttribute('aria-pressed', 'false');
    expect(time).not.toHaveTextContent(exact);

    await user.click(time);
    expect(time).toHaveAttribute('aria-pressed', 'true');
    expect(time).toHaveTextContent(exact);

    await user.click(time);
    expect(time).toHaveAttribute('aria-pressed', 'false');
    expect(time).not.toHaveTextContent(exact);

    // С клавиатуры то же: фокус на времени и Enter.
    time.focus();
    await user.keyboard('{Enter}');
    expect(time).toHaveTextContent(exact);
  });

  it('рисуется одним запросом пакета, без запросов за телами записей', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));

    renderApp('/tasks/DEMO-6');

    const heading = await screen.findByRole('heading', { name: /DEMO-6/ });
    // Статус ищется в шапке: тот же `in_progress` стоит и у задачи на другом конце связи.
    const header = heading.closest('header') as HTMLElement;
    expect(within(header).getByText('in_progress')).toBeInTheDocument();
    expect(within(header).getByText(say.ui('task.features.blocked'))).toBeInTheDocument();

    // Признак «заблокирована» подкреплён связью: видно, кто именно держит.
    const links = screen.getByRole('heading', { name: say.task('links') }).closest('section');
    expect(within(links as HTMLElement).getByRole('link', { name: 'DEMO-2' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-2',
    );

    // Сводка четырьмя частями — целиком, без клика.
    const summary = screen.getByRole('heading', { name: say.task('summary') }).closest('section');
    for (const part of [
      say.ui('entry.summary.done'),
      say.ui('entry.summary.remaining'),
      say.ui('entry.summary.blockers'),
      say.ui('entry.summary.nextStep'),
    ]) {
      expect(within(summary as HTMLElement).getByText(part)).toBeInTheDocument();
    }

    expect(screen.getByText(say.task('index.count', { count: 7 }))).toBeInTheDocument();
    expect(seen).toHaveLength(1);
    expect(entriesCalls()).toEqual([]);
  });

  it('клик по записи описи читает одну запись и показывает её по типу', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));
    renderApp('/tasks/DEMO-6');

    const checkHeadline = new RegExp(say.ui('entry.headline.check', { no: 2 }));
    await userEvent.setup().click(await screen.findByRole('button', { name: checkHeadline }));

    // Номер проверки и исход называет строка описи — заголовок собран по фактам.
    const line = screen.getByRole('button', { name: checkHeadline });
    expect(line).toHaveTextContent('failed');

    // Текст проверки берётся из `checks` задачи по номеру: в самой записи его нет,
    // поэтому ищем именно в раскрытой записи, а не в разделе «Обзорные проверки».
    // Ищем в пределах описи: тот же текст проверки стоит и в разделе «Обзорные
    // проверки» задачи, и поиск по всей странице нашёл бы оба.
    const index = screen.getByRole('table', { name: say.task('index.count', { count: 7 }) });
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

    const questions = (await screen.findByRole('heading', { name: say.task('questions') })).closest(
      'section',
    );
    expect(
      within(questions as HTMLElement).getByText(say.ui('entry.blocking')),
    ).toBeInTheDocument();
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

    await user.type(
      await screen.findByLabelText(say.ui('answer.fieldLabel')),
      'Храним вечно: дело неизменяемо.',
    );
    await user.click(screen.getByRole('button', { name: say.ui('answer.submit') }));
    await waitFor(() => expect(posts).toHaveLength(1));

    // Кадр обгоняет ответ сервера: пакет перечитан и пришёл уже без вопроса.
    act(() => liveJournal.send({ ...answerEntry(9, 'DEMO-4', 4, 'Храним вечно.'), seq: 1050 }));
    release();

    const receipt = await screen.findByRole('region', {
      name: say.ui('answer.receiptLabel', { reference: 'DEMO-4#4' }),
    });
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

    await user.click(
      await screen.findByRole('button', {
        name: new RegExp(say.ui('entry.headline.check', { no: 2 })),
      }),
    );
    await within(
      screen.getByRole('table', { name: say.task('index.count', { count: 7 }) }),
    ).findByText('Неприменимый оператор отвечает списком');

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
    const index = await screen.findByRole('table', {
      name: say.task('index.count', { count: 7 }),
    });
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

  it('раскрытие и сворачивание записи кликом не прокручивает, а переход по адресу — прокручивает (UI-126)', async () => {
    server.use(packageOf('DEMO-4'), entries('DEMO-4'));
    const user = userEvent.setup();
    // В jsdom `scrollIntoView` — заглушка (`testing/setup.ts`); здесь она подменена
    // шпионом, чтобы отличить «не звали вовсе» от «позвали и он ничего не сделал».
    const scrollIntoView = vi
      .spyOn(Element.prototype, 'scrollIntoView')
      .mockImplementation(() => {});

    renderApp('/tasks/DEMO-4');
    const heading = await screen.findByRole('button', {
      name: /Список допустимого собирается по типу поля/,
    });

    // Раньше `scrollIntoView({ block: 'center' })` срабатывал на каждом клике: адрес
    // раскрытия и адрес перехода по ссылке `TRK-42#12` писались одним и тем же
    // параметром, и запись отличить было нечем.
    await user.click(heading);
    await waitFor(() => expect(address.current).toBe('/tasks/DEMO-4?entry=4'));
    expect(scrollIntoView).not.toHaveBeenCalled();

    // Закрытие той же записи — тот же путь и то же требование.
    await user.click(heading);
    await waitFor(() => expect(address.current).toBe('/tasks/DEMO-4'));
    expect(scrollIntoView).not.toHaveBeenCalled();

    scrollIntoView.mockRestore();
  });

  it('переход по адресу с номером записи по-прежнему прокручивает к ней (UI-126)', async () => {
    server.use(packageOf('DEMO-4'), entries('DEMO-4'));
    const scrollIntoView = vi
      .spyOn(Element.prototype, 'scrollIntoView')
      .mockImplementation(() => {});

    renderApp('/tasks/DEMO-4?entry=4');
    await screen.findByRole('button', {
      name: /Список допустимого собирается по типу поля/,
    });

    // Единственный оставшийся путь прокрутки: приход снаружи, не собственный клик.
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());

    scrollIntoView.mockRestore();
  });

  it('в длинной описи «К свежей записи» раскрывает последнюю и читает только её', async () => {
    // Опись из двадцати записей: короткая видна целиком, и прыгать по ней незачем.
    const long = Array.from({ length: 20 }, (_, at) =>
      heading(at + 1, { type: 'decision' }, `Решение номер ${at + 1}`),
    );
    server.use(packageOf('DEMO-4', { index: long }), entries('DEMO-4'));
    const user = userEvent.setup();

    renderApp('/tasks/DEMO-4');
    await screen.findByRole('table', { name: say.task('index.count', { count: 20 }) });

    await user.click(screen.getByRole('button', { name: say.task('index.toLatest') }));

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
    await screen.findByRole('table', { name: say.task('index.count', { count: 7 }) });

    expect(
      screen.queryByRole('button', { name: say.task('index.toLatest') }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: say.task('index.toTop') })).not.toBeInTheDocument();
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

    const checks = (
      await screen.findByRole('heading', { name: say.task('sections.checks') })
    ).closest('section');
    const list = within(checks as HTMLElement).getByRole('list');
    expect(list.tagName).toBe('OL');
    expect(within(list).getAllByRole('listitem')).toHaveLength(2);
    expect(list).toHaveTextContent('Незнакомое поле отвечает списком допустимых');
  });

  it('в шапке значения состояния и времени подписаны парами «подпись — значение» (UI-143)', async () => {
    server.use(packageOf('DEMO-4'));
    renderApp('/tasks/DEMO-4');

    const heading = await screen.findByRole('heading', { name: /DEMO-4/ });
    const header = heading.closest('header') as HTMLElement;

    // Полоса свойств — список определений: род значения назван видимой подписью `dt`,
    // значение — формой в `dd` (решение Д7 о формах остаётся).
    const pairs = Object.fromEntries(
      within(header)
        .getAllByRole('term')
        .map((term) => [term.textContent, term.nextElementSibling?.textContent ?? '']),
    );
    expect(pairs[say.task('header.status')]).toBe('in_progress');
    expect(pairs[say.task('header.priority')]).toMatch(/^\S+$/);
    expect(pairs[say.task('header.assignee')]).toMatch(/\S/);
    expect(pairs).toHaveProperty(say.task('header.updated'));
    expect(pairs).toHaveProperty(say.task('header.created'));

    // Скрытое «статус»/«приоритет» знака не повторяет видимую подпись: диктор не
    // читает род значения дважды.
    expect(header).not.toHaveTextContent(
      new RegExp(`${say.ui('task.statusLabel')}\\s+in_progress`),
    );
  });

  it('на несуществующей задаче объясняет по коду и зовёт обратно к списку', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-999`, () =>
        failure('task_not_found', 404, 'Task not found'),
      ),
    );

    renderApp('/tasks/DEMO-999');

    expect(await screen.findByText(say.task('missingText'))).toBeInTheDocument();
    expect(screen.getByRole('link', { name: say.task('backToList') })).toHaveAttribute(
      'href',
      '/tasks',
    );
  });
});

describe('пустые состояния сводки, вопросов и замечаний (UI-132)', () => {
  it('все три пустых сшиты в одну рамку, а не рисуют по своей на каждое', async () => {
    server.use(packageOf('DEMO-4', { summary: null }));
    renderApp('/tasks/DEMO-4');

    // Заголовки остаются на месте и честными: пустое состояние не молчит.
    await screen.findByText(say.task('noSummary'));
    expect(screen.getByText(say.task('noQuestions'))).toBeInTheDocument();
    expect(screen.getByText(say.task('noRemarks'))).toBeInTheDocument();

    // Три отдельных рамки исчезают (правило замены задачи): ни одна из трёх больше
    // не стоит собственной секцией `aria-labelledby`…
    expect(document.querySelector('section[aria-labelledby="summary"]')).toBeNull();
    expect(document.querySelector('section[aria-labelledby="questions"]')).toBeNull();
    expect(document.querySelector('section[aria-labelledby="remarks"]')).toBeNull();

    // …а их строки делят один и тот же общий контейнер.
    const summaryRow = screen.getByText(say.task('noSummary')).closest('div');
    const questionsRow = screen.getByText(say.task('noQuestions')).closest('div');
    const remarksRow = screen.getByText(say.task('noRemarks')).closest('div');
    const frame = summaryRow?.parentElement;
    expect(frame).not.toBeNull();
    expect(questionsRow?.parentElement).toBe(frame);
    expect(remarksRow?.parentElement).toBe(frame);
  });

  it('непустой блок между двумя пустыми остаётся своей секцией и не сшивает их через себя', async () => {
    server.use(
      packageOf('DEMO-4', {
        summary: null,
        questions: [questionEntry(5, 'DEMO-4')],
        features: {
          blocked: false,
          open_questions: 1,
          open_blocking_questions: 1,
          last_summary_at: null,
        },
      }),
    );
    renderApp('/tasks/DEMO-4');

    // Вопрос непуст — своя секция, заметность не падает: тело вопроса и форма ответа
    // видны без клика (та же проверка, что и без соседних пустых блоков).
    const questions = (await screen.findByRole('heading', { name: say.task('questions') })).closest(
      'section',
    );
    expect(questions).not.toBeNull();
    expect(questions?.getAttribute('aria-labelledby')).toBe('questions');

    // Сводка и замечания вокруг него остаются пустыми, но не соседями друг другу —
    // между ними стоит непустой блок вопросов, поэтому сшиваются только подряд идущие
    // пустые: сводка и замечания получают каждая свою (разную) рамку.
    expect(document.querySelector('section[aria-labelledby="summary"]')).toBeNull();
    expect(document.querySelector('section[aria-labelledby="remarks"]')).toBeNull();
    const summaryRow = screen.getByText(say.task('noSummary')).closest('div');
    const remarksRow = screen.getByText(say.task('noRemarks')).closest('div');
    expect(summaryRow?.parentElement).not.toBeNull();
    expect(summaryRow?.parentElement).not.toBe(remarksRow?.parentElement);
  });
});

describe('блок «Связи» (UI-125)', () => {
  const AUTHOR = { kind: 'agent', signature: 'demo_agent' } as const;
  const WHEN = '2026-09-01T10:00:00Z';

  function linksOf(...kinds: TaskLink['kind'][]): TaskLink[] {
    return kinds.map((kind, index) => ({
      kind,
      other: {
        key: `DEMO-${index + 2}`,
        title: `Задача вида ${kind} №${index}`,
        status: index % 2 === 0 ? 'in_progress' : 'done',
      },
      author: AUTHOR,
      created_at: WHEN,
    }));
  }

  it('вид связи стоит заголовком группы со счётчиком, а не плашкой слева', async () => {
    server.use(
      packageOf('DEMO-6', {
        links: linksOf('blocked_by', 'blocked_by', 'child', 'relates'),
      }),
      entries('DEMO-6'),
    );

    renderApp('/tasks/DEMO-6');
    await screen.findByRole('heading', { name: /DEMO-6/ });

    const section = screen.getByRole('heading', { name: say.task('links') }).closest('section');

    // Три группы — три заголовка, каждый ровно один раз: под ним все задачи вида.
    const groupHeadings = within(section as HTMLElement).getAllByRole('heading', { level: 3 });
    expect(groupHeadings).toHaveLength(3);

    const blockedByHeading = groupHeadings.find((node) => node.textContent?.includes('blocked_by'));
    expect(blockedByHeading).toBeDefined();
    // Идентификатор контракта рядом с подписью на языке человека — не вместо неё.
    expect(blockedByHeading).toHaveTextContent('blocked_by');
    expect(blockedByHeading).toHaveTextContent(say.ui('task.links.kind.blocked_by'));
    // Счётчик группы считает её собственные задачи, а не связи целиком.
    expect(blockedByHeading).toHaveTextContent(say.task('linkGroup.count', { count: 2 }));

    // Порядок групп значимый: то, что держит задачу, стоит первым.
    const order = groupHeadings.map((node) => node.textContent ?? '');
    expect(order.findIndex((text) => text.includes('blocked_by'))).toBe(0);
    expect(order.findIndex((text) => text.includes('relates'))).toBe(order.length - 1);

    // Прежней плашки слева больше нет: у знака вида связи своя разметка.
    expect(section?.querySelector('[data-mark="link-kind"]')).not.toBeNull();
  });

  it('родитель и дочерние задачи подписаны тем, кем они приходятся этой задаче', async () => {
    // `child` — эта задача ребёнок перечисленной, `parent` — она родитель перечисленных.
    server.use(
      packageOf('DEMO-6', { links: linksOf('parent', 'child', 'parent') }),
      entries('DEMO-6'),
    );

    renderApp('/tasks/DEMO-6');
    await screen.findByRole('heading', { name: /DEMO-6/ });

    const section = screen.getByRole('heading', { name: say.task('links') }).closest('section');
    const groups = within(section as HTMLElement)
      .getAllByRole('heading', { level: 3 })
      .map((node) => node.closest('section') as HTMLElement);
    const groupOf = (kind: string) =>
      groups.find((group) => group.querySelector('h3')?.textContent?.includes(kind));

    const parentGroup = groupOf('child') as HTMLElement;
    const childrenGroup = groupOf('parent') as HTMLElement;
    // Родитель выше дочерних и подписан словом «родитель», а не видом связи.
    expect(groups.indexOf(parentGroup)).toBeLessThan(groups.indexOf(childrenGroup));
    expect(parentGroup.querySelector('h3')).toHaveTextContent(say.ui('task.links.kind.child'));
    expect(within(parentGroup).getByRole('link', { name: 'DEMO-3' })).toBeInTheDocument();
    expect(childrenGroup.querySelector('h3')).toHaveTextContent(say.ui('task.links.kind.parent'));
    expect(within(childrenGroup).getAllByRole('link')).toHaveLength(2);

    // Шапка ведёт в родителя — ту задачу, у которой эта связь стоит как `child`.
    const header = screen.getByRole('heading', { level: 1 }).closest('header') as HTMLElement;
    expect(within(header).getByRole('link', { name: /DEMO-3/ })).toBeInTheDocument();
    expect(within(header).queryByRole('link', { name: /DEMO-2/ })).toBeNull();
  });

  it('статус связанной задачи нарисован тем же знаком, что в таблице задач', async () => {
    server.use(packageOf('DEMO-6', { links: linksOf('child') }), entries('DEMO-6'));

    renderApp('/tasks/DEMO-6');
    await screen.findByRole('heading', { name: /DEMO-6/ });

    const section = screen.getByRole('heading', { name: say.task('links') }).closest('section');
    const statusMark = within(section as HTMLElement)
      .getByText('in_progress')
      .closest('[data-mark="status"]');

    // Тот же знак, что в шапке карточки и в строке списка: форма, а не голая плашка.
    expect(statusMark?.querySelector('svg')).not.toBeNull();
  });
});

describe('порядок чтения карточки', () => {
  it('замечания идут до описи дела, а действие стоит в липкой навигации', async () => {
    server.use(packageOf('DEMO-6'), entries('DEMO-6'));
    renderApp('/tasks/DEMO-6');
    await screen.findByRole('heading', { name: say.task('remarks') });

    /*
     * Порядок разметки и есть порядок чтения: Tab и программа чтения с экрана идут
     * по нему, а не по тому, как блоки расставлены на широком экране. Сверяется по
     * заголовкам, а не по `aria-labelledby` секций: у DEMO-6 вопросы и замечания
     * пусты и делят одну слитую рамку без `aria-labelledby` (UI-132) — заголовок
     * при этом остаётся `<h2>` независимо от того, пуст блок или нет.
     */
    const remarksHeading = screen.getByRole('heading', { name: say.task('remarks') });
    const caseHeading = screen.getByRole('heading', { name: say.task('case') });
    const summaryHeading = screen.getByRole('heading', { name: say.task('summary') });
    expect(
      remarksHeading.compareDocumentPosition(caseHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      summaryHeading.compareDocumentPosition(remarksHeading) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // Кнопка одна и живёт в навигации: второго пути к форме нет.
    const nav = screen.getByRole('navigation', {
      name: say.ui('task.nav.label', { key: 'DEMO-6' }),
    });
    expect(within(nav).getByRole('button', { name: say.ui('remark.submit') })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: say.ui('remark.submit') })).toHaveLength(1);
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
    expect(await screen.findByText(say.task('noRemarks'))).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: say.ui('remark.submit') }));
    await user.type(
      screen.getByLabelText(say.ui('remark.fieldLabel')),
      'Дыры в нумерации сбивают с толку.',
    );
    await user.click(screen.getByRole('button', { name: say.ui('remark.submit') }));

    const receipt = await screen.findByRole('region', {
      name: say.ui('remark.receiptLabel', { key: 'DEMO-6' }),
    });
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
    expect(screen.getByText(say.ui('task.features.remarks', { count: 2 }))).toBeInTheDocument();
  });

  it('кадр живого потока обгоняет ответ сервера — подтверждение всё равно показано', async () => {
    const posts = withRemarks();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    await user.click(await screen.findByRole('button', { name: say.ui('remark.submit') }));
    await user.type(
      screen.getByLabelText(say.ui('remark.fieldLabel')),
      'Дыры в нумерации сбивают с толку.',
    );
    await user.click(screen.getByRole('button', { name: say.ui('remark.submit') }));

    // Кадр о той же записи перечитывает пакет. Форма замечания стоит вне списка,
    // поэтому переживает перечитывание — и своё подтверждение показывает сама.
    act(() => liveJournal.send({ ...remarkEntry(9, 'DEMO-6', 'Ещё одно'), seq: 2050 }));

    expect(
      await screen.findByRole('region', {
        name: say.ui('remark.receiptLabel', { key: 'DEMO-6' }),
      }),
    ).toBeInTheDocument();
    // Второй записи кадр не породил: подшивку делает форма, а поток только перечитывает.
    expect(posts).toHaveLength(1);
  });

  it('на закрытой задаче форма есть, а правки разделов нет', async () => {
    withRemarks({ task: taskDetails('DEMO-6', { status: 'done' }), transitions: [] });
    renderApp('/tasks/DEMO-6');

    expect(
      await screen.findByRole('button', { name: say.ui('remark.submit') }),
    ).toBeInTheDocument();
    // Роль человека не расширяется (`CONCEPT.md`, 7): закрытая задача не открывает
    // правку разделов задания.
    expect(screen.queryByRole('textbox', { name: say.task('sections.goal') })).toBeNull();
  });

  it('черновик переживает уход со страницы и отказ отправки', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-6`, () => data(taskPackage('DEMO-6', { remarks: [] }))),
      http.get(`${API}/api/v1/tasks`, () => collection([])),
      http.post(`${API}/api/v1/tasks/DEMO-6/entries`, () => failure('internal_error', 500, 'Boom')),
    );
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    await user.click(await screen.findByRole('button', { name: say.ui('remark.submit') }));
    await user.type(screen.getByLabelText(say.ui('remark.fieldLabel')), 'Недописанное замечание');

    // Отказ сети текст не уносит: повторять набранное человек не должен.
    await user.click(screen.getByRole('button', { name: say.ui('remark.submit') }));
    await screen.findByRole('alert');
    expect(screen.getByLabelText(say.ui('remark.fieldLabel'))).toHaveValue(
      'Недописанное замечание',
    );

    // Уход на список и возврат — тоже: черновик живёт в хранилище сеанса.
    await user.click(screen.getByRole('link', { name: say.ui('app.allTasks') }));
    await screen.findByRole('heading', { name: say.tasks('title') });
    renderApp('/tasks/DEMO-6');

    await user.click((await screen.findAllByRole('button', { name: say.ui('remark.submit') }))[0]!);
    expect(screen.getAllByLabelText(say.ui('remark.fieldLabel'))[0]).toHaveValue(
      'Недописанное замечание',
    );
  });

  it('замечание, отклонённое по заголовку, показывает переведённую причину у поля (UI-165)', async () => {
    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-6`, () => data(taskPackage('DEMO-6', { remarks: [] }))),
      http.get(`${API}/api/v1/tasks`, () => collection([])),
      http.post(`${API}/api/v1/tasks/DEMO-6/entries`, () =>
        // Настоящая форма бэкенда — список `{field, reason, ...}`
        // (`app/domain/fields.py`), не объект `{поле: причина}` (UI-165). Замечание
        // помечает `title`, не `body`: форма падает на него, только если у `body` своих
        // замечаний нет (`fields?.body ?? fields?.title`, `remark-form.tsx`).
        failure('entry_fields_invalid', 422, 'Entry fields invalid', {
          fields: [{ field: 'title', reason: 'too_long', max: 200, got: 500 }],
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6', { language: 'ru' });

    await user.click(await screen.findByRole('button', { name: say.ui('remark.submit') }));
    await user.type(screen.getByLabelText(say.ui('remark.fieldLabel')), 'Заведомо длинный текст');
    await user.click(screen.getByRole('button', { name: say.ui('remark.submit') }));

    expect(await screen.findByText(say.fieldReasons('too_long'))).toBeInTheDocument();
  });

  it('«Отмена» на пустой форме сворачивает её без вопроса (UI-142)', async () => {
    withRemarks();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    await user.click(await screen.findByRole('button', { name: say.ui('remark.submit') }));
    expect(screen.getByLabelText(say.ui('remark.fieldLabel'))).toHaveValue('');

    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    // Никакого вопроса — форма ушла сразу, и на месте снова кнопка «Оставить замечание».
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.queryByLabelText(say.ui('remark.fieldLabel'))).toBeNull();
    const nav = screen.getByRole('navigation', {
      name: say.ui('task.nav.label', { key: 'DEMO-6' }),
    });
    expect(within(nav).getByRole('button', { name: say.ui('remark.submit') })).toBeInTheDocument();
  });

  it('«Отмена» на непустом черновике спрашивает и выбрасывает его по подтверждению (UI-142)', async () => {
    withRemarks();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    await user.click(await screen.findByRole('button', { name: say.ui('remark.submit') }));
    await user.type(
      screen.getByLabelText(say.ui('remark.fieldLabel')),
      'Возможно, что-то упустил.',
    );

    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    // Форма ещё на экране: вопрос задан, а не выполнен сам собой.
    const dialog = await screen.findByRole('alertdialog', {
      name: say.ui('composer.discardTitle'),
    });
    expect(screen.getByLabelText(say.ui('remark.fieldLabel'))).toHaveValue(
      'Возможно, что-то упустил.',
    );

    await user.click(
      within(dialog).getByRole('button', { name: say.ui('composer.discardConfirm') }),
    );

    // Свернулась, и черновик пропал не только из вида: открыв форму заново, поле пусто.
    expect(screen.queryByLabelText(say.ui('remark.fieldLabel'))).toBeNull();
    await user.click(await screen.findByRole('button', { name: say.ui('remark.submit') }));
    expect(screen.getByLabelText(say.ui('remark.fieldLabel'))).toHaveValue('');
  });

  it('«Продолжить писать» закрывает вопрос и оставляет черновик как был (UI-142)', async () => {
    withRemarks();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-6');

    await user.click(await screen.findByRole('button', { name: say.ui('remark.submit') }));
    await user.type(screen.getByLabelText(say.ui('remark.fieldLabel')), 'Ещё дописываю.');
    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: say.ui('composer.keepWriting') }));

    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.getByLabelText(say.ui('remark.fieldLabel'))).toHaveValue('Ещё дописываю.');
  });
});

describe('вопрос на карточке: отмена ответа (UI-156)', () => {
  function withQuestion(overrides = {}) {
    server.use(
      packageOf('DEMO-4', {
        questions: [questionEntry(4, 'DEMO-4')],
        features: {
          blocked: false,
          open_questions: 1,
          open_blocking_questions: 1,
          last_summary_at: null,
        },
        ...overrides,
      }),
      entries('DEMO-4'),
    );
  }

  it('«Отмена» на пустой форме сворачивает её без вопроса', async () => {
    withQuestion();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-4');

    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue('');

    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    // Никакого вопроса — форма ушла сразу, и на месте снова кнопка «Ответить».
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.queryByLabelText(say.ui('answer.fieldLabel'))).toBeNull();
    expect(screen.getByRole('button', { name: say.ui('answer.open') })).toBeInTheDocument();
  });

  it('«Отмена» на непустом черновике спрашивает и выбрасывает его по подтверждению', async () => {
    withQuestion();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-4');

    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    await user.type(screen.getByLabelText(say.ui('answer.fieldLabel')), 'Хочу проверить отмену.');

    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    const dialog = await screen.findByRole('alertdialog', {
      name: say.ui('composer.discardTitle'),
    });
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue(
      'Хочу проверить отмену.',
    );

    await user.click(
      within(dialog).getByRole('button', { name: say.ui('composer.discardConfirm') }),
    );

    // Свернулась, и черновик пропал не только из вида: открыв форму заново, поле пусто.
    expect(screen.queryByLabelText(say.ui('answer.fieldLabel'))).toBeNull();
    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue('');
  });

  it('«Продолжить писать» закрывает диалог и оставляет черновик как был', async () => {
    withQuestion();
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-4');

    await user.click(await screen.findByRole('button', { name: say.ui('answer.open') }));
    await user.type(screen.getByLabelText(say.ui('answer.fieldLabel')), 'Ещё дописываю.');
    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: say.ui('composer.keepWriting') }));

    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(screen.getByLabelText(say.ui('answer.fieldLabel'))).toHaveValue('Ещё дописываю.');
  });

  it('адрес, называющий вопрос, раскрывает форму сразу — «Отмена» сворачивает её как обычно', async () => {
    withQuestion();
    const user = userEvent.setup();
    // `askedFor`: адрес называет именно этот вопрос, форма раскрыта без клика.
    renderApp('/tasks/DEMO-4?entry=4');

    expect(await screen.findByLabelText(say.ui('answer.fieldLabel'))).toHaveValue('');
    await user.click(screen.getByRole('button', { name: say.ui('composer.cancel') }));

    // Параметр `?entry=4` не тронут, но повторно форму принудительно не раскрывает:
    // на месте кнопка «Ответить», а не молчаливый повторный показ формы.
    expect(screen.queryByLabelText(say.ui('answer.fieldLabel'))).toBeNull();
    expect(screen.getByRole('button', { name: say.ui('answer.open') })).toBeInTheDocument();
  });
});

describe('опись: правки разделов одного действия (UI-133)', () => {
  const ACTION = '55555555-5555-4555-8555-555555555555';
  const FIELDS: components['schemas']['TaskField'][] = [
    'title',
    'description',
    'goal',
    'context',
    'constraints',
    'output',
    'checks',
  ];

  /** Заведение, семь правок одним `update_task` (записи 2–8) и решение после них. */
  function grouped(key: string) {
    return packageOf(key, {
      index: [
        heading(1, { type: 'created' }, 'Task created', { action_id: 'aaaa' }),
        ...FIELDS.map((field, offset) =>
          heading(offset + 2, { type: 'section_changed', field }, `Section changed: ${field}`, {
            action_id: ACTION,
          }),
        ),
        heading(9, { type: 'decision' }, 'Решение после правки', { action_id: 'bbbb' }),
      ],
    });
  }

  function nestedRows() {
    return Array.from(document.querySelectorAll('tr[data-nested]'));
  }

  it('семь правок стоят одной строкой, раскрываются кликом и адрес не трогают', async () => {
    server.use(grouped('DEMO-8'), entries('DEMO-8'));
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-8');

    const group = await screen.findByRole('button', {
      name: say.ui('entry.group.label', { first: 2, last: 8 }),
    });
    expect(group).toHaveAttribute('aria-expanded', 'false');
    // Строк описи три: заведение, группа, решение — а не девять.
    const table = screen.getByRole('table', { name: say.task('index.count', { count: 9 }) });
    expect(within(table).getAllByRole('row')).toHaveLength(1 + 3);
    expect(nestedRows()).toHaveLength(0);
    // Заголовок группы называет все разделы идентификаторами контракта.
    for (const field of FIELDS) expect(within(group).getByText(field)).toBeInTheDocument();

    await user.click(group);
    expect(group).toHaveAttribute('aria-expanded', 'true');
    expect(nestedRows()).toHaveLength(FIELDS.length);
    expect(address.current).toBe('/tasks/DEMO-8');
    // Раскрытие группы читает не тела, а только опись: тела — по клику на запись.
    expect(entriesCalls()).toHaveLength(0);

    await user.click(group);
    expect(nestedRows()).toHaveLength(0);
  });

  it('?entry=4 раскрывает группу, раскрывает именно запись 4 и приводит её в поле зрения', async () => {
    server.use(grouped('DEMO-8'), entries('DEMO-8'));
    const scrollIntoView = vi
      .spyOn(Element.prototype, 'scrollIntoView')
      .mockImplementation(() => {});
    renderApp('/tasks/DEMO-8?entry=4');

    const group = await screen.findByRole('button', {
      name: say.ui('entry.group.label', { first: 2, last: 8 }),
    });
    expect(group).toHaveAttribute('aria-expanded', 'true');
    const rows = nestedRows();
    const opened = rows.filter(
      (row) => row.querySelector('button[aria-expanded]')?.getAttribute('aria-expanded') === 'true',
    );
    expect(opened.map((row) => row.querySelector('th')?.textContent)).toEqual(['4']);
    await waitFor(() => expect(entriesCalls().some((url) => url.includes('nos=4'))).toBe(true));
    // Прокручивается строка записи 4, а не группа.
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
    expect(scrollIntoView.mock.contexts.at(-1)).toBe(opened[0]);
    scrollIntoView.mockRestore();
  });

  it('свёрнутая группа уносит из адреса номер своей записи', async () => {
    server.use(grouped('DEMO-8'), entries('DEMO-8'));
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-8?entry=4');

    const group = await screen.findByRole('button', {
      name: say.ui('entry.group.label', { first: 2, last: 8 }),
    });
    await user.click(group);
    await waitFor(() => expect(address.current).toBe('/tasks/DEMO-8'));
    expect(group).toHaveAttribute('aria-expanded', 'false');
    expect(nestedRows()).toHaveLength(0);
  });

  it('правки без признака действия стоят по одной, как раньше', async () => {
    server.use(
      packageOf('DEMO-8', {
        index: [2, 3].map((no) =>
          heading(no, { type: 'section_changed', field: 'goal' }, 'Section changed: goal'),
        ),
      }),
      entries('DEMO-8'),
    );
    renderApp('/tasks/DEMO-8');
    const table = await screen.findByRole('table', {
      name: say.task('index.count', { count: 2 }),
    });
    expect(within(table).getAllByRole('row')).toHaveLength(1 + 2);
    expect(document.querySelector('tr[data-group]')).toBeNull();
  });
});

describe('смысл признака в шапке достижим без наведения (UI-163)', () => {
  it('нажатие на знак меняет число на фразу признака, повторное — обратно', async () => {
    const user = userEvent.setup();
    server.use(
      packageOf('DEMO-4', {
        features: {
          blocked: true,
          open_questions: 2,
          open_blocking_questions: 1,
          open_remarks: 0,
          last_summary_at: null,
        },
      }),
      entries('DEMO-4'),
    );

    renderApp('/tasks/DEMO-4');
    const heading = await screen.findByRole('heading', { name: /DEMO-4/ });
    const header = heading.closest('header') as HTMLElement;

    const questions = say.ui('task.features.questionsBlocking', {
      count: 2,
      blocking: say.ui('task.features.blockingOf', { count: 1 }),
    });
    // Знак — кнопка-переключатель: на телефоне наведения нет, и одна подсказка `title`
    // до смысла знака не довела бы.
    const mark = within(header).getByRole('button', { name: questions });
    expect(mark).toHaveAttribute('aria-pressed', 'false');
    // До нажатия фраза есть только для диктора, глазу видно число.
    expect(within(mark).getByText(questions)).toHaveClass('sr-only');
    expect(mark).toHaveTextContent(/2$/);

    await user.click(mark);
    expect(mark).toHaveAttribute('aria-pressed', 'true');
    expect(within(mark).getByText(questions)).not.toHaveClass('sr-only');

    await user.click(mark);
    expect(mark).toHaveAttribute('aria-pressed', 'false');
    expect(within(mark).getByText(questions)).toHaveClass('sr-only');

    // С клавиатуры то же, и каждый знак раскрывается сам по себе.
    const blocked = within(header).getByRole('button', { name: say.ui('task.features.blocked') });
    blocked.focus();
    await user.keyboard('{Enter}');
    expect(within(blocked).getByText(say.ui('task.features.blocked'))).not.toHaveClass('sr-only');
    expect(mark).toHaveAttribute('aria-pressed', 'false');
  });
});
