import { describe, expect, it } from 'vitest';
import { PROJECT_DESCRIPTION_LIMIT, descriptionLength } from './description';

describe('длина описания проекта', () => {
  it('меряется после обрезки пробелов по краям, как у бэкенда', () => {
    expect(descriptionLength('  что это  \n')).toBe(7);
  });

  it('считает кодовые точки: знак вне основной плоскости — один знак, а не два', () => {
    expect('🙂'.length).toBe(2);
    expect(descriptionLength('🙂')).toBe(1);
  });

  it('предел — 320 знаков, как `MAX_PROJECT_DESCRIPTION_LENGTH` бэкенда', () => {
    expect(PROJECT_DESCRIPTION_LIMIT).toBe(320);
  });
});
