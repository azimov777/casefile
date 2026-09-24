import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { ApiError } from '../api';
import { LANGUAGES, dictionaries, en, i18n, ru } from '../i18n';
import { errorMessage, errorText, fieldReasonText } from './text';

/**
 * Справочник кодов бэкенда собирается из его кода командой, значит его можно сверять,
 * а не переписывать на глаз. Новый код на бэкенде роняет `pnpm check` здесь — раньше,
 * чем английская фраза доедет до человека.
 */
const ERRORS_MD = resolve(process.cwd(), '../docs/ERRORS.md');

function codesFromReference(): string[] {
  const rows = readFileSync(ERRORS_MD, 'utf8').matchAll(/^\| `([a-z_]+)` \|/gm);
  return [...rows].map((row) => row[1] as string);
}

describe('словарь ошибок', () => {
  /*
   * Полнота спрашивается с каждого языка отдельно, а не с одного за всех: код,
   * переведённый только на русский, — это английский экран с русской фразой посреди
   * него, и поймать это обязана проверка, а не человек.
   */
  it.each(LANGUAGES)('словарь %s покрывает каждый код из справочника бэкенда', (language) => {
    const codes = codesFromReference();

    expect(codes.length).toBeGreaterThan(40);
    expect(
      codes.filter((code) => !(code in dictionaries[language].errors)),
      `Дополни словарь src/shared/i18n/dictionaries/${language}/errors.ts`,
    ).toEqual([]);
  });

  it('русские тексты на русском и заканчиваются точкой', () => {
    for (const [code, text] of Object.entries(ru.errors)) {
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
describe.each(LANGUAGES)('errorText на языке %s', (language) => {
  const dictionary = dictionaries[language];

  beforeAll(() => {
    void i18n.changeLanguage(language);
  });

  afterAll(() => {
    void i18n.changeLanguage('en');
  });

  it('берёт текст по коду', () => {
    expect(errorText('unauthorized')).toBe(dictionary.errors.unauthorized);
  });

  it('берёт на своём языке и тот код, что переехал из старого словаря последним', () => {
    expect(errorText('task_not_found')).toBe(dictionary.errors.task_not_found);
  });

  it('неизвестный код показывает фразу бэкенда и сам код', () => {
    expect(errorText('brand_new_code', 'Something odd')).toBe('Something odd (brand_new_code)');
  });

  it('неизвестный код без фразы бэкенда всё равно называет код', () => {
    expect(errorText('brand_new_code')).toBe(
      dictionary.ui.error.unknownCode.replace('{{code}}', 'brand_new_code'),
    );
  });
});

/*
 * В отличие от `errors`, `fieldReasons` не обязан покрывать причины бэкенда целиком
 * (`shared/i18n/dictionaries/ru/field-reasons.ts`), поэтому здесь нет проверки
 * полноты со справочником — только качество того, что в словаре есть, и запасной
 * текст для причины, которой в нём нет.
 */
describe('словарь причин у поля', () => {
  it('русские тексты на русском и заканчиваются точкой', () => {
    for (const [reason, text] of Object.entries(ru.fieldReasons)) {
      expect(text, reason).toMatch(/[А-Яа-яЁё]/);
      expect(text, reason).toMatch(/[.:]$/);
    }
  });

  it('английские тексты без кириллицы и заканчиваются точкой', () => {
    for (const [reason, text] of Object.entries(en.fieldReasons)) {
      expect(text, reason).not.toMatch(/[А-Яа-яЁё]/);
      expect(text, reason).toMatch(/[.:]$/);
    }
  });
});

describe.each(LANGUAGES)('fieldReasonText на языке %s', (language) => {
  const dictionary = dictionaries[language];

  beforeAll(() => {
    void i18n.changeLanguage(language);
  });

  afterAll(() => {
    void i18n.changeLanguage('en');
  });

  it('берёт текст по коду причины', () => {
    expect(fieldReasonText('too_long')).toBe(dictionary.fieldReasons.too_long);
  });

  it('причина без перевода называет сам код в запасном тексте', () => {
    expect(fieldReasonText('brand_new_reason')).toBe(
      dictionary.ui.error.unknownFieldReason.replace('{{reason}}', 'brand_new_reason'),
    );
  });
});

describe('errorMessage', () => {
  beforeAll(() => {
    void i18n.changeLanguage('ru');
  });

  afterAll(() => {
    void i18n.changeLanguage('en');
  });

  it('отказ бэкенда переводит по коду', () => {
    const failure = new ApiError('task_not_found', 'Task not found', 404, {});

    expect(errorMessage(failure)).toBe(ru.errors.task_not_found);
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
