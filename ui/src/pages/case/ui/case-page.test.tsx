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
  questionEntry,
  taskPackage,
} from '@testing/msw/responses';
import { server } from '@testing/msw/server';
import { renderApp } from '@testing/render';
import { ENTRY_TYPES, isServiceEntry, type Entry } from '@/entities/entry';
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

describe('дело лентой', () => {
  it('показывает записи по порядку номеров одним запросом', async () => {
    server.use(feed());

    renderApp('/tasks/DEMO-1/case');

    await screen.findByText('Это всё дело: записей 15.');
    const numbers = cards().map((card) => card.getAttribute('aria-label'));
    expect(numbers[0]).toBe('DEMO-1#1');
    expect(numbers.at(-1)).toBe('DEMO-1#15');

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

  it('«было / стало» и причина перехода видны прямо в ленте', async () => {
    server.use(feed());
    renderApp('/tasks/DEMO-1/case');
    await screen.findByText(/Это всё дело/);

    const section = screen.getByLabelText('DEMO-1#12');
    expect(within(section).getByText('Было')).toBeInTheDocument();
    expect(within(section).getByText('Старая цель')).toBeInTheDocument();
    expect(within(section).getByText('Новая цель')).toBeInTheDocument();

    const status = screen.getByLabelText('DEMO-1#11');
    expect(within(status).getByText(/Задан блокирующий вопрос/)).toBeInTheDocument();
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

  it('запись со второй страницы дочитывается сама, а не теряется', async () => {
    // Лента страничная: без дочитывания человек, пришедший по ссылке «см. #15»,
    // смотрел бы в ленту без пятнадцатой записи и не понимал, почему.
    const all = wholeCase();
    server.use(
      http.get(`${API}/api/v1/tasks/DEMO-1/entries`, ({ request }) => {
        const url = new URL(request.url);
        seen.push(url);
        const cursor = url.searchParams.get('cursor');
        if (cursor === null) {
          return collection(all.slice(0, 5), { has_more: true, next_cursor: 'вторая' });
        }
        return collection(all.slice(5));
      }),
    );

    renderApp('/tasks/DEMO-1/case?entry=15');

    const target = await screen.findByLabelText('DEMO-1#15');
    expect(target.className).toMatch(/highlighted/);
    // Дочитано именно страницами по курсору, а не одним запросом «дай всё».
    expect(seen).toHaveLength(2);
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
