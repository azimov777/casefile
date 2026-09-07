import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  API,
  bootstrap,
  collection,
  data,
  entryOfType,
  heading,
  questionEntry,
  remarkEntry,
  resolutionEntry,
  taskPackage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { address, renderApp } from '@testing/render';
import { ENTRY_TYPES, isServiceEntry, type Entry, type EntryType } from '@/entities/entry';
import { setToken } from '@/shared/api';

let seen: URL[] = [];

beforeEach(() => {
  seen = [];
  server.use(
    http.get(`${API}/api/v1/bootstrap`, () => data(bootstrap())),
    http.get(`${API}/api/v1/tasks/DEMO-1`, () => data(taskPackage('DEMO-1'))),
  );
  setToken('trk_test');
});

/** Дело из записи каждого типа: по нему видно и порядок, и отбор. */
function wholeCase(): Entry[] {
  return ENTRY_TYPES.map((type, index) => entryOfType(index + 1, 'DEMO-1', type));
}

/** Лента отвечает так же, как бэкенд: отбор по `types` сужает выдачу. */
/**
 * Номер записи нужного типа в собранном деле.
 *
 * Считается от порядка `ENTRY_TYPES`, а не выписан числом: новый тип записи в
 * контракте сдвигает номера, и тест, привязанный к «двенадцатой записи», после этого
 * проверяет соседнюю — молча и не падая по существу.
 */
function noOf(type: EntryType): number {
  return ENTRY_TYPES.indexOf(type) + 1;
}

function feed(entries = wholeCase()) {
  return http.get(`${API}/api/v1/tasks/DEMO-1/entries`, ({ request }) => {
    const url = new URL(request.url);
    seen.push(url);
    const types = url.searchParams.getAll('types');
    const items = types.length === 0 ? entries : entries.filter((e) => types.includes(e.type));
    return collection(items);
  });
}

function cards() {
  return screen.getAllByRole('article');
}

/** Пакет задачи с полной описью этого дела: по ней страница знает последнюю запись. */
function longCase(entries: Entry[]) {
  return http.get(`${API}/api/v1/tasks/DEMO-1`, () =>
    data(
      taskPackage('DEMO-1', {
        index: entries.map((entry) => heading(entry.no, entry.type, entry.title)),
      }),
    ),
  );
}

/**
 * Лента, отвечающая как бэкенд: `after_no` отрезает начало, страница — пять записей.
 * Пять, а не двадцать пять: дело в тесте короткое, а проверяется именно то, что
 * далёкая запись приезжает окном, а не листанием.
 */
function pagedFeed(entries: Entry[]) {
  return http.get(`${API}/api/v1/tasks/DEMO-1/entries`, ({ request }) => {
    const url = new URL(request.url);
    seen.push(url);
    const after = Number(url.searchParams.get('after_no') ?? '0');
    const rest = entries.filter((entry) => entry.no > after);
    return collection(rest.slice(0, 5), {
      has_more: rest.length > 5,
      next_cursor: rest.length > 5 ? 'дальше' : null,
    });
  });
}

