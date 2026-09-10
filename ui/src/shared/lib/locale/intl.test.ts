import { describe, expect, it } from 'vitest';
import { LANGUAGES } from '../../i18n';
import { formatNumber, perLanguage } from './intl';

describe('разбор форматтеров по языку', () => {
  it('строит по одному на язык и отдаёт тот же самый на повторе', () => {
    let built = 0;
    const get = perLanguage((language) => {
      built += 1;
      return { language };
    });

    const english = get('en');
    expect(get('en')).toBe(english);
    expect(built).toBe(1);

    expect(get('ru')).not.toBe(english);
    expect(built).toBe(2);

    // Сотня обращений после того, как оба языка построены, не строит ничего.
    for (let call = 0; call < 100; call += 1) for (const language of LANGUAGES) get(language);
    expect(built).toBe(LANGUAGES.length);
  });
});

describe('число для человека', () => {
  it('разделяет разряды по правилам языка', () => {
    // Сами разделители у языков разные, и называть их здесь строкой значило бы завести
    // ту самую свою таблицу. Проверяется другое: разделитель появился, он не цифра,
    // и у языков он не один и тот же.
    const english = formatNumber(1234567, 'en');
    const russian = formatNumber(1234567, 'ru');

    expect(english).not.toBe(russian);
    expect(english.replace(/\D/gu, '')).toBe('1234567');
    expect(russian.replace(/\D/gu, '')).toBe('1234567');
    expect(english).toMatch(/\D/u);
    expect(russian).toMatch(/\D/u);
  });

  it('короткое число остаётся собой на любом языке', () => {
    for (const language of LANGUAGES) {
      expect(formatNumber(0, language)).toBe('0');
      expect(formatNumber(42, language)).toBe('42');
      expect(formatNumber(999, language)).toBe('999');
    }
  });
});
