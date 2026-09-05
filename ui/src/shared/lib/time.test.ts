import { describe, expect, it } from 'vitest';
import { exactTime, relativeTime } from './time';

const NOW = Date.parse('2026-09-05T12:00:00Z');

function ago(milliseconds: number): string {
  return new Date(NOW - milliseconds).toISOString();
}

describe('относительное время', () => {
  it('свежую метку не считает в минутах', () => {
    expect(relativeTime(ago(20 * 1000), NOW)).toBe('только что');
  });

  it('часы, дни и месяцы считает своими единицами', () => {
    expect(relativeTime(ago(3 * 60 * 1000), NOW)).toMatch(/3 мин/);
    expect(relativeTime(ago(5 * 60 * 60 * 1000), NOW)).toMatch(/5 ч/);
    expect(relativeTime(ago(3 * 24 * 60 * 60 * 1000), NOW)).toMatch(/3 дн/);
    expect(relativeTime(ago(60 * 24 * 60 * 60 * 1000), NOW)).toMatch(/2 мес/);
  });

  it('часы сервера впереди наших не превращаются в «через минуту»', () => {
    expect(relativeTime(ago(-30 * 1000), NOW)).toBe('только что');
  });

  it('пустое и неразбираемое значение не выдумывает', () => {
    expect(relativeTime(null, NOW)).toBe('');
    expect(relativeTime(undefined, NOW)).toBe('');
    expect(relativeTime('позавчера', NOW)).toBe('');
  });
});

describe('точное время', () => {
  it('показывает дату и время', () => {
    expect(exactTime('2026-09-05T12:00:00Z')).toMatch(/2026/);
  });

  it('пустое значение оставляет пустым', () => {
    expect(exactTime(null)).toBe('');
  });
});
