import { http } from 'msw';
import userEvent from '@testing-library/user-event';
import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
import { say } from '@testing/say';
import {
  ENTRY_TYPES,
  factsOfEntry,
  isServiceEntry,
  type Entry,
  type EntryType,
} from '@/entities/entry';
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
        index: entries.map((entry) => heading(entry.no, factsOfEntry(entry), entry.title)),
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

    await screen.findByText(say.case('end', { count: ENTRY_TYPES.length }));
    const numbers = cards().map((card) => card.getAttribute('aria-label'));
    expect(numbers[0]).toBe('DEMO-1#1');
    expect(numbers.at(-1)).toBe(`DEMO-1#${ENTRY_TYPES.length}`);

    expect(seen).toHaveLength(1);
    expect(seen[0]?.searchParams.getAll('types')).toEqual([]);
  });

  it('отбор «служебные» оставляет только записи трекера', async () => {
    server.use(feed());
    renderApp('/tasks/DEMO-1/case');
    await screen.findByText(say.case('end', { count: ENTRY_TYPES.length }));

    await userEvent
      .setup()
      .click(screen.getByRole('button', { name: say.case('filters.serviceEntries') }));

    const service = ENTRY_TYPES.filter(isServiceEntry);
    expect(await screen.findByText(say.case('end', { count: service.length }))).toBeInTheDocument();
    expect(seen.at(-1)?.searchParams.getAll('types').sort()).toEqual([...service].sort());
  });

  it('перечень типов свёрнут, а отобранные типы названы поимённо', async () => {
    const user = userEvent.setup();
    server.use(feed());

    renderApp('/tasks/DEMO-1/case?type=summary&type=decision');
    await screen.findByText(say.case('end', { count: 2 }));

    // Восемнадцати флажков на первом экране дела нет: они занимали место до первой
    // записи, а дело открывают читать.
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    // Но что отобрано — видно словами, а не счётчиком «выбрано 2».
    const chosen = screen.getByRole('list', { name: say.case('filters.chosen') });
    expect(within(chosen).getAllByRole('listitem')).toHaveLength(2);
    expect(chosen).toHaveTextContent('decision');
    expect(chosen).toHaveTextContent('summary');

    // Раскрытие даёт все типы контракта, каждый — обычный флажок с подписью.
    await user.click(screen.getByRole('button', { name: say.case('filters.expand') }));
    expect(screen.getAllByRole('checkbox')).toHaveLength(ENTRY_TYPES.length);
    expect(screen.getByRole('checkbox', { name: 'summary' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'attempt' })).not.toBeChecked();
  });

  it('тип снимается своим чипом, и отбор остаётся в адресе', async () => {
    const user = userEvent.setup();
    server.use(feed());

    renderApp('/tasks/DEMO-1/case?type=summary&type=decision');
    await screen.findByText(say.case('end', { count: 2 }));

    await user.click(
      screen.getByRole('button', { name: say.case('filters.remove', { type: 'summary' }) }),
    );

    expect(address.current).toContain('type=decision');
    expect(address.current).not.toContain('type=summary');
    expect(seen.at(-1)?.searchParams.getAll('types')).toEqual(['decision']);
  });

  it('«было / стало» и причина перехода видны прямо в ленте', async () => {
    server.use(feed());
    renderApp('/tasks/DEMO-1/case');
    await screen.findByText(say.case('end', { count: ENTRY_TYPES.length }));

    const section = screen.getByLabelText(`DEMO-1#${noOf('section_changed')}`);
    expect(within(section).getByText(say.ui('entry.was'))).toBeInTheDocument();
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
    await screen.findByText(say.case('end', { count: 2 }));

    const card = screen.getByLabelText('DEMO-1#3');
    // Разбор вложен в замечание — как ответ в вопрос: для читателя это одно событие.
    const inner = within(card).getByLabelText('DEMO-1#4');
    // Регуляркой: заголовок собран из частей, и исход стоит в строке «· taken into work».
    expect(
      within(inner).getByText(new RegExp(say.ui('entry.remarkOutcome.accepted'))),
    ).toBeInTheDocument();
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
    await screen.findByText(say.case('end', { count: 1 }));

    expect(
      within(screen.getByLabelText('DEMO-1#3')).getByText(say.case('noResolutionYet')),
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
    expect(target).toHaveAttribute('data-highlighted');

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

    const windowShown = say.case('window.shown', { reference: 'DEMO-1#10' });
    expect(await screen.findByText(windowShown)).toBeInTheDocument();
    // Первой записи дела в окне нет — и это сказано, а не оставлено на догадку.
    expect(screen.queryByLabelText('DEMO-1#1')).not.toBeInTheDocument();

    await user.click(screen.getAllByRole('button', { name: say.case('fromStart') })[0]!);

    expect(await screen.findByLabelText('DEMO-1#1')).toBeInTheDocument();
    expect(screen.queryByText(windowShown)).not.toBeInTheDocument();
  });

  it('«К свежей записи» ведёт к последней записи описи, а не последней загруженной', async () => {
    const all = wholeCase();
    const user = userEvent.setup();
    server.use(longCase(all), pagedFeed(all));

    renderApp('/tasks/DEMO-1/case');
    await screen.findByLabelText('DEMO-1#1');

    await user.click(screen.getByRole('button', { name: say.case('toLatest') }));

    // Последняя запись всего дела известна из описи пакета задачи: ждать, пока лента
    // дочитается до конца, чтобы узнать её номер, не приходится.
    const last = await screen.findByLabelText(`DEMO-1#${all.length}`);
    expect(last).toHaveAttribute('data-highlighted');
  });

  it('запись вне отбора по типу объясняется словами и отбор можно сбросить', async () => {
    server.use(feed());
    const user = userEvent.setup();

    // Отбор оставляет в ленте только сводки, а названа запись другого типа.
    renderApp('/tasks/DEMO-1/case?type=summary&entry=4');

    const hiddenByType = say.case('window.hiddenByType', { reference: 'DEMO-1#4' });
    expect(await screen.findByText(hiddenByType)).toBeInTheDocument();
    expect(screen.queryByLabelText('DEMO-1#4')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: say.case('window.showAllTypes') }));

    const target = await screen.findByLabelText('DEMO-1#4');
    expect(target).toHaveAttribute('data-highlighted');
    expect(screen.queryByText(hiddenByType)).not.toBeInTheDocument();
  });

  it('номер записи, которой в деле нет, объясняется, а не оставляет пустой экран', async () => {
    server.use(feed());
    renderApp('/tasks/DEMO-1/case?entry=99');

    expect(
      await screen.findByText(say.case('window.missing', { reference: 'DEMO-1#99' })),
    ).toBeInTheDocument();
  });

  it('ссылка на ответ ведёт к нему туда, где он показан — внутрь вопроса', async () => {
    const question = questionEntry(3, 'DEMO-1');
    const answer = { ...entryOfType(4, 'DEMO-1', 'answer'), payload: { question_no: 3 } } as Entry;
    server.use(feed([question, answer]));

    renderApp('/tasks/DEMO-1/case?entry=4');

    const questionCard = await screen.findByLabelText('DEMO-1#3');
    const answerCard = within(questionCard).getByLabelText('DEMO-1#4');
    // Помечен именно ответ, а не вопрос, внутри которого он показан.
    expect(answerCard).toHaveAttribute('data-highlighted');
    expect(questionCard).not.toHaveAttribute('data-highlighted');
  });

  it('адрес с номером записи подсвечивает названную запись', async () => {
    server.use(feed());

    // Параметр `entry`, а не якорь `#4`: одно и то же действие человека называется
    // в адресе одинаково и здесь, и в описи карточки (`shared/lib/task-refs.ts`).
    renderApp('/tasks/DEMO-1/case?entry=4');

    const target = await screen.findByLabelText('DEMO-1#4');
    expect(target).toHaveAttribute('data-highlighted');
    expect(screen.getByLabelText('DEMO-1#5')).not.toHaveAttribute('data-highlighted');
  });
});

