import { describe, expect, it } from 'vitest';
import { EMPTY_FILTERS, type TaskFilters } from './filters';
import { describeFilters } from './summary';

function labels(overrides: Partial<TaskFilters>) {
  return describeFilters({ ...EMPTY_FILTERS, ...overrides }).map((condition) => condition.label);
}

describe('условия отбора словами', () => {
  it('без условий не называет ничего: список пуст, а не «все задачи» строкой', () => {
    expect(describeFilters(EMPTY_FILTERS)).toEqual([]);
  });

  it('называет каждое включённое условие и ни одно не сворачивает в счётчик', () => {
    expect(
      labels({
        queue: 'DEMO',
        status: ['open', 'in_progress'],
        priority: ['high'],
        assignee: 'owner',
        tags: ['frontend', 'ux'],
        text: 'токен',
        blocked: true,
        withQuestions: true,
        query: 'status: done',
      }),
    ).toEqual([
      'очередь DEMO',
      'статус open, in_progress',
      'приоритет high',
      'исполнитель owner',
      'теги frontend, ux',
      'текст «токен»',
      'только заблокированные',
      'есть открытые вопросы',
      'запрос: status: done',
    ]);
  });

  it('на доске не называет статус: столбцы показаны все, и параметром он не уходит', () => {
    expect(labels({ view: 'board', queue: 'DEMO', status: ['open'] })).toEqual(['очередь DEMO']);
  });

  it('порядок и режим условиями не считает: они меняют вид, а не состав выдачи', () => {
    expect(labels({ sort: 'key', cursor: 'page-2', view: 'board' })).toEqual([]);
  });

  it('при заполненном запросе помечает нерабочими все остальные условия', () => {
    const conditions = describeFilters({
      ...EMPTY_FILTERS,
      queue: 'DEMO',
      blocked: true,
      query: 'status: open',
    });

    expect(conditions.map((condition) => [condition.id, condition.inactive])).toEqual([
      ['queue', true],
      ['blocked', true],
      ['query', false],
    ]);
  });

  it('без запроса не помечает нерабочим ничего', () => {
    const conditions = describeFilters({ ...EMPTY_FILTERS, queue: 'DEMO', blocked: true });
    expect(conditions.every((condition) => !condition.inactive)).toBe(true);
  });
});
