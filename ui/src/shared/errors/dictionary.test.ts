import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ApiError } from '../api';
import { en, i18n, ru } from '../i18n';
import { errorDictionary } from './dictionary';
import { errorMessage, errorText } from './text';

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

/*
 * Источников текста два, и это переезд, а не устройство: коды экрана входа уже живут
 * в словарях языков, остальные ждут UI-78 в `dictionary.ts`. Полнота считается по обоим
 * сразу — иначе переезд ослабил бы проверку ровно в тот момент, когда она нужнее всего.
 */
function covered(code: string): boolean {
  return code in ru.errors || errorDictionary[code] !== undefined;
}

describe('словарь ошибок', () => {
  it('покрывает каждый код из справочника бэкенда', () => {
    const codes = codesFromReference();

    expect(codes.length).toBeGreaterThan(40);
    expect(
      codes.filter((code) => !covered(code)),
      'Дополни словарь src/shared/i18n/dictionaries/*/errors.ts',
    ).toEqual([]);
  });

  it('код лежит в одном месте: переехавший не остался и в старом словаре', () => {
    expect(Object.keys(ru.errors).filter((code) => errorDictionary[code] !== undefined)).toEqual(
      [],
    );
  });

  it('русские тексты на русском и заканчиваются точкой', () => {
    for (const [code, text] of Object.entries({ ...errorDictionary, ...ru.errors })) {
      expect(text, code).toMatch(/[А-Яа-яЁё]/);
      expect(text, code).toMatch(/[.:]$/);
    }
  });

  it('английские тексты без кириллицы и заканчиваются точкой', () => {
    for (const [code, text] of Object.entries(en.errors)) {
      expect(text, code).not.toMatch(/[А-Яа-яЁё]/);
      expect(text, code).toMatch(/[.:]$/);
    }
  });
});

/*
 * Язык подставляется явно: текст отказа берётся из словаря по языку интерфейса, и
 * модульный тест не вправе зависеть от того, на какой машине он запущен.
 */
describe.each(['ru', 'en'] as const)('errorText на языке %s', (language) => {
  const dictionary = language === 'ru' ? ru : en;

  beforeAll(() => {
    void i18n.changeLanguage(language);
  });

  afterAll(() => {
    void i18n.changeLanguage('ru');
  });

  it('берёт текст по коду', () => {
    expect(errorText('unauthorized')).toBe(dictionary.errors.unauthorized);
  });

  it('неизвестный код показывает фразу бэкенда и сам код', () => {
    expect(errorText('brand_new_code', 'Something odd')).toBe('Something odd (brand_new_code)');
  });

  it('неизвестный код без фразы бэкенда всё равно называет код', () => {
    expect(errorText('brand_new_code')).toBe(
      dictionary.ui.error.unknownCode.replace('{{code}}', 'brand_new_code'),
    );
  });

  it('код, ещё не переехавший в словари, показывается по-русски на любом языке', () => {
    // Названная цена незаконченного переезда: UI-78 её снимает.
    expect(errorText('task_not_found')).toBe(errorDictionary.task_not_found);
  });
});

describe('errorMessage', () => {
  beforeAll(() => {
    void i18n.changeLanguage('ru');
  });

  it('отказ бэкенда переводит по коду', () => {
    const failure = new ApiError('task_not_found', 'Task not found', 404, {});

    expect(errorMessage(failure)).toBe('Задачи с таким ключом нет.');
  });

  it('обрыв связи объясняет тем же словарём: код придуман клиентом', () => {
    expect(errorMessage(ApiError.network(new Error('fetch failed')))).toBe(ru.errors.network_error);
  });

  it('исключение не из API показывает своё сообщение', () => {
    expect(errorMessage(new Error('Внезапно'))).toBe('Внезапно');
  });

  it('брошенное не-исключение не выдаётся за ошибку контракта', () => {
    expect(errorMessage('строка')).toBe(ru.ui.error.unknown);
  });
});
