import { describe, expect, it } from 'vitest';
import { ApiError } from '@/shared/api';
import { caretLine, readQueryProblem } from './query-problem';

describe('разбор отказа на негодный отбор', () => {
  it('берёт позицию, строку и допустимые значения из details', () => {
    const error = new ApiError('search_value_invalid', 'Search value is invalid', 422, {
      field: 'status',
      position: 8,
      value: 'opne',
      allowed: ['backlog', 'open', 'in_progress'],
    });

    expect(readQueryProblem(error, 'status: opne')).toEqual({
      message: 'Значение условия отбора недопустимо.',
      position: 8,
      query: 'status: opne',
      allowed: ['backlog', 'open', 'in_progress'],
    });
  });

  it('строку берёт из details, когда бэкенд её вернул', () => {
    const error = new ApiError('invalid_search_query', 'Search query cannot be parsed', 422, {
      query: 'status = = open',
      position: 9,
      reason: 'unexpected_character',
    });

    expect(readQueryProblem(error, 'что-то другое')?.query).toBe('status = = open');
  });

  it('чужой отказ подсказкой у поля не становится', () => {
    const error = new ApiError('unauthorized', 'Authentication required', 401, {});
    expect(readQueryProblem(error, 'status: open')).toBeNull();
    expect(readQueryProblem(new Error('сеть'), 'status: open')).toBeNull();
  });
});

describe('указатель на позицию', () => {
  it('ставит крышку под нужным символом', () => {
    expect(caretLine('status: opne', 8)).toBe('        ^');
  });

  it('позицию за пределами строки прижимает к её концу', () => {
    expect(caretLine('abc', 99)).toBe('   ^');
  });
});
