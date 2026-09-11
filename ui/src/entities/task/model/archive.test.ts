import { describe, expect, it } from 'vitest';
import { ApiError } from '@/shared/api';
import {
  ARCHIVE_AFTER_DAYS,
  archiveThreshold,
  hideArchive,
  outsideArchive,
  wrappable,
} from './archive';

const NOW = new Date('2026-09-11T12:00:00.000Z');

/**
 * Правило показа при этих часах — написано здесь заново, а не собрано кодом: тест,
 * берущий строку оттуда же, откуда её берёт запрос, сверял бы код с самим собой.
 */
const RULE = 'status: not in done, cancelled or last_entry_at: >= "2026-09-08T12:00:00.000Z"';

function refusal(code: string, details: Record<string, unknown>): ApiError {
  return new ApiError(code, 'Search query is invalid', 422, details);
}

describe('правило архива', () => {
  it('порог — ровно три дня назад, абсолютным мгновением в UTC', () => {
    expect(ARCHIVE_AFTER_DAYS).toBe(3);
    expect(archiveThreshold(NOW)).toBe('2026-09-08T12:00:00.000Z');
  });

  it('«не в архиве» — не закрыта или писали после порога; время в кавычках', () => {
    expect(outsideArchive(NOW)).toBe(RULE);
  });

  it('без запроса уходит одно правило', () => {
    for (const query of [undefined, null, '', '   ']) {
      expect(hideArchive(query, NOW).query, String(query)).toBe(RULE);
    }
  });

  it('запрос складывается с правилом по «и», запрос первым', () => {
    expect(hideArchive('status: done', NOW).query).toBe(`(status: done) and (${RULE})`);
    // Скобки человека внутри группы остаются его скобками: смысл тот же, `or` не
    // вырывается наружу — `and` у склейки стоит за закрывающей скобкой.
    expect(hideArchive('status: done or priority: high', NOW).query).toBe(
      `(status: done or priority: high) and (${RULE})`,
    );
  });
});

describe('можно ли обернуть строку скобками', () => {
  it.each([
    'status: done',
    '(status: done or status: cancelled) and priority: high',
    'assignee: empty()',
    'text: "скобка ( в кавычках"',
    "text: 'и ) в одинарных'",
    'text: "кавычка \\" внутри и скобка ("',
    'status: done #',
    'a: 1 b: 2',
  ])('да: %s', (query) => {
    expect(wrappable(query)).toBe(true);
  });

  it.each([
    'status: done)',
    '(status: done',
    'status: done) or (status: cancelled',
    'text: "abc',
    "text: 'abc",
    'text: "abc\\"',
    'text: "abc\\',
    ')(',
  ])('нет: %s', (query) => {
    expect(wrappable(query)).toBe(false);
  });

  it('строку, которую обернуть нельзя, отправляет одну — без правила и без склейки', () => {
    // Такую строку бэкенд отвергает и одну, и позицию называет в ней же. Склеенная,
    // она проходила бы и отдавала архив: скобка человека закрывала бы нашу группу.
    const query = 'status: done) or (status: cancelled';
    const sent = hideArchive(query, NOW);

    expect(sent.query).toBe(query);
    const error = refusal('invalid_search_query', { position: 12, query });
    expect(sent.relocate(error)).toBe(error);
  });
});

describe('отказ склейки возвращается в строку человека', () => {
  it('позиция сдвигается на префикс, строка отказа — его строка, остальное как было', () => {
    const query = 'status: donee';
    const sent = hideArchive(query, NOW);
    // Бэкенд называет позицию в той строке, которую получил, — в склейке.
    const position = sent.query.indexOf('donee');

    const relocated = sent.relocate(
      refusal('search_value_invalid', {
        field: 'status',
        position,
        value: 'donee',
        reason: 'not_allowed',
        allowed: ['backlog', 'open'],
      }),
    );

    expect(relocated).toBeInstanceOf(ApiError);
    const error = relocated as ApiError;
    expect(error.code).toBe('search_value_invalid');
    expect(error.status).toBe(422);
    expect(error.details).toEqual({
      field: 'status',
      position: query.indexOf('donee'),
      value: 'donee',
      reason: 'not_allowed',
      allowed: ['backlog', 'open'],
      query,
    });
  });

  it('строка, которую бэкенд вернул, заменяется строкой человека', () => {
    const query = 'status: done and';
    const sent = hideArchive(query, NOW);

    const error = sent.relocate(
      refusal('invalid_search_query', { position: 17, query: sent.query, reason: 'x' }),
    ) as ApiError;

    // Замерено на живом бэкенде (UI-97#5): одна строка — 16, в склейке — 17.
    expect(error.details.position).toBe(16);
    expect(error.details.query).toBe(query);
  });

  it('позиция за краем его строки — это конец его строки', () => {
    const query = 'status: done and';
    const sent = hideArchive(query, NOW);
    // Лимит условий, перешагнутый склейкой, бьёт в правило — далеко за его строкой.
    const inRule = sent.query.indexOf('last_entry_at');

    const error = sent.relocate(refusal('invalid_search_query', { position: inRule })) as ApiError;
    expect(error.details.position).toBe(query.length);
  });

  it('чужие отказы и отказы без позиции не трогает', () => {
    const sent = hideArchive('status: done', NOW);

    const withoutPosition = refusal('internal_error', {});
    expect(sent.relocate(withoutPosition)).toBe(withoutPosition);

    const foreign = new Error('network');
    expect(sent.relocate(foreign)).toBe(foreign);
  });
});
