import { describe, expect, it } from 'vitest';
import type { Setting } from '../api/settings';
import { amountOf, parseCanonical, splitAmount, toCanonical, unitsOf } from './amount';

const integer = { kind: 'integer' } as const;
const duration = { kind: 'duration' } as const;

function setting(name: string, kind: Setting['kind'], effective: string): Setting {
  return {
    name,
    env_var: 'TRACKER_X',
    kind,
    value: null,
    effective_value: effective,
    source: 'default',
    default_value: effective,
    default_source: 'default',
    minimum: null,
    maximum: null,
    updated_by: null,
    updated_at: null,
  };
}

describe('значение настройки', () => {
  it('срок читается из секунд, число — из строки, чужой вид не выдумывается', () => {
    expect(parseCanonical(duration, 'PT2592000S')).toBe(2_592_000);
    expect(parseCanonical(duration, 'P30D')).toBeNull();
    expect(parseCanonical(integer, '168')).toBe(168);
    expect(parseCanonical(integer, 'abc')).toBeNull();
    expect(parseCanonical({ kind: 'boolean' }, 'true')).toBeNull();
  });

  it('берётся самая крупная единица без остатка', () => {
    expect(splitAmount('file_max_bytes', 26_214_400)).toMatchObject({
      amount: 25,
      unit: { id: 'megabytes' },
    });
    expect(splitAmount('file_max_bytes', 1500)).toMatchObject({
      amount: 1500,
      unit: { id: 'bytes' },
    });
    expect(splitAmount('oauth_access_ttl', 2_592_000)).toMatchObject({
      amount: 30,
      unit: { id: 'days' },
    });
    expect(splitAmount('oauth_access_ttl', 5400)).toMatchObject({
      amount: 90,
      unit: { id: 'minutes' },
    });
    expect(splitAmount('session_hours', 168)).toMatchObject({ amount: 7, unit: { id: 'days' } });
    expect(amountOf(setting('mcp_page_size', 'integer', '25'))).toMatchObject({ amount: 25 });
  });

  it('введённое число уходит в каноническую строку той же настройки', () => {
    const days = unitsOf('oauth_access_ttl').find((unit) => unit.id === 'days');
    const mega = unitsOf('file_max_bytes').find((unit) => unit.id === 'megabytes');
    expect(days && toCanonical(duration, '30', days)).toBe('PT2592000S');
    expect(mega && toCanonical(integer, '25', mega)).toBe('26214400');
  });

  it('не целое и пустое до сервера не доходит', () => {
    const [only] = unitsOf('mcp_page_size');
    expect(only && toCanonical(integer, '1.5', only)).toBeNull();
    expect(only && toCanonical(integer, '', only)).toBeNull();
    expect(only && toCanonical(integer, '-3', only)).toBeNull();
  });
});
