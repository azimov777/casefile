import { describe, expect, it } from 'vitest';
import { ApiError } from './error';

describe('ApiError.fromBody', () => {
  it('читает замечания по полям из details.fields — списком, как шлёт бэкенд', () => {
    // Форма — настоящая, из `tests/test_case_api.py`
    // (`test_a_question_to_someone_outside_the_registry_is_refused`): список объектов
    // `{field, reason, ...}`, не объект `{поле: причина}`.
    const error = ApiError.fromBody(
      {
        error: {
          code: 'entry_fields_invalid',
          message: 'Case entry fields are invalid',
          details: {
            fields: [{ field: 'question_no', reason: 'unknown_entry', key: 'TRK-1', no: 99 }],
          },
        },
      },
      422,
    );

    expect(error.fields).toEqual({ question_no: 'unknown_entry' });
  });

  it('несколько замечаний в одном ответе — каждое по своему полю', () => {
    const error = ApiError.fromBody(
      {
        error: {
          code: 'task_fields_invalid',
          message: 'Task fields are invalid',
          details: {
            fields: [
              { field: 'title', reason: 'required' },
              { field: 'priority', reason: 'not_allowed', allowed: ['low', 'normal'] },
            ],
          },
        },
      },
      422,
    );

    expect(error.fields).toEqual({ title: 'required', priority: 'not_allowed' });
  });

  it('объектная форма `{поле: причина}` не разбирается: бэкенд её не шлёт', () => {
    const error = ApiError.fromBody(
      {
        error: {
          code: 'entry_fields_invalid',
          message: 'Case entry fields are invalid',
          details: { fields: { question_no: 'unknown_entry' } },
        },
      },
      422,
    );

    expect(error.fields).toBeNull();
  });

  it('элемент списка без поля или причины строкой — пропускается', () => {
    const error = ApiError.fromBody(
      {
        error: {
          code: 'entry_fields_invalid',
          message: 'Case entry fields are invalid',
          details: { fields: [{ field: 'body' }, 'not an object', { reason: 'required' }] },
        },
      },
      422,
    );

    expect(error.fields).toBeNull();
  });

  it('без details.fields полей нет, а не пустой объект', () => {
    const error = ApiError.fromBody(
      { error: { code: 'conflict', message: 'State conflict' } },
      409,
    );
    expect(error.fields).toBeNull();
    expect(error.details).toEqual({});
  });

  it('чужое тело не выдаётся за контракт', () => {
    expect(ApiError.fromBody({ detail: 'Not Found' }, 404).code).toBe('malformed_response');
    expect(ApiError.fromBody({ error: { code: 7 } }, 400).code).toBe('malformed_response');
  });
});
