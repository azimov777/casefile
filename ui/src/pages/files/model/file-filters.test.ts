import { describe, expect, it } from 'vitest';
import { activeConditions, readFileFilter, typePresetOf, withFilter } from './file-filters';

describe('readFileFilter', () => {
  it('без параметров — умолчание: свежие добавленные первыми, без условий', () => {
    const filter = readFileFilter(new URLSearchParams());
    expect(filter).toEqual({
      q: '',
      project: null,
      mimeType: null,
      sort: 'added',
      descending: true,
      unopened: false,
    });
    expect(activeConditions(filter)).toBe(0);
  });

  it('читает поиск, проект, вид, порядок и направление', () => {
    const filter = readFileFilter(
      new URLSearchParams('q=схема&project=TRK&type=pdf&sort=size&order=asc'),
    );
    expect(filter.q).toBe('схема');
    expect(filter.project).toBe('TRK');
    expect(filter.mimeType).toBe('application/pdf');
    expect(filter.sort).toBe('size');
    expect(filter.descending).toBe(false);
    expect(activeConditions(filter)).toBe(3);
    expect(typePresetOf(filter)).toBe('pdf');
  });

  it('неизвестные вид и порядок отбрасываются, а не уходят на сервер', () => {
    const filter = readFileFilter(new URLSearchParams('type=exe&sort=name'));
    expect(filter.mimeType).toBeNull();
    expect(filter.sort).toBe('added');
  });
});

describe('withFilter', () => {
  it('не пишет умолчания в адрес', () => {
    const params = new URLSearchParams('sort=size&order=asc&q=a');
    expect(withFilter(params, { sort: 'added', descending: true, q: '' }).toString()).toBe('');
  });

  it('сохраняет чужие параметры адреса', () => {
    const params = new URLSearchParams('walk=3');
    expect(withFilter(params, { type: 'image' }).toString()).toBe('walk=3&type=image');
  });
});
