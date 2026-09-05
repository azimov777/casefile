import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { errorDictionary } from './dictionary';
import { errorText } from './text';

/**
 * Справочник кодов бэкенда собирается из его кода командой, значит его можно сверять,
 * а не переписывать на глаз. Новый код на бэкенде роняет `pnpm check` здесь — раньше,
 * чем английская фраза доедет до человека.
 */
const ERRORS_MD = resolve(process.cwd(), '../tracker/docs/ERRORS.md');

function codesFromReference(): string[] {
  const rows = readFileSync(ERRORS_MD, 'utf8').matchAll(/^\| `([a-z_]+)` \|/gm);
  return [...rows].map((row) => row[1] as string);
}

describe('словарь ошибок', () => {
  it('покрывает каждый код из справочника бэкенда', () => {
    const codes = codesFromReference();

    expect(codes.length).toBeGreaterThan(40);
    expect(
      codes.filter((code) => errorDictionary[code] === undefined),
      'Дополни словарь src/shared/errors/dictionary.ts',
    ).toEqual([]);
  });

  it('тексты на русском и заканчиваются точкой', () => {
    for (const [code, text] of Object.entries(errorDictionary)) {
      expect(text, code).toMatch(/[А-Яа-яЁё]/);
      expect(text, code).toMatch(/[.:]$/);
    }
  });
});

describe('errorText', () => {
  it('берёт текст по коду', () => {
    expect(errorText('unauthorized')).toBe('Токен неизвестен или отозван.');
  });

  it('неизвестный код показывает фразу бэкенда и сам код', () => {
    expect(errorText('brand_new_code', 'Something odd')).toBe('Something odd (brand_new_code)');
  });

  it('неизвестный код без фразы бэкенда всё равно называет код', () => {
    expect(errorText('brand_new_code')).toBe('Неизвестная ошибка (brand_new_code).');
  });
});
