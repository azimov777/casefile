import { describe, expect, it } from 'vitest';
import {
  DEFAULT_SORT,
  EMPTY_FILTERS,
  OPEN_QUESTIONS_CONDITION,
  filtersToListParams,
  hasConditions,
  readFilters,
  splitTags,
  writeFilters,
  type TaskFilters,
} from './filters';

function filters(overrides: Partial<TaskFilters> = {}): TaskFilters {
  return { ...EMPTY_FILTERS, ...overrides };
}

describe('чтение отбора из адреса', () => {
  it('разбирает повторяющиеся параметры и флажки', () => {
    const params = new URLSearchParams(
      'queue=DEMO&status=open&status=in_progress&priority=high&tags=backend&tags=search&blocked=true&questions=true&text=поиск&assignee=owner&sort=key&cursor=abc',
    );

    expect(readFilters(params)).toEqual({
      view: 'table',
      queue: 'DEMO',
      status: ['open', 'in_progress'],
      priority: ['high'],
      assignee: 'owner',
      tags: ['backend', 'search'],
      text: 'поиск',
      blocked: true,
      withQuestions: true,
      query: '',
      sort: 'key',
      cursor: 'abc',
    });
  });

  it('теги принимает и перечислением через запятую', () => {
    expect(readFilters(new URLSearchParams('tags=backend,+search')).tags).toEqual([
      'backend',
      'search',
    ]);
  });

  it('значения не из контракта отбрасывает, а не отправляет на бэкенд', () => {
    const params = new URLSearchParams('status=opne&status=open&priority=urgent&sort=названию');

    const parsed = readFilters(params);
    expect(parsed.status).toEqual(['open']);
    expect(parsed.priority).toEqual([]);
    expect(parsed.sort).toBe(DEFAULT_SORT);
  });
});

describe('запись отбора в адрес', () => {
  it('пустое и умолчания в адрес не пишет', () => {
    expect(writeFilters(EMPTY_FILTERS).toString()).toBe('');
  });

  it('переживает круг: адрес → отбор → адрес', () => {
    const source = new URLSearchParams(
      'queue=DEMO&status=open&priority=low&assignee=owner&tags=docs&text=очередь&blocked=true&questions=true&sort=key&cursor=xyz',
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
    expect(params.cursor).toBeUndefined();
  });

  it('«есть открытые вопросы» уезжает условием языка запросов: числом его не выразить', () => {
    expect(filtersToListParams(filters({ withQuestions: true })).query).toBe(
      OPEN_QUESTIONS_CONDITION,
    );
  });

  it('заполненное поле запроса отменяет структурный отбор целиком', () => {
    const params = filtersToListParams(
      filters({ queue: 'DEMO', status: ['open'], withQuestions: true, query: ' status: done ' }),
    );

    expect(params).toEqual({ query: 'status: done', sort: [DEFAULT_SORT], cursor: undefined });
  });

  it('курсор и порядок едут при любом виде отбора', () => {
    expect(filtersToListParams(filters({ cursor: 'abc', sort: '-priority' }))).toMatchObject({
      cursor: 'abc',
      sort: ['-priority'],
    });
  });
});

describe('признак «условия заданы»', () => {
  it('порядок и курсор условиями не считаются', () => {
    expect(hasConditions(filters({ sort: 'key', cursor: 'abc' }))).toBe(false);
    expect(hasConditions(filters({ blocked: true }))).toBe(true);
    expect(hasConditions(filters({ query: 'status: open' }))).toBe(true);
  });
});

describe('разбор тегов', () => {
  it('обрезает пробелы и выбрасывает пустые', () => {
    expect(splitTags(' backend , , search ')).toEqual(['backend', 'search']);
  });
});
