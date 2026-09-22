import { describe, expect, it } from 'vitest';
import { CLIENT_PARAM, DEFAULT_CLIENT, parseClient, withClient } from './client';

describe('клиент фрагментов в адресе', () => {
  it('незнакомое и пустое значение — умолчание, знакомое — оно само', () => {
    expect(parseClient(null)).toBe(DEFAULT_CLIENT);
    expect(parseClient('')).toBe(DEFAULT_CLIENT);
    expect(parseClient('vim')).toBe(DEFAULT_CLIENT);
    expect(parseClient('codex')).toBe('codex');
  });

  it('умолчание параметра не пишет, прочие параметры остаются', () => {
    const params = new URLSearchParams('shared=true&client=json');

    expect(withClient(params, 'codex').toString()).toBe('shared=true&client=codex');
    expect(withClient(params, DEFAULT_CLIENT).has(CLIENT_PARAM)).toBe(false);
    expect(withClient(params, DEFAULT_CLIENT).get('shared')).toBe('true');
    // Исходные параметры не тронуты: функция отдаёт новые.
    expect(params.get(CLIENT_PARAM)).toBe('json');
  });
});
