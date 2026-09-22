import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_COLLAPSED,
  DEFAULT_SORT,
  EMPTY_FILTERS,
  OPEN_QUESTIONS_CONDITION,
  OPEN_REMARKS_CONDITION,
  filtersToListParams,
  hasConditions,
  readFilters,
  writeFilters,
  type TaskFilters,
} from './filters';

function filters(overrides: Partial<TaskFilters> = {}): TaskFilters {
  return { ...EMPTY_FILTERS, ...overrides };
}

describe('чтение отбора из адреса', () => {
  it('разбирает повторяющиеся параметры и флажки', () => {
    const params = new URLSearchParams(
      'queue=DEMO&status=open&status=in_progress&priority=high&blocked=true&questions=true&remarks=true&text=поиск&assignee=owner&sort=key&page=3',
    );

    expect(readFilters(params)).toEqual({
      view: 'table',
      queue: 'DEMO',
      status: ['open', 'in_progress'],
      priority: ['high'],
      assignee: 'owner',
      text: 'поиск',
      blocked: true,
      withQuestions: true,
      withRemarks: true,
      query: '',
      sort: 'key',
      page: 3,
      collapsed: DEFAULT_COLLAPSED,
      showArchive: false,
    });
  });

  it('значения не из контракта отбрасывает, а не отправляет на бэкенд', () => {
    const params = new URLSearchParams('status=opne&status=open&priority=urgent&sort=названию');

    const parsed = readFilters(params);
    expect(parsed.status).toEqual(['open']);
    expect(parsed.priority).toEqual([]);
    expect(parsed.sort).toBe(DEFAULT_SORT);
  });

  it('негодный номер страницы читает как первую, а не как отказ', () => {
    for (const search of ['page=abc', 'page=0', 'page=-2', 'page=1.5', 'page=']) {
      expect(readFilters(new URLSearchParams(search)).page, search).toBe(1);
    }
  });

  it('старая ссылка с курсором открывает начало списка: курсора в адресе больше нет', () => {
    const parsed = readFilters(new URLSearchParams('queue=DEMO&cursor=eyJrIjog'));

    expect(parsed.page).toBe(1);
    expect(parsed.queue).toBe('DEMO');
    expect(writeFilters(parsed).has('cursor')).toBe(false);
  });
});

describe('свёрнутые столбцы доски', () => {
  it('без параметра свёрнуты закрытые и отменённые', () => {
    expect(readFilters(new URLSearchParams('view=board')).collapsed).toEqual(DEFAULT_COLLAPSED);
  });

  it('пустое значение означает «ничего не свёрнуто», а не «параметра нет»', () => {
    expect(readFilters(new URLSearchParams('view=board&collapsed=')).collapsed).toEqual([]);
    expect(writeFilters({ ...EMPTY_FILTERS, view: 'board', collapsed: [] }).get('collapsed')).toBe(
      '',
    );
  });

  it('умолчание в адрес не пишет, а отличное от него — пишет целиком', () => {
    expect(writeFilters({ ...EMPTY_FILTERS, collapsed: DEFAULT_COLLAPSED }).has('collapsed')).toBe(
      false,
    );
    expect(
      writeFilters({ ...EMPTY_FILTERS, collapsed: ['backlog', 'done'] }).getAll('collapsed'),
    ).toEqual(['backlog', 'done']);
  });

  it('свёрнутость условием отбора не считается: она про вид, а не про состав выдачи', () => {
    expect(hasConditions({ ...EMPTY_FILTERS, collapsed: [] })).toBe(false);
  });
});

describe('запись отбора в адрес', () => {
  it('пустое и умолчания в адрес не пишет', () => {
    expect(writeFilters(EMPTY_FILTERS).toString()).toBe('');
  });

  it('переживает круг: адрес → отбор → адрес', () => {
    const source = new URLSearchParams(
      'queue=DEMO&status=open&priority=low&assignee=owner&text=очередь&blocked=true&questions=true&sort=key&page=4',
    );

    expect(writeFilters(readFilters(source)).toString()).toBe(source.toString());
  });
});

