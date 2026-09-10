import { describe, expect, it } from 'vitest';
import { say } from '@testing/say';
import { EMPTY_FILTERS, type TaskFilters } from './filters';
import { describeFilters } from './summary';

/*
 * Подписи условий берутся из словаря тем же ключом, что и в коде: правка формулировки
 * не роняет эти проверки, а пропавший ключ роняет.
 */
function labels(overrides: Partial<TaskFilters>) {
  return describeFilters({ ...EMPTY_FILTERS, ...overrides }, say.tasks).map(
    (condition) => condition.label,
  );
}

describe('условия отбора словами', () => {
  it('без условий не называет ничего: список пуст, а не «все задачи» строкой', () => {
    expect(describeFilters(EMPTY_FILTERS, say.tasks)).toEqual([]);
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
      say.tasks('filters.condition.status', { values: 'open, in_progress' }),
      say.tasks('filters.condition.priority', { values: 'high' }),
      say.tasks('filters.condition.assignee', { value: 'owner' }),
      say.tasks('filters.condition.text', { value: 'токен' }),
      say.tasks('filters.condition.blocked'),
      say.tasks('filters.condition.questions'),
      say.tasks('filters.condition.remarks'),
    ]);
  });

  it('на доске не называет статус: столбцы показаны все, и параметром он не уходит', () => {
    expect(labels({ view: 'board', queue: 'DEMO', status: ['open'], priority: ['high'] })).toEqual([
      say.tasks('filters.condition.priority', { values: 'high' }),
    ]);
  });

  it('очередь условием не считает: она стала местом в интерфейсе, а не отбором', () => {
    expect(labels({ queue: 'DEMO' })).toEqual([]);
  });

  it('порядок и режим условиями не считает: они меняют вид, а не состав выдачи', () => {
    expect(labels({ sort: 'key', page: 2, view: 'board' })).toEqual([]);
  });

  it('при заполненном запросе условие ровно одно: сам запрос', () => {
    const conditions = describeFilters(
      {
        ...EMPTY_FILTERS,
        queue: 'DEMO',
        blocked: true,
        query: 'status: open',
      },
      say.tasks,
    );

    // Запрос отменяет структурный отбор целиком, и перечислять рядом отменённое
    // значило бы показывать то, что на выдачу не влияет. Условия не потеряны:
    // они остались в адресе и вернутся, как только запрос опустеет.
    expect(conditions).toEqual([
      { id: 'query', label: say.tasks('filters.condition.query', { query: 'status: open' }) },
    ]);
  });
});
