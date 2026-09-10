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
        text: 'токен',
        blocked: true,
        withQuestions: true,
        withRemarks: true,
      }),
    ).toEqual([
      'статус open, in_progress',
      'приоритет high',
      'исполнитель owner',
      'текст «токен»',
      'только заблокированные',
      'есть открытые вопросы',
      'есть неразобранные замечания',
    ]);
  });

  it('на доске не называет статус: столбцы показаны все, и параметром он не уходит', () => {
    expect(labels({ view: 'board', queue: 'DEMO', status: ['open'], priority: ['high'] })).toEqual([
      'приоритет high',
    ]);
  });

  it('очередь условием не считает: она стала местом в интерфейсе, а не отбором', () => {
    expect(labels({ queue: 'DEMO' })).toEqual([]);
  });

  it('порядок и режим условиями не считает: они меняют вид, а не состав выдачи', () => {
    expect(labels({ sort: 'key', page: 2, view: 'board' })).toEqual([]);
  });

  it('при заполненном запросе условие ровно одно: сам запрос', () => {
    const conditions = describeFilters({
      ...EMPTY_FILTERS,
      queue: 'DEMO',
      blocked: true,
      query: 'status: open',
    });

    // Запрос отменяет структурный отбор целиком, и перечислять рядом отменённое
    // значило бы показывать то, что на выдачу не влияет. Условия не потеряны:
    // они остались в адресе и вернутся, как только запрос опустеет.
    expect(conditions).toEqual([{ id: 'query', label: 'запрос: status: open' }]);
  });
});
