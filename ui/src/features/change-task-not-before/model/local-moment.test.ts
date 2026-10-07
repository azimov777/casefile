import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { fromLocalInput, toLocalInput } from './local-moment';

/* Пояс браузера — Берлин: осенью +02:00 до перевода часов 25 октября, зимой +01:00. */
const was = process.env.TZ;
beforeAll(() => {
  process.env.TZ = 'Europe/Berlin';
});
afterAll(() => {
  if (was === undefined) delete process.env.TZ;
  else process.env.TZ = was;
});

describe('момент между полем и контрактом', () => {
  it('ввод 12 октября 09:00 уходит со смещением +02:00', () => {
    expect(fromLocalInput('2026-10-12T09:00')).toBe('2026-10-12T09:00:00+02:00');
  });

  it('смещение берётся у самого момента: зимой +01:00', () => {
    expect(fromLocalInput('2026-12-01T09:00')).toBe('2026-12-01T09:00:00+01:00');
  });

  it('ответ 07:00Z раскладывается в 09:00 местного времени', () => {
    expect(toLocalInput('2026-10-12T07:00:00Z')).toBe('2026-10-12T09:00');
  });

  it('пустое и негодное — ничего', () => {
    expect(fromLocalInput('')).toBeNull();
    expect(toLocalInput(null)).toBe('');
    expect(toLocalInput('не момент')).toBe('');
  });
});