describe('перевод отбора в параметры запроса', () => {
  it('структурные условия уезжают своими параметрами', () => {
    const params = filtersToListParams(
      filters({ queue: 'DEMO', status: ['open'], blocked: true, text: '  поиск  ' }),
    );

    expect(params).toMatchObject({
      queue: ['DEMO'],
      status: ['open'],
      blocked: true,
      text: 'поиск',
      sort: [DEFAULT_SORT],
    });
    expect(params.offset).toBeUndefined();
  });

  it('«есть открытые вопросы» уезжает условием языка запросов: числом его не выразить', () => {
    expect(filtersToListParams(filters({ withQuestions: true })).query).toBe(
      OPEN_QUESTIONS_CONDITION,
    );
  });

  it('«есть неразобранные замечания» — такое же условие, и складывается с вопросами', () => {
    expect(filtersToListParams(filters({ withRemarks: true })).query).toBe(OPEN_REMARKS_CONDITION);

    // Два флажка — одно условие через `and`: иначе второй молча вытеснил бы первый.
    expect(filtersToListParams(filters({ withQuestions: true, withRemarks: true })).query).toBe(
      `${OPEN_QUESTIONS_CONDITION} and ${OPEN_REMARKS_CONDITION}`,
    );
  });

  it('заполненное поле запроса отменяет структурный отбор целиком', () => {
    const params = filtersToListParams(
      filters({ queue: 'DEMO', status: ['open'], withQuestions: true, query: ' status: done ' }),
    );

    // Правило архива остаётся и поверх запроса: его строка складывается с правилом
    // в момент чтения (`fetchTasks`), а здесь стоит только признак (UI-97).
    expect(params).toEqual({
      query: 'status: done',
      sort: [DEFAULT_SORT],
      offset: undefined,
      hideArchived: true,
    });
  });

  it('номер страницы уезжает смещением, а порядок — при любом виде отбора', () => {
    // Страница 3 по пятьдесят строк начинается со сто первой: `(3 - 1) * 50`.
    expect(filtersToListParams(filters({ page: 3, sort: '-priority' }))).toMatchObject({
      offset: 100,
      sort: ['-priority'],
    });
  });

  it('первая страница смещения не просит: `offset=0` — тот же запрос, только шумнее', () => {
    expect(filtersToListParams(filters({ page: 1 })).offset).toBeUndefined();
  });

  it('доска смещения не получает: её страницы копятся своей подгрузкой', () => {
    expect(filtersToListParams(filters({ view: 'board', page: 3 })).offset).toBeUndefined();
  });

  it('порядок на доске тот же, что выбран в таблице: он сортирует карточки в столбцах', () => {
    // До UI-130 доска подменяла выбор человека своим порядком (UI-130#10).
    expect(filtersToListParams(filters({ view: 'board', sort: '-priority' })).sort).toEqual([
      '-priority',
    ]);
  });

  it('курсора в параметрах таблицы нет вовсе: он и смещение вместе — отказ бэкенда', () => {
    expect(filtersToListParams(filters({ page: 3 }))).not.toHaveProperty('cursor');
  });
});

describe('признак «условия заданы»', () => {
  it('порядок и номер страницы условиями не считаются', () => {
    expect(hasConditions(filters({ sort: 'key', page: 3 }))).toBe(false);
    expect(hasConditions(filters({ blocked: true }))).toBe(true);
    expect(hasConditions(filters({ query: 'status: open' }))).toBe(true);
  });
});

describe('архив', () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it('по умолчанию скрыт: и без условий, и под запросом человека, и на доске', () => {
    expect(filtersToListParams(filters()).hideArchived).toBe(true);
    expect(filtersToListParams(filters({ query: 'status: done' })).hideArchived).toBe(true);
    expect(filtersToListParams(filters({ view: 'board' })).hideArchived).toBe(true);
  });

  it('показанный живёт в адресе словом `shown` и переживает круг', () => {
    const source = new URLSearchParams('queue=DEMO&archive=shown');

    const parsed = readFilters(source);
    expect(parsed.showArchive).toBe(true);
    expect(writeFilters(parsed).toString()).toBe(source.toString());
    // Показанный архив в запрос не просится вовсе — выдача API по умолчанию и есть всё.
    expect(filtersToListParams(parsed)).not.toHaveProperty('hideArchived');
  });

  it('умолчание в адрес не пишется, а негодное значение читается умолчанием', () => {
    expect(writeFilters(filters({ showArchive: false })).has('archive')).toBe(false);
    for (const search of ['archive=true', 'archive=', 'archive=SHOWN', '']) {
      expect(readFilters(new URLSearchParams(search)).showArchive, search).toBe(false);
    }
  });

  it('показ архива условием отбора не считается: он выдачу расширяет, а не сужает', () => {
    expect(hasConditions(filters({ showArchive: true }))).toBe(false);
  });

  it('даты в параметрах нет: ключ запроса один и тот же, сколько бы времени ни прошло', () => {
    vi.useFakeTimers({ toFake: ['Date'], now: new Date('2026-09-11T12:00:00Z') });
    const before = filtersToListParams(filters({ query: 'status: done' }));

    vi.setSystemTime(new Date('2026-09-15T08:30:00Z'));
    const after = filtersToListParams(filters({ query: 'status: done' }));

    expect(after).toEqual(before);
    expect(JSON.stringify(after)).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });
});