describe('лента: правки разделов одного действия (UI-133)', () => {
  const ACTION = '55555555-5555-4555-8555-555555555555';
  const FIELDS = ['title', 'goal', 'checks'] as const;

  /** Заведение, три правки одним `update_task` (записи 2–4) и решение после них. */
  function edited(): Entry[] {
    const sections = FIELDS.map((field, offset): Entry => {
      const base = entryOfType(offset + 2, 'DEMO-1', 'section_changed');
      if (base.type !== 'section_changed') throw new Error('section_changed expected');
      return {
        ...base,
        action_id: ACTION,
        payload: { ...base.payload, field, before: `Было ${field}`, after: `Стало ${field}` },
      };
    });
    return [
      { ...entryOfType(1, 'DEMO-1', 'created'), action_id: 'aaaa' },
      ...sections,
      { ...entryOfType(5, 'DEMO-1', 'decision'), action_id: 'bbbb' },
    ];
  }

  function group() {
    return screen.getByRole('region', { name: say.ui('entry.group.label', { first: 2, last: 4 }) });
  }

  it('правки стоят одной строкой, их пары «было / стало» — только по раскрытию', async () => {
    const entries = edited();
    server.use(feed(entries), longCase(entries));
    const user = userEvent.setup();
    renderApp('/tasks/DEMO-1/case');

    await screen.findByLabelText('DEMO-1#5');
    // В ленте две записи и группа, а не пять записей.
    expect(cards().map((card) => card.getAttribute('aria-label'))).toEqual([
      'DEMO-1#1',
      'DEMO-1#5',
    ]);
    const toggle = within(group()).getByRole('button', {
      name: say.ui('entry.group.expand', { count: 3 }),
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    for (const field of FIELDS) expect(within(group()).getByText(field)).toBeInTheDocument();
    expect(screen.queryByText('Стало goal')).not.toBeInTheDocument();

    await user.click(toggle);
    expect(within(group()).getAllByRole('article')).toHaveLength(FIELDS.length);
    expect(screen.getByText('Стало goal')).toBeInTheDocument();
    // Записи в группе остаются адресуемыми по номеру.
    expect(screen.getByLabelText('DEMO-1#3')).toHaveAttribute('id', 'entry-3');

    await user.click(within(group()).getByRole('button', { name: say.ui('entry.group.collapse') }));
    expect(within(group()).queryAllByRole('article')).toHaveLength(0);
  });

  it('?entry=3 раскрывает группу, помечает именно запись 3 и прокручивает к ней', async () => {
    const entries = edited();
    server.use(feed(entries), longCase(entries));
    const scrollIntoView = vi
      .spyOn(Element.prototype, 'scrollIntoView')
      .mockImplementation(() => {});
    renderApp('/tasks/DEMO-1/case?entry=3');

    const target = await screen.findByLabelText('DEMO-1#3');
    expect(target).toHaveAttribute('data-highlighted');
    expect(screen.getByLabelText('DEMO-1#2')).not.toHaveAttribute('data-highlighted');
    expect(
      within(group()).getByRole('button', { name: say.ui('entry.group.collapse') }),
    ).toHaveAttribute('aria-expanded', 'true');
    await waitFor(() => expect(scrollIntoView.mock.contexts).toContain(target));
    scrollIntoView.mockRestore();
  });
});
