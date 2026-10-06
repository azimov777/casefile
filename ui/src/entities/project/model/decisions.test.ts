import { describe, expect, it } from 'vitest';
import { decisionHref, decisionNo, decisionTasksQuery } from './decisions';

describe('ссылка на решение проекта', () => {
  it('ведёт на экран проекта с раскрытой записью решения', () => {
    expect(decisionHref('TRK#15')).toBe('/projects/TRK?entry=15');
    expect(decisionNo('OPS#3')).toBe(3);
  });

  it('строку не той формы не превращает в номер', () => {
    expect(decisionNo('TRK-1#2')).toBeNull();
    expect(decisionHref('TRK')).toBe('/projects/TRK');
  });

  it('отбор задач по решению — условие языка запросов бэкенда', () => {
    expect(decisionTasksQuery('TRK#15')).toBe('decision: TRK#15');
  });
});
