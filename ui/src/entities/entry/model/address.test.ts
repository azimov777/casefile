import { describe, expect, it } from 'vitest';
import { entryAddress } from './address';

describe('entryAddress', () => {
  it('собирает адрес карточки с номером записи на источнике страницы', () => {
    expect(entryAddress({ kind: 'task', key: 'UI-124' }, 16, 'http://127.0.0.1:8080')).toBe(
      'http://127.0.0.1:8080/tasks/UI-124?entry=16',
    );
  });

  it('не тащит путь текущей страницы: адрес дела даёт тот же адрес карточки', () => {
    expect(entryAddress({ kind: 'task', key: 'TRK-7' }, 3, 'https://tracker.example.org')).toBe(
      'https://tracker.example.org/tasks/TRK-7?entry=3',
    );
  });

  it('запись дела проекта открывается на экране проекта', () => {
    expect(entryAddress({ kind: 'project', key: 'TRK' }, 7, 'http://127.0.0.1:8080')).toBe(
      'http://127.0.0.1:8080/projects/TRK?entry=7',
    );
  });
});
