import { describe, expect, it } from 'vitest';
import { PAGE_GAP, pageCount, pageWindow } from './paging';

describe('pageCount', () => {
  it('делит выдачу на страницы с округлением вверх', () => {
    expect(pageCount(98, 50)).toBe(2);
    expect(pageCount(100, 50)).toBe(2);
    expect(pageCount(101, 50)).toBe(3);
  });

  it('пустая выдача — ноль страниц, а не одна', () => {
    expect(pageCount(0, 50)).toBe(0);
  });

  it('неполная первая страница всё равно страница', () => {
    expect(pageCount(7, 50)).toBe(1);
  });
});

describe('pageWindow', () => {
  it('короткую выдачу показывает номерами целиком', () => {
    expect(pageWindow(1, 4)).toEqual([1, 2, 3, 4]);
  });

  it('в середине даёт ряд из задачи: 1 2 [3] 4 … 7', () => {
    expect(pageWindow(3, 7)).toEqual([1, 2, 3, 4, PAGE_GAP, 7]);
  });

  it('у краёв окно сдвигается внутрь, а не ужимается', () => {
    expect(pageWindow(1, 7)).toEqual([1, 2, 3, PAGE_GAP, 7]);
    expect(pageWindow(7, 7)).toEqual([1, PAGE_GAP, 5, 6, 7]);
  });

  it('одну спрятанную страницу показывает номером, а не многоточием', () => {
    expect(pageWindow(1, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it('номер за концом выдачи не растягивает ряд: окно встаёт у последней страницы', () => {
    expect(pageWindow(99, 7)).toEqual([1, PAGE_GAP, 5, 6, 7]);
  });

  it('у выдачи без страниц ряда нет', () => {
    expect(pageWindow(1, 0)).toEqual([]);
  });
});