describe('дело лентой', () => {
  it('показывает записи по порядку номеров одним запросом', async () => {
    server.use(feed());

    renderApp('/tasks/DEMO-1/case');

    await screen.findByText(`Это всё дело: записей ${ENTRY_TYPES.length}.`);
    const numbers = cards().map((card) => card.getAttribute('aria-label'));
    expect(numbers[0]).toBe('DEMO-1#1');
    expect(numbers.at(-1)).toBe(`DEMO-1#${ENTRY_TYPES.length}`);

    expect(seen).toHaveLength(1);
    expect(seen[0]?.searchParams.getAll('types')).toEqual([]);
  });

  it('отбор «служебные» оставляет только записи трекера', async () => {
    server.use(feed());
    renderApp('/tasks/DEMO-1/case');
    await screen.findByText(/Это всё дело/);

    await userEvent.setup().click(screen.getByRole('button', { name: 'Служебные' }));

    const service = ENTRY_TYPES.filter(isServiceEntry);
    expect(await screen.findByText(`Это всё дело: записей ${service.length}.`)).toBeInTheDocument();
    expect(seen.at(-1)?.searchParams.getAll('types').sort()).toEqual([...service].sort());
  });

  it('перечень типов свёрнут, а отобранные типы названы поимённо', async () => {
    const user = userEvent.setup();
    server.use(feed());

    renderApp('/tasks/DEMO-1/case?type=summary&type=decision');
    await screen.findByText(/Это всё дело/);

    // Восемнадцати флажков на первом экране дела нет: они занимали место до первой
    // записи, а дело открывают читать.
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    // Но что отобрано — видно словами, а не счётчиком «выбрано 2».
    const chosen = screen.getByRole('list', { name: 'Отобранные типы записей' });
    expect(within(chosen).getAllByRole('listitem')).toHaveLength(2);
    expect(chosen).toHaveTextContent('decision');
    expect(chosen).toHaveTextContent('summary');

    // Раскрытие даёт все типы контракта, каждый — обычный флажок с подписью.
    await user.click(screen.getByRole('button', { name: 'Выбрать типы' }));
    expect(screen.getAllByRole('checkbox')).toHaveLength(ENTRY_TYPES.length);
    expect(screen.getByRole('checkbox', { name: 'summary' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'attempt' })).not.toBeChecked();
  });

  it('тип снимается своим чипом, и отбор остаётся в адресе', async () => {
    const user = userEvent.setup();
    server.use(feed());

    renderApp('/tasks/DEMO-1/case?type=summary&type=decision');
    await screen.findByText(/Это всё дело/);

    await user.click(screen.getByRole('button', { name: 'Убрать тип: summary' }));

    expect(address.current).toContain('type=decision');
    expect(address.current).not.toContain('type=summary');
    expect(seen.at(-1)?.searchParams.getAll('types')).toEqual(['decision']);
  });

  it('«было / стало» и причина перехода видны прямо в ленте', async () => {
    server.use(feed());
    renderApp('/tasks/DEMO-1/case');
    await screen.findByText(/Это всё дело/);

    const section = screen.getByLabelText(`DEMO-1#${noOf('section_changed')}`);
    expect(within(section).getByText('Было')).toBeInTheDocument();
    expect(within(section).getByText('Старая цель')).toBeInTheDocument();
    expect(within(section).getByText('Новая цель')).toBeInTheDocument();

    const status = screen.getByLabelText(`DEMO-1#${noOf('status_changed')}`);
    expect(within(status).getByText(/Задан блокирующий вопрос/)).toBeInTheDocument();
  });

  it('разбор стоит под своим замечанием и называет исход словами', async () => {
    const remark = remarkEntry(3, 'DEMO-1', 'Дыры в нумерации сбивают с толку');
    const resolution = resolutionEntry(4, 'DEMO-1', 3);
    server.use(feed([remark, resolution]));
    renderApp('/tasks/DEMO-1/case');
    await screen.findByText(/Это всё дело/);

    const card = screen.getByLabelText('DEMO-1#3');
    // Разбор вложен в замечание — как ответ в вопрос: для читателя это одно событие.
    const inner = within(card).getByLabelText('DEMO-1#4');
    // Регуляркой: заголовок собран из частей, и исход стоит в строке «· принято в работу».
    expect(within(inner).getByText(/принято в работу/)).toBeInTheDocument();
    // Ключ продолжения остаётся ссылкой: по нему человек и переходит смотреть работу.
    expect(within(inner).getByRole('link', { name: 'DEMO-2' })).toHaveAttribute(
      'href',
      '/tasks/DEMO-2',
    );
    // Отдельной записью разбор в ленте не повторяется.
    expect(screen.getAllByLabelText('DEMO-1#4')).toHaveLength(1);
  });

  it('неразобранное замечание честно говорит, что разбора ещё нет', async () => {
    server.use(feed([remarkEntry(3, 'DEMO-1')]));
    renderApp('/tasks/DEMO-1/case');
    await screen.findByText(/Это всё дело/);

    expect(
      within(screen.getByLabelText('DEMO-1#3')).getByText('Разбора пока нет.'),
    ).toBeInTheDocument();
  });

  it('ответ стоит под своим вопросом, а не отдельной записью ленты', async () => {
    const question = questionEntry(3, 'DEMO-1');
    const answer = entryOfType(4, 'DEMO-1', 'answer');
    server.use(feed([question, { ...answer, payload: { question_no: 3 } } as Entry]));

    renderApp('/tasks/DEMO-1/case');

    const questionCard = await screen.findByLabelText('DEMO-1#3');
    // Ответ вложен в карточку вопроса, а не стоит рядом с ней.
    expect(within(questionCard).getByLabelText('DEMO-1#4')).toBeInTheDocument();
    expect(cards().filter((card) => card.getAttribute('aria-label') === 'DEMO-1#4')).toHaveLength(
      1,
    );
  });

  it('отбор по типу `answer` показывает ответы отдельными записями', async () => {
    const question = questionEntry(3, 'DEMO-1');
    const answer = { ...entryOfType(4, 'DEMO-1', 'answer'), payload: { question_no: 3 } } as Entry;
    server.use(feed([question, answer]));

    renderApp('/tasks/DEMO-1/case?type=answer');

    const card = await screen.findByLabelText('DEMO-1#4');
    expect(card).toBeInTheDocument();
    expect(screen.queryByLabelText('DEMO-1#3')).not.toBeInTheDocument();
  });

  it('далёкая запись приезжает окном, а не листанием всего дела', async () => {
    // Раньше лента дочитывала страницы одну за другой, пока запись не найдётся:
    // человек, пришедший по ссылке «см. #15», получал по дороге все тела до неё.
    const all = wholeCase();
    server.use(longCase(all), pagedFeed(all));

    renderApp('/tasks/DEMO-1/case?entry=15');

    const target = await screen.findByLabelText('DEMO-1#15');
    expect(target.className).toMatch(/highlighted/);

    // Двух запросов хватило: первая страница дела и окно, начатое за пять записей
    // до названной. Тел с шестой по десятую в этих ответах нет вовсе.
    expect(seen).toHaveLength(2);
    expect(seen.at(-1)?.searchParams.get('after_no')).toBe('10');
    expect(seen.at(-1)?.searchParams.get('cursor')).toBeNull();
  });

  it('окно названо вслух, и из него есть путь к началу дела', async () => {
    const all = wholeCase();
    const user = userEvent.setup();
    server.use(longCase(all), pagedFeed(all));

    renderApp('/tasks/DEMO-1/case?from=10');

    expect(await screen.findByText(/Показаны записи после DEMO-1#10/)).toBeInTheDocument();
    // Первой записи дела в окне нет — и это сказано, а не оставлено на догадку.
    expect(screen.queryByLabelText('DEMO-1#1')).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: 'Читать дело сначала' })[0]!);

    expect(await screen.findByLabelText('DEMO-1#1')).toBeInTheDocument();
    expect(screen.queryByText(/Показаны записи после/)).not.toBeInTheDocument();
  });

  it('«К свежей записи» ведёт к последней записи описи, а не последней загруженной', async () => {
    const all = wholeCase();
    const user = userEvent.setup();
    server.use(longCase(all), pagedFeed(all));

    renderApp('/tasks/DEMO-1/case');
    await screen.findByLabelText('DEMO-1#1');

    await user.click(screen.getByRole('button', { name: 'К свежей записи' }));

    // Последняя запись всего дела известна из описи пакета задачи: ждать, пока лента
    // дочитается до конца, чтобы узнать её номер, не приходится.
    const last = await screen.findByLabelText(`DEMO-1#${all.length}`);
    expect(last.className).toMatch(/highlighted/);
  });

  it('запись вне отбора по типу объясняется словами и отбор можно сбросить', async () => {
    server.use(feed());
    const user = userEvent.setup();

    // Отбор оставляет в ленте только сводки, а названа запись другого типа.
    renderApp('/tasks/DEMO-1/case?type=summary&entry=4');

    expect(await screen.findByText(/не попадает в отбор по типу/)).toBeInTheDocument();
    expect(screen.queryByLabelText('DEMO-1#4')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Показать все типы' }));

    const target = await screen.findByLabelText('DEMO-1#4');
    expect(target.className).toMatch(/highlighted/);
    expect(screen.queryByText(/не попадает в отбор по типу/)).not.toBeInTheDocument();
  });

  it('номер записи, которой в деле нет, объясняется, а не оставляет пустой экран', async () => {
    server.use(feed());
    renderApp('/tasks/DEMO-1/case?entry=99');

    expect(await screen.findByText(/в деле нет/)).toBeInTheDocument();
  });

  it('ссылка на ответ ведёт к нему туда, где он показан — внутрь вопроса', async () => {
    const question = questionEntry(3, 'DEMO-1');
    const answer = { ...entryOfType(4, 'DEMO-1', 'answer'), payload: { question_no: 3 } } as Entry;
    server.use(feed([question, answer]));

    renderApp('/tasks/DEMO-1/case?entry=4');

    const questionCard = await screen.findByLabelText('DEMO-1#3');
    const answerCard = within(questionCard).getByLabelText('DEMO-1#4');
    // Помечен именно ответ, а не вопрос, внутри которого он показан.
    expect(answerCard.className).toMatch(/highlighted/);
    expect(questionCard.className).not.toMatch(/highlighted/);
  });

  it('адрес с номером записи подсвечивает названную запись', async () => {
    server.use(feed());

    // Параметр `entry`, а не якорь `#4`: одно и то же действие человека называется
    // в адресе одинаково и здесь, и в описи карточки (`shared/lib/task-refs.ts`).
    renderApp('/tasks/DEMO-1/case?entry=4');

    const target = await screen.findByLabelText('DEMO-1#4');
    expect(target.className).toMatch(/highlighted/);
    expect(screen.getByLabelText('DEMO-1#5').className).not.toMatch(/highlighted/);
  });
});
