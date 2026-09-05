import { describe, expect, it } from 'vitest';
import { ApiError } from './error';

describe('ApiError.fromBody', () => {
  it('читает замечания по полям из details.fields', () => {
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

    expect(error.fields).toEqual({ question_no: 'unknown_entry' });
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
