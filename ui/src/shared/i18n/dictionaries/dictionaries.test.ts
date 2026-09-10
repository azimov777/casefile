import { describe, expect, it } from 'vitest';
import { LANGUAGES } from '../languages';
import { dictionaries } from './index';

/*
 * Наборы ключей всех словарей обязаны совпадать.
 *
 * Компилятор видит только английский: типы ключей построены на нём (`i18next.d.ts`),
 * поэтому пропажу ключа из английского он ловит сам, а пропажу из русского — нет.
 * Ловит её этот тест, и потому подпись, забытая в одном языке, роняет `pnpm check`,
 * а не доезжает до человека английской фразой посреди русского экрана.
 */

/**
 * Множественное число даёт языку разное число ключей на одну фразу: в английском две
 * формы (`_one`, `_other`), в русском четыре (`_one`, `_few`, `_many`, `_other`).
 * Сравнивать их в лоб нельзя — иначе честная плюрализация выглядела бы расхождением.
 * Сравнивается фраза, а не форма: суффикс формы отбрасывается.
 *
 * Формы перечислены по `Intl.PluralRules`, а своей таблицы у нас нет и не будет.
 */
const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

/** Плоский список ключей словаря: `login.submit`, `errors.unauthorized`. */
function keysOf(node: unknown, prefix = '', stripForm = true): string[] {
  if (typeof node !== 'object' || node === null) {
    return [stripForm ? prefix.replace(PLURAL_SUFFIX, '') : prefix];
  }

  return Object.entries(node).flatMap(([key, value]) =>
    keysOf(value, prefix === '' ? key : `${prefix}.${key}`, stripForm),
  );
}

function sortedKeys(language: keyof typeof dictionaries): string[] {
  return [...new Set(keysOf(dictionaries[language]))].sort();
}

describe('словари языков', () => {
  it('перечислены все поддержанные языки и ничего сверх', () => {
    expect(Object.keys(dictionaries).sort()).toEqual([...LANGUAGES].sort());
  });

  it('набор ключей одинаков во всех языках', () => {
    const reference = sortedKeys('en');

    expect(reference.length).toBeGreaterThan(10);
    for (const language of LANGUAGES) {
      expect(sortedKeys(language), `словарь ${language}`).toEqual(reference);
    }
  });

  it('ни одна подпись не осталась непереведённой копией английской', () => {
    // Совпадение текста законно там, где переводить нечего: подсказка формата токена,
    // пример на языке запросов бэкенда, подстановка кода ошибки и приписка к заголовку
    // разбора — знак и подстановка, без единого слова.
    const sameOnPurpose = new Set([
      'login.tokenPlaceholder',
      'tasks.filters.query.placeholder',
      'ui.error.withCode',
      'ui.entry.headline.resolutionOutcome',
    ]);

    /*
     * Сравниваются полные ключи, вместе с формой множественного числа: у стёртой формы
     * (`tasks.found`) значения нет ни в одном языке, и два `undefined` прошли бы за
     * непереведённую копию. Формы, которых в английском нет вовсе (`_few`, `_many`),
     * сравнивать не с чем — они пропускаются.
     */
    const copied = fullKeys('en').filter((key) => {
      if (sameOnPurpose.has(key.replace(PLURAL_SUFFIX, ''))) return false;
      const russian = phrase('ru', key);
      return russian !== undefined && phrase('en', key) === russian;
    });

    expect(copied).toEqual([]);
  });
});

/** Плоский список ключей вместе с формой множественного числа. */
function fullKeys(language: keyof typeof dictionaries): string[] {
  return keysOf(dictionaries[language], '', false).sort();
}

function phrase(language: keyof typeof dictionaries, key: string): unknown {
  return key
    .split('.')
    .reduce<unknown>(
      (node, step) =>
        typeof node === 'object' && node !== null
          ? (node as Record<string, unknown>)[step]
          : undefined,
      dictionaries[language],
    );
}
